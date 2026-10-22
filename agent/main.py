# -*- coding: utf-8 -*-
"""FastAPI 入口：房间/Agent 接口，逐句输出 NDJSON。

启动：
    python -m agent.main
或：
    uvicorn agent.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agent import dream_service, rooms, schemas, service
from agent.affection.engine import STAGES
from agent.config import settings
from agent.db import repository
from agent.db.connection import ping as mysql_ping
from agent.db.schema import migrate
from agent.memory.manager import compress_candidates
from agent.llm import providers
from agent.persona import list_personas
from agent.rag.retriever import _milvus_client  # noqa: PLC2701 - 健康检查复用同一客户端

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

NDJSON_MEDIA_TYPE = "application/x-ndjson; charset=utf-8"
NDJSON_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        migrate()
        logger.info("MySQL 迁移完成。")
    except Exception as exc:  # noqa: BLE001 - 依赖不可用时仍保留房间与立绘
        logger.error("MySQL 迁移失败，记忆与关系功能将不可用：%s", exc)
    yield


app = FastAPI(title="红楼梦人物 Agent", version="0.3.0", lifespan=lifespan)

origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _uid(value: str | None) -> str:
    return (value or settings.default_user_id).strip() or settings.default_user_id


def _milvus_ok() -> bool:
    try:
        _milvus_client().has_collection(settings.milvus_collection)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus 不可用：%s", exc)
        return False


@app.get("/health")
def health() -> dict:
    """健康检查：逐项报告依赖，任一项不可用都不影响主链路降级。"""
    people = list_personas()
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "model": settings.ollama_model if settings.llm_provider != "deepseek" else settings.deepseek_model,
        "embed_model": settings.embed_model,
        "ollama_host": settings.ollama_host,
        "milvus": _milvus_ok(),
        "mysql": mysql_ping(),
        "protagonist": [item.name for item in people if item.is_protagonist],
        "supporting": [item.name for item in people if not item.is_protagonist],
        "stages": STAGES,
    }


@app.get("/api/state")
def state(user_id: str = Query(default="local_default"), character: str = Query(default=service.DEFAULT_CHARACTER)) -> dict:
    """前端只读取关系阶段与游戏内时间；配角没有关系阶段，返回空 stage。"""
    return service.state_of(user_id, character)


@app.get("/api/dream/list")
def dream_list(user_id: str = Query(default="local_default")) -> dict:
    """十四章的目录与本机进度。"""
    return dream_service.catalog(_uid(user_id))


@app.post("/api/dream/enter")
def dream_enter(
    request: schemas.DreamEnterRequest,
    x_deepseek_key: str | None = Header(default=None),
) -> StreamingResponse:
    """入梦：引梦 + 第一段正文与第一个选择点，走 NDJSON。"""
    return StreamingResponse(
        service.encode_stream(
            dream_service.enter_events(
                _uid(request.user_id), request.chapter_key, request.cast,
                x_deepseek_key, request.restart,
            )
        ),
        media_type=NDJSON_MEDIA_TYPE,
        headers=NDJSON_HEADERS,
    )


@app.post("/api/dream/choose")
def dream_choose(
    request: schemas.DreamChooseRequest,
    x_deepseek_key: str | None = Header(default=None),
) -> StreamingResponse:
    """做一个选择：结算预写后果，在席的人表态，并带回下一段。"""
    return StreamingResponse(
        service.encode_stream(
            dream_service.choose_events(
                _uid(request.user_id), request.chapter_key, request.node_key,
                request.option_key, x_deepseek_key,
            )
        ),
        media_type=NDJSON_MEDIA_TYPE,
        headers=NDJSON_HEADERS,
    )


@app.post("/api/dream/leave")
def dream_leave(request: schemas.DreamLeaveRequest) -> dict:
    """中途退出：保留进度，下次可接着来。"""
    return dream_service.leave(_uid(request.user_id), request.chapter_key)


@app.get("/api/characters")
def characters() -> dict:
    """十二位人物的名字、别号与常用称呼。

    前端拿它来判断"来客这一句提到了谁"——所以别名必须由后端一处给出，
    免得前后端各存一份、迟早对不上。
    """
    people = list_personas()
    return {
        "ok": True,
        "characters": [
            {
                "name": item.name,
                "courtesy": item.courtesy,
                "aliases": list(item.aliases),
                "role": item.role,
            }
            for item in people
        ],
    }


@app.get("/api/room")
def room_here(user_id: str = Query(default="local_default"), scene: str = Query(default="")) -> dict:
    """这间房此刻有谁。

    按 用户＋日＋时段＋场景 播种，所以同一时段内反复进出结果完全一致，
    结束会谈推进时段之后才会换人。前端不再自己持有人在场的名册。
    """
    try:
        user = repository.ensure_user(user_id)
        day = int(user.get("game_day") or 1)
        period = user.get("game_period") or "清晨"
    except Exception as exc:  # noqa: BLE001 - 时钟读不到就退化为第一天清晨，不影响进房
        logger.warning("读取游戏时钟失败，退化为第 1 日清晨：%s", exc)
        day, period = 1, "清晨"

    result = rooms.cast_for(user_id, day, period, scene)
    result["ok"] = True
    result["seed"] = {"user_id": user_id, "game_day": day, "game_period": period, "scene": scene}
    return result


@app.post("/api/dialogue")
def dialogue(
    request: schemas.DialogueRequest,
    x_deepseek_key: str | None = Header(default=None),
) -> StreamingResponse:
    """一次发言 → 逐句 NDJSON 事件流。speaker 声明本轮由谁应答。

    X-DeepSeek-Key 非空则本轮走 DeepSeek，密钥校验不过会先发一条错误事件再退回本地。
    密钥只在这次请求的内存里，不落盘、不进日志。
    """
    return StreamingResponse(
        service.dialogue_stream(request, x_deepseek_key),
        media_type=NDJSON_MEDIA_TYPE,
        headers=NDJSON_HEADERS,
    )


@app.post("/api/provider/check")
def provider_check(x_deepseek_key: str | None = Header(default=None)) -> dict:
    """校验前端填的 DeepSeek 密钥；空密钥表示"用本地"，不算错误。"""
    key = (x_deepseek_key or "").strip()
    if not key:
        return {
            "ok": True,
            "provider": "ollama",
            "model": settings.ollama_model,
            "detail": "",
            "message": "未填密钥，使用本地模型。",
        }
    usable, detail = providers.check_deepseek_key(key, use_cache=False)
    if usable:
        return {
            "ok": True,
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "detail": "",
            "message": f"密钥可用，将使用 DeepSeek（{settings.deepseek_model}）。",
        }
    return JSONResponse(
        status_code=200,
        content={
            "ok": False,
            "provider": "ollama",
            "model": settings.ollama_model,
            "detail": detail,
            "message": f"DeepSeek 密钥错误：{detail}。将使用本地模型。",
        },
    )


@app.post("/api/greeting")
def greeting(
    request: schemas.DialogueRequest,
    x_deepseek_key: str | None = Header(default=None),
) -> StreamingResponse:
    """主角入席问候，同样走 NDJSON，前端无需区分。"""
    return StreamingResponse(
        service.greeting_stream(
            request.user_id, request.present_characters, request.scene,
            x_deepseek_key, request.speaker, request.greeting_kind or "room",
        ),
        media_type=NDJSON_MEDIA_TYPE,
        headers=NDJSON_HEADERS,
    )


@app.post("/api/session/end")
def session_end(request: schemas.DialogueRequest) -> dict:
    """一次有效会谈结束：压缩主角的候选记忆并推进一个时段。"""
    user_id = (request.user_id or settings.default_user_id).strip() or settings.default_user_id
    try:
        repository.ensure_user(user_id)
        compressed = compress_candidates(user_id, service.DEFAULT_CHARACTER)
        clock = repository.advance_period(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("会话结算失败")
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})
    return {"ok": True, "compressed": compressed, "clock": clock}


@app.get("/api/history")
def history(user_id: str = Query(default="local_default"), limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    """完整聊天记录供回看；长期记忆与公开档案都不提供读取入口。"""
    try:
        rows = repository.full_history(user_id, limit)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})
    return {"ok": True, "messages": rows}


@app.post("/api/reset")
def reset(request: schemas.ResetRequest) -> dict:
    """完整世界重置：不可恢复，必须二次确认。"""
    if not request.confirm:
        return JSONResponse(status_code=400, content={"ok": False, "detail": "重置不可恢复，请显式确认。"})
    user_id = (request.user_id or settings.default_user_id).strip() or settings.default_user_id
    try:
        repository.reset_user(user_id)
        repository.ensure_user(user_id)
        repository.get_affection(user_id, service.DEFAULT_CHARACTER)
    except Exception as exc:  # noqa: BLE001
        logger.exception("重置失败")
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})
    return {"ok": True, "clock": {"game_day": 1, "game_period": "清晨"}, "stage": STAGES[0]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
