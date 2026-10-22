# -*- coding: utf-8 -*-
"""对话编排：把人物配置、检索、模型、房间记录与关系系统串成一条逐句事件流。

主角（林黛玉）与配角（其余十位）的分工：
- 共用：按需原著检索、逐句 NDJSON、房间公开记录、公开档案、危机时先安抚的守则；
- 主角独有：七阶段关系与隐藏好感度、私有记忆与定向遗忘、入席问候。
任何依赖失效都不伪造角色回复、不改动记忆与好感，只发异常事件。
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from typing import Any, Iterator

from agent import schemas, story
from agent.affection.engine import STAGES, apply_assessment
from agent.config import settings
from agent.db import repository
from agent.llm.generator import (
    DialogueContext,
    generate_greeting,
    generate_reply_stream,
    sanitize_address,
)
from agent.llm.providers import resolve_provider
from agent.memory.manager import (
    address_facts,
    build_memory_lines,
    collect_candidates,
    compress_candidates,
    detect_forget_request,
    forget_topic,
    profile_from_text,
)
from agent.persona import get_persona, list_personas
from agent.persona.base import Persona
from agent.rag.retriever import retrieve_for_answer, should_retrieve
from agent.safety import detect_crisis

logger = logging.getLogger(__name__)

DEFAULT_CHARACTER = "林黛玉"
EMPTY_AFFECTION: dict[str, Any] = {"delta": 0.0, "event_type": "其他", "reason": "未记录"}


def encode(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def encode_stream(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """把事件流编成 NDJSON 行流；异常兜底成一张异常卡，不让连接悬着。"""
    try:
        for event in events:
            yield encode(event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("事件流异常终止")
        yield encode(schemas.error_event("流程中断，请稍后再试。", str(exc)))
        yield encode(schemas.round_end())


def resolve_persona(request: schemas.DialogueRequest) -> Persona | None:
    """按显式 speaker 取人物；缺省时退回在场名单里第一个认识的，最后退回主角。"""
    persona = get_persona(request.speaker or "")
    if persona is not None:
        return persona
    for name in request.present_characters or []:
        persona = get_persona(name)
        if persona is not None:
            return persona
    return get_persona(DEFAULT_CHARACTER)


def _present_names(requested: list[str], persona: Persona) -> list[str]:
    names = [name for name in (requested or []) if name]
    if persona.name not in names:
        names.insert(0, persona.name)
    return names


def _game_time(user: dict[str, Any]) -> str:
    return f"第{int(user.get('game_day') or 1)}日·{user.get('game_period') or '清晨'}"


def _notes(crisis: bool, forget_result: dict[str, Any] | None, evidence_count: int) -> list[str]:
    notes: list[str] = []
    if crisis:
        notes.append(
            "来客此刻可能身处现实危险：先以温言安抚，绝不责备、嗔怪或说他不该如此；"
            "以深切而不失分寸的关切相劝，绝不把悲剧浪漫化，也不要提供任何伤害自己的方法"
        )
    if forget_result and forget_result.get("count"):
        notes.append("来客要求你忘记某些旧事，你已经应下并将它们放下，可以极含蓄地应一句，不必复述内容")
    if evidence_count == 0:
        notes.append("本轮没有可用的原著片段，涉及原著事实时须坦率保留，不得编造")
    return notes


def _apply_vignette(user_id: str, vignette: story.Vignette, user: dict[str, Any]) -> None:
    """关目首触发：把心绪、心事与态度改动写进 hlm_character_state。"""
    day = int(user.get("game_day") or 1)
    for effect in vignette.effects:
        current = repository.ensure_character_state(user_id, effect.character)
        repository.set_character_state(
            user_id,
            effect.character,
            mood=effect.mood or None,
            secret=effect.secret or None,
            attitude=current["attitude"] + effect.attitude,
            game_day=day,
        )


def _room_story(
    user_id: str,
    persona: Persona,
    present: list[str],
    scene: str | None,
    user: dict[str, Any],
    *,
    entry: bool,
) -> list[str]:
    """本房的房间小关目。

    进门（入席问候）时只首启"没经历过的"，首触发即写人物状态并记档；
    谈话过程中只用较低的频率回望"已经历过的"，免得每一轮都冒出一桩原著旧事、盖过正常交谈。

    任何异常都不该让对话开不了口，所以整段吞掉异常、退化为"没有特别的事"。
    """
    if not scene:
        return []
    try:
        triggered = repository.triggered_vignettes(user_id)
        if entry:
            chosen = story.pick(scene, present, triggered, random.Random(), mode=story.PICK_FRESH)
        else:
            chosen = story.pick(
                scene,
                present,
                triggered,
                random.Random(),
                chance=story.VIGNETTE_CHANCE * 0.4,
                mode=story.PICK_RECALL,
            )
        if chosen is None:
            return []
        if entry:
            _apply_vignette(user_id, chosen, user)
            repository.record_event(user_id, persona.name, "关目:" + chosen.key, chosen.quote)
            logger.info("关目首触发：%s（%s）", chosen.key, "、".join(e.character for e in chosen.effects))
            return story.story_lines(chosen, True)
        logger.info("关目回望：%s", chosen.key)
        return story.story_lines(chosen, False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("关目装配失败，本轮按无特别之事处理：%s", exc)
        return []


def _room_snapshot(user_id: str, scene: str | None = None) -> list[dict[str, Any]]:
    """房里最近说过的话——同一间房里全体真实角色共享的公开信息。

    按 scene 过滤：换院子之后，上一间房说过的话不该再被当成「房里说过的话」。
    """
    return [
        {
            "speaker": row.get("speaker") or "",
            "text": row.get("text") or "",
            "self": bool(row.get("self_turn")),
        }
        for row in repository.recent_chat(user_id, scene)
    ]


def _drop_current_round(room: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """砍掉本轮里别人已经做出的答复，只留到来客这一句为止。

    同一轮里后开口的人如果看得到前一位的完整答复，4B 模型会照着复述一遍
    （实测逐句雷同）。指令层面的"别重复"拦不住，只能从上下文里拿掉。
    这些答复仍会写进房间记录，所以下一轮起他们照样记得对方说过什么。
    """
    last_self = -1
    for index, item in enumerate(room):
        if item.get("self"):
            last_self = index
    return room[: last_self + 1] if last_self >= 0 else room


def _mentioned_note(user_text: str, present: list[str]) -> list[str]:
    """来客这一句点到了谁。

    在场的人交给自己开口（由前端挑应答者），这里只提醒"被提到但不在场"的那些：
    可以谈论、可以转述，但别替他们说出此刻的台词。
    """
    if not user_text:
        return []
    onstage = {name for name in present if name}
    absent: list[str] = []
    for persona in list_personas():
        if persona.name in onstage:
            continue
        names = [persona.name, *[item for item in persona.aliases if item]]
        if any(name and name in user_text for name in names):
            absent.append(persona.name)
    if not absent:
        return []
    who = "、".join(absent)
    return [
        f"来客这一句提到了{who}，但{who}此刻都不在这间屋子里："
        "可以谈起他们、也可以转述他们说过的话，但不要替他们说出此刻的台词，"
        "也不要假装他们就在旁边。"
    ]


def _provider_or_notice(
    api_key: str | None,
) -> tuple[Any, str]:
    """定下本轮的模型提供器。前端填了 DeepSeek 密钥就以它为准，验不过则退回本地并带回提示。"""
    try:
        return resolve_provider(api_key)
    except Exception as exc:  # noqa: BLE001
        logger.exception("提供器不可用")
        return None, f"模型不可用：{exc}"


def dialogue_events(request: schemas.DialogueRequest, api_key: str | None = None) -> Iterator[dict[str, Any]]:
    """一次发言对应的完整事件序列。"""
    persona = resolve_persona(request)
    if persona is None:
        yield schemas.error_event("没有找到可用的角色配置。")
        yield schemas.round_end()
        return

    user_id = (request.user_id or settings.default_user_id).strip() or settings.default_user_id
    session_id = uuid.uuid4().hex[:12]
    user_text = (request.text or "").strip()
    if not user_text:
        yield schemas.error_event("这一句是空的，未曾落笔。")
        yield schemas.round_end()
        return

    # 0. 先定提供器：密钥有问题就当场说，不要等检索与生成都跑完才告诉用户
    provider, provider_notice = _provider_or_notice(api_key)
    if provider_notice:
        yield schemas.error_event(provider_notice)
        if provider is None:
            yield schemas.round_end()
            return

    # 1. 公开档案 + 状态装配（主角另需压缩上一轮的候选记忆）
    try:
        repository.ensure_user(user_id)
        for key, value in profile_from_text(user_text).items():
            repository.upsert_profile_fact(user_id, key, value)
        profile = repository.get_profile_facts(user_id)
        if persona.has_private_memory:
            compress_candidates(user_id, persona.name)
        user = repository.ensure_user(user_id)
        room = _room_snapshot(user_id, request.scene)
        if request.round_index > 0:
            room = _drop_current_round(room)
        memory_lines = build_memory_lines(user_id, persona.name) if persona.has_private_memory else []
        stage = repository.get_affection(user_id, persona.name)["stage"] if persona.has_relationship else ""
    except Exception as exc:  # noqa: BLE001 - MySQL 不可用：显示异常卡，保留房间与立绘
        logger.exception("状态装配失败")
        yield schemas.error_event("记忆与关系暂不可用，请稍后再试。", str(exc))
        yield schemas.round_end()
        return

    # 2. 定向遗忘（只有主角持有私有记忆）
    forget_result: dict[str, Any] | None = None
    if persona.has_private_memory:
        topic = detect_forget_request(user_text)
        if topic:
            try:
                forget_result = forget_topic(user_id, persona.name, topic)
            except Exception as exc:  # noqa: BLE001
                logger.warning("定向遗忘失败：%s", exc)

    # 3. 危机识别：不发独立安全卡，只把守则写进本轮提示
    crisis = detect_crisis(user_text)

    # 4. 先记下来客这句（房间记录已在上方取过，不会重复）
    try:
        repository.append_chat(user_id, session_id, "我", user_text, self_turn=True, scene=request.scene or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("记录来客发言失败：%s", exc)

    # 5. 按需检索原著
    evidence = retrieve_for_answer(user_text)[0] if should_retrieve(user_text) else []
    confidence = max((item.score for item in evidence), default=0.0)
    evidence_payload = [item.to_dict() for item in evidence]

    # 6. 人物状态与房间小关目（都属"动态段"，放在提示词末尾）
    present_names = _present_names(request.present_characters, persona)
    try:
        state_lines = repository.state_lines(user_id, persona.name)
    except Exception as exc:  # noqa: BLE001 - 状态读不到不该让这一轮开不了口
        logger.warning("人物状态读取失败：%s", exc)
        state_lines = []
    story_lines = _room_story(user_id, persona, present_names, request.scene, user, entry=False)

    context = DialogueContext(
        speaker=persona.name,
        present=present_names,
        game_time=_game_time(user),
        profile=profile,
        memory=memory_lines,
        room=room,
        evidence=evidence,
        user_text=user_text,
        crisis=crisis,
        notes=_notes(crisis, forget_result, len(evidence)) + _mentioned_note(user_text, present_names),
        stage=stage,
        state=state_lines,
        story=story_lines,
    )

    # 6. 生成：模型不可用时不伪造台词（提供器已在第 0 步定好）
    # 7. 逐句输出：模型仍在续写时，已成的句子就先送出并开始转场
    guard_facts = address_facts(profile)
    sentences: list[dict[str, Any]] = []
    assessment: dict[str, Any] = dict(EMPTY_AFFECTION)
    started = False
    try:
        for label, payload in generate_reply_stream(provider, persona, context):
            if label == "sentence":
                if not started:
                    yield schemas.speaker_start(persona.name)
                    started = True
                payload["text"] = sanitize_address(payload["text"], guard_facts)
                # 称呼守卫可能把整句削成空串（极罕见），丢弃而不是发出空台词
                if not payload["text"].strip():
                    continue
                sentences.append(payload)
                yield schemas.sentence(
                    speaker=persona.name,
                    text=payload["text"],
                    emotion=payload["emotion"],
                    action=payload["action"],
                    intensity=payload["intensity"],
                    kind=payload["kind"],
                    confidence=confidence if evidence else None,
                    evidence=evidence_payload if len(sentences) == 1 and evidence_payload else None,
                )
            elif label == "affection":
                assessment = payload
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成失败")
        yield schemas.error_event("言语一时未能成句，请稍后再试。", str(exc))
        yield schemas.round_end()
        return

    if not sentences:
        yield schemas.error_event("未能成句，请再说一次。")
        yield schemas.round_end()
        return

    yield schemas.speaker_end(persona.name)

    # 8. 记下这位角色的回复（房间公开记录，人人可读）
    reply_text = "".join(item["text"] for item in sentences)
    try:
        repository.append_chat(
            user_id,
            session_id,
            persona.name,
            reply_text,
            emotion=sentences[0]["emotion"],
            action=sentences[0]["action"],
            kind=sentences[0]["kind"],
            self_turn=False,
            evidence_json=json.dumps(evidence_payload, ensure_ascii=False) if evidence_payload else None,
            scene=request.scene or "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("记录角色回复失败：%s", exc)

    settlement: dict[str, Any] = {
        "speaker": persona.name,
        "role": persona.role,
        "confidence": round(confidence, 3),
        "retrieved": len(evidence),
        "kind": sentences[0]["kind"],
    }

    # 9. 好感结算：只有主角参与，模型判断语义与诚意，规则限制幅度与阶段门槛
    if persona.has_relationship:
        try:
            result = apply_assessment(user_id, persona.name, assessment)
            settlement.update(
                {
                    "stage": result["stage"],
                    "stage_changed": result["stage_changed"],
                    "event_type": result["event_type"],
                    "delta": result["applied_delta"],
                }
            )
            yield schemas.stage_event(
                persona.name,
                result["stage"],
                result["previous_stage"] if result["stage_changed"] else None,
            )
        except Exception as exc:  # noqa: BLE001 - 结算失败不影响已输出的台词
            logger.warning("关系结算失败：%s", exc)
            settlement["stage"] = stage
    settlement["forgotten"] = (forget_result or {}).get("count", 0)

    # 10. 候选记忆：主角私有，本轮先记，下一轮统一压缩
    if persona.has_private_memory:
        try:
            for candidate in collect_candidates(user_text):
                repository.add_candidate(
                    user_id,
                    persona.name,
                    candidate["content"],
                    category=str(candidate.get("category") or ""),
                    priority=int(candidate.get("priority") or 1),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("候选记忆写入失败：%s", exc)

    yield schemas.round_end(settlement=settlement)


# 这里是本轮最重要的一句话，放在提示词最前面——放在人设之后会被压过去
GREETING_KINDS: dict[str, str] = {
    # 进院：来客自己走进来的，屋里的人原本就在这屋里，不必自称刚到
    "room": "【此刻的情形】来客自己走进了你正待着的这间屋子，你原本就在这里。"
            "说一两句招呼即可，可以就着房里方才的话头说。"
            "不要交代自己的来历（你本来就在），也不要说你刚到。",
    # 被请入席：说话的人原本不在这屋里，是被请来的
    "entry": "【此刻的情形】来客刚把你请进这间屋子，你原本并不在这里。"
             "第一句必须交代你方才在哪里、在做什么（例如正在做什么活计、从哪一处过来），"
             "再向在场的人打个招呼。不要说你本来就在这儿，也不要一开口就问来客坐没坐。",
    # 离席：说话的人马上就走
    "leave": "【此刻的情形】你正要离席，说完这句就走。"
             "只说一句或两句：说清你为什么这时候走、往哪里去，可以带一句对刚才话头的回应。"
             "不要邀请任何人做任何事，不要留客，不要提议一同做什么，"
             "不要说“来”“咱们”“别拘束”这类招呼话——那是迎客，不是告辞。",
}


def greeting_events(
    user_id: str,
    present: list[str],
    scene: str | None = None,
    api_key: str | None = None,
    speaker: str | None = None,
    kind: str = "entry",
) -> Iterator[dict[str, Any]]:
    """入席或离席时的一句话。

    说话人优先取显式传入的 speaker——请离时那个人已经不在名单里了，
    只按 present[0] 找的话会由别人替他开口。
    """
    persona = (
        get_persona(speaker or "")
        or get_persona(present[0] if present else "")
        or get_persona(DEFAULT_CHARACTER)
    )
    if persona is None:
        yield schemas.error_event("没有找到可用的角色配置。")
        yield schemas.round_end()
        return

    provider, provider_notice = _provider_or_notice(api_key)
    if provider_notice:
        yield schemas.error_event(provider_notice)
        if provider is None:
            yield schemas.round_end()
            return

    uid = (user_id or settings.default_user_id).strip() or settings.default_user_id
    try:
        repository.ensure_user(uid)
        user = repository.ensure_user(uid)
        profile = repository.get_profile_facts(uid)
        room = _room_snapshot(uid, scene)
        memory_lines = build_memory_lines(uid, persona.name) if persona.has_private_memory else []
        stage = repository.get_affection(uid, persona.name)["stage"] if persona.has_relationship else ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("问候状态装配失败")
        yield schemas.error_event("记忆与关系暂不可用，请稍后再试。", str(exc))
        yield schemas.round_end()
        return

    present_names = _present_names(present, persona)
    try:
        state_lines = repository.state_lines(uid, persona.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("人物状态读取失败：%s", exc)
        state_lines = []
    story_lines = _room_story(uid, persona, present_names, scene, user, entry=True)

    context = DialogueContext(
        speaker=persona.name,
        present=present_names,
        game_time=_game_time(user),
        profile=profile,
        memory=memory_lines,
        room=room,
        evidence=[],
        user_text="",
        stage=stage,
        state=state_lines,
        story=story_lines,
        notes=[GREETING_KINDS.get(kind, GREETING_KINDS["entry"])],
    )

    try:
        sentences = generate_greeting(provider, persona, context)
    except Exception as exc:  # noqa: BLE001
        logger.exception("问候生成失败")
        yield schemas.error_event("一时未能开口，请稍后再试。", str(exc))
        yield schemas.round_end()
        return

    if not sentences:
        yield schemas.error_event("一时未能开口，请稍后再试。")
        yield schemas.round_end()
        return

    guard_facts = address_facts(profile)
    emitted: list[dict[str, Any]] = []
    yield schemas.speaker_start(persona.name)
    for item in sentences:
        item["text"] = sanitize_address(item["text"], guard_facts)
        if not item["text"].strip():
            continue
        emitted.append(item)
        yield schemas.sentence(
            speaker=persona.name,
            text=item["text"],
            emotion=item["emotion"],
            action=item["action"],
            intensity=item["intensity"],
            kind=item["kind"],
        )
    if not emitted:
        yield schemas.speaker_end(persona.name)
        yield schemas.round_end()
        return
    yield schemas.speaker_end(persona.name)

    if persona.has_relationship:
        yield schemas.stage_event(persona.name, stage)

    try:
        repository.append_chat(
            uid,
            "greeting",
            persona.name,
            "".join(item["text"] for item in emitted),
            emotion=emitted[0]["emotion"],
            action=emitted[0]["action"],
            kind=emitted[0]["kind"],
            self_turn=False,
            scene=scene or "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("问候记录失败：%s", exc)

    yield schemas.round_end(settlement={"speaker": persona.name, "stage": stage, "greeting": True})


def dialogue_stream(request: schemas.DialogueRequest, api_key: str | None = None):
    try:
        for event in dialogue_events(request, api_key):
            yield encode(event)
    except Exception as exc:  # noqa: BLE001 - 兜底：保证 NDJSON 流以异常卡收尾
        logger.exception("对话流异常终止")
        yield encode(schemas.error_event("对话流意外中断。", str(exc)))
        yield encode(schemas.round_end())


def greeting_stream(
    user_id: str,
    present: list[str],
    scene: str | None = None,
    api_key: str | None = None,
    speaker: str | None = None,
    kind: str = "entry",
):
    try:
        for event in greeting_events(user_id, present, scene, api_key, speaker, kind):
            yield encode(event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("问候流异常终止")
        yield encode(schemas.error_event("问候流意外中断。", str(exc)))
        yield encode(schemas.round_end())


def state_of(user_id: str, character: str = DEFAULT_CHARACTER) -> dict[str, Any]:
    """前端只读取关系阶段与游戏内时间；配角没有关系阶段，只回报在场所需的信息。"""
    uid = (user_id or settings.default_user_id).strip() or settings.default_user_id
    persona = get_persona(character)
    model = settings.ollama_model if settings.llm_provider != "deepseek" else settings.deepseek_model
    has_relationship = bool(persona and persona.has_relationship)
    try:
        repository.ensure_user(uid)
        user = repository.ensure_user(uid)
        stage = repository.get_affection(uid, character)["stage"] if has_relationship else ""
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "detail": str(exc),
            "character": character,
            "role": persona.role if persona else "supporting",
            "has_relationship": has_relationship,
            "stage": "",
            "stages": list(STAGES) if has_relationship else [],
            "game_day": 1,
            "game_period": "清晨",
            "provider": settings.llm_provider,
            "model": model,
        }
    return {
        "available": True,
        "character": character,
        "role": persona.role if persona else "supporting",
        "has_relationship": has_relationship,
        "stage": stage,
        "stages": list(STAGES) if has_relationship else [],
        "game_day": int(user.get("game_day") or 1),
        "game_period": user.get("game_period") or "清晨",
        "provider": settings.llm_provider,
        "model": model,
    }
