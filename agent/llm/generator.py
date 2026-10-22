# -*- coding: utf-8 -*-
"""提示词装配、逐句解析与输出校验。

模型只负责产出 JSON；结构与词表由 Ollama 结构化输出约束，解析侧再做一层容错，
保证进入 NDJSON 的每一句都能在前端命中已登记立绘状态，且绝不把 JSON 残片当作台词。

提示词结构刻意把「静态人格段」放在最前、「本轮处境段」放在最后：
同一会话中静态前缀逐字节一致，Ollama 可复用 KV 缓存，首句等待因此显著缩短。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from agent.llm.providers import LLMError, LLMProvider
from agent.persona.base import Persona
from agent.rag.retriever import Evidence

logger = logging.getLogger(__name__)

ALLOWED_KINDS = ("原著事实", "性格推演", "书外知识")
SENTENCE_SPLIT = re.compile(r"[^。！？；\n]*[。！？；\n]|[^。！？；\n]+")
TEXT_FIELD = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
JSON_HINT = re.compile(r'^[\s\[{]|"sentences"\s*:|^\s*"[a-z_]+"\s*:')
# JSON 结构残片：中文台词里绝不会出现这些组合，一旦出现必是解析漏网的语法碎片
JSON_ARTIFACT = re.compile(r'[\[\]{}]|"\s*:')
CJK = re.compile(r"[\u4e00-\u9fff]")

REPLY_MAX_TOKENS = 420
GREETING_MAX_TOKENS = 260

# 来客未自报性别前，姓名后不得挂这些称谓
HONORIFICS = (
    "公子", "先生", "姑娘", "小姐", "郎君", "夫人", "少爷", "老爷",
    "太太", "大爷", "奶奶", "姐姐", "妹妹", "哥哥", "弟弟", "兄台",
)


@dataclass
class DialogueContext:
    """装配提示词所需的全部处境信息。"""

    speaker: str = ""
    present: list[str] = field(default_factory=list)
    game_time: str = "第一日·清晨"
    profile: dict[str, str] = field(default_factory=dict)
    memory: list[str] = field(default_factory=list)
    room: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    user_text: str = ""
    crisis: bool = False
    notes: list[str] = field(default_factory=list)
    stage: str = "初识"
    # 十二位人物共享的人物状态（心绪/态度取向/心事），不向界面暴露
    state: list[str] = field(default_factory=list)
    # 本房的房间小关目：首次是"正在经历"，之后是"追忆"
    story: list[str] = field(default_factory=list)


def _present_line(persona: Persona, present: Sequence[str]) -> str:
    names = [name for name in present if name and name != "我"]
    others = [name for name in names if name != persona.name]
    if not others:
        return "只有你与来客"
    return "你、来客，以及" + "、".join(others)


def _profile_block(profile: dict[str, str]) -> str:
    if not profile:
        return "（来客尚未自报，不必追问，也不要猜测）"
    lines = [f"- {key}：{value}" for key, value in profile.items() if value]
    return "\n".join(lines) if lines else "（来客尚未自报，不必追问，也不要猜测）"


def _memory_block(memory: Sequence[str]) -> str:
    if not memory:
        return "（暂无）"
    return "\n".join(f"- {item}" for item in memory)


def _room_block(room: Sequence[dict[str, Any]], speaker: str) -> str:
    """房里最近说过的话，带说话人姓名。

    分三层标注，免得同一轮里几个人说出同一句话：
    - 自己这一轮之前说过的话 →「你方才说的」；
    - 来客发问之后、别人在本轮已经说过的话 →「本轮」，要接住而不是复述；
    - 其余是更早的旧话。
    """
    if not room:
        return "（房里还没有别的话）"
    # 最后一条来客发言之后的，都是本轮的应答
    last_self = -1
    for index, item in enumerate(room):
        if item.get("self"):
            last_self = index

    lines: list[str] = []
    for index, item in enumerate(room):
        who = "来客" if item.get("self") else str(item.get("speaker") or "某人")
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if item.get("self"):
            lines.append(f"{who}：{text}")
        elif who == speaker:
            lines.append(f"{who}（你方才说的）：{text}")
        elif index > last_self >= 0:
            lines.append(f"{who}（本轮已说）：{text}")
        else:
            lines.append(f"{who}：{text}")
    return "\n".join(lines) if lines else "（房里还没有别的话）"


def _bullet_block(lines: Sequence[str], empty: str) -> str:
    return "\n".join(f"- {item}" for item in lines) if lines else empty


def _evidence_block(evidence: Sequence[Evidence]) -> str:
    if not evidence:
        return "（本轮未检索，或无可用的原著片段。不得编造原著事实。）"
    return "\n\n".join(item.to_prompt_line() for item in evidence)


def _fill(template: str, persona: Persona, context: DialogueContext) -> str:
    return (
        template.replace("<<NAME>>", persona.name)
        .replace("<<COURTESY>>", persona.courtesy)
        .replace("<<STAGE>>", context.stage)
        .replace("<<PRESENT>>", _present_line(persona, context.present))
        .replace("<<GAME_TIME>>", context.game_time)
        .replace("<<NOTES>>", "；".join(context.notes) if context.notes else "（无）")
        .replace("<<STATE>>", _bullet_block(context.state, "（你此刻心境如常，与方才无异）"))
        .replace("<<STORY>>", _bullet_block(context.story, "（这间屋子里此刻没有别的动静）"))
        .replace("<<PROFILE>>", _profile_block(context.profile))
        .replace("<<MEMORY>>", _memory_block(context.memory))
        .replace("<<ROOM>>", _room_block(context.room, persona.name))
        .replace("<<EVIDENCE>>", _evidence_block(context.evidence))
        .replace("<<VOCABULARY>>", persona.vocabulary_lines())
    )


def build_dialogue_messages(persona: Persona, context: DialogueContext) -> list[dict]:
    """房间记录统一放进系统提示，用户当前这句才是 user 轮次。"""
    return [
        {"role": "system", "content": _fill(persona.system_prompt, persona, context)},
        {"role": "user", "content": context.user_text},
    ]


def build_greeting_messages(persona: Persona, context: DialogueContext) -> list[dict]:
    template = persona.greeting_prompt or persona.system_prompt
    return [
        {"role": "system", "content": _fill(template, persona, context)},
        {"role": "user", "content": "（来客入席了，请开口。）"},
    ]


# ---------------------------------------------------------------- 解析

def extract_json(raw: str) -> Any:
    """从模型输出中尽力取出 JSON，容忍代码块与前后杂字。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^\s*```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start == -1 or end <= start:
            continue
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue
    return None


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in SENTENCE_SPLIT.findall(text or "")]
    return [part for part in parts if part]


def _clamp_intensity(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _normalize_kind(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in ALLOWED_KINDS else "性格推演"


def _looks_like_json(text: str) -> bool:
    """判断一段文本是否为 JSON 语法碎片而非台词。"""
    stripped = (text or "").strip()
    if not stripped:
        return True
    if stripped in {"{", "}", "[", "]", ",", ":", "\"", "\u201D", "\u201C"}:
        return True
    if JSON_ARTIFACT.search(stripped):
        return True
    if not CJK.search(stripped):
        # 台词一律是中文；没有汉字的多半是结构残片或键名
        return True
    return bool(JSON_HINT.match(stripped)) and ('"' in stripped or "{" in stripped or "[" in stripped)


def _salvage_from_json_text(raw: str) -> list[str]:
    """JSON 残缺时，只从 text 字段里抢救真正的台词，绝不把结构残片当台词。"""
    texts: list[str] = []
    for match in TEXT_FIELD.finditer(raw or ""):
        try:
            value = json.loads('"' + match.group(1) + '"')
        except json.JSONDecodeError:
            value = match.group(1)
        value = (value or "").strip()
        if value and not _looks_like_json(value):
            texts.append(value)
    return texts


def _collect_items(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        candidate = payload.get("sentences")
        if isinstance(candidate, list):
            return candidate
        if payload.get("text"):
            return [payload]
        return []
    if isinstance(payload, list):
        return payload
    return []


def _build(text: str, emotion: Any, action: Any, intensity: Any, kind: Any, persona: Persona) -> list[dict[str, Any]]:
    normalized_emotion = persona.normalize_emotion(str(emotion or ""))
    normalized_action = persona.normalize_action(str(action or ""))
    normalized_kind = _normalize_kind(kind)
    base_intensity = _clamp_intensity(intensity, persona.default_intensity)

    pieces = split_sentences(text) or [text.strip()]
    built: list[dict[str, Any]] = []
    for index, piece in enumerate(pieces):
        if _looks_like_json(piece) or len(piece) < 1:
            continue
        built.append(
            {
                "text": piece,
                "emotion": normalized_emotion,
                "action": normalized_action,
                "intensity": round(max(0.05, base_intensity - index * 0.05), 3),
                "kind": normalized_kind,
            }
        )
    return built


def parse_sentences(raw: str, persona: Persona) -> list[dict[str, Any]]:
    """把模型输出解析为规范化句子列表。

    优先走 JSON；JSON 残缺时只抢救 text 字段；确无 JSON 痕迹时才按标点分句。
    """
    payload = extract_json(raw)
    sentences: list[dict[str, Any]] = []

    for item in _collect_items(payload):
        if isinstance(item, str):
            sentences.extend(_build(item, "", "", None, "", persona))
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        sentences.extend(
            _build(
                text,
                item.get("emotion"),
                item.get("action"),
                item.get("intensity"),
                item.get("kind"),
                persona,
            )
        )
        if len(sentences) >= 6:
            break

    if sentences:
        return sentences[:6]

    salvaged = _salvage_from_json_text(raw)
    for text in salvaged:
        sentences.extend(_build(text, "", "", None, "", persona))
    if sentences:
        logger.warning("模型 JSON 不完整，已从 text 字段抢救出 %d 句。", len(sentences))
        return sentences[:6]

    if payload is not None or JSON_HINT.match((raw or "").strip() or " "):
        logger.error("模型输出疑似 JSON 但无法取得台词，放弃本轮而非伪造台词。")
        return []

    logger.warning("模型输出非 JSON，按标点降级分句。")
    for piece in split_sentences(raw):
        sentences.extend(_build(piece, "", "", None, "", persona))
    return sentences[:6]


# ---------------------------------------------------------------- 称呼守卫

def sanitize_address(text: str, facts: dict[str, str] | None = None) -> str:
    """称呼守卫：把"陈公子"这类姓氏加称谓的臆测改回"你"或来客自报的名字。

    角色无从知道来客是男是女、是老是少，spec §5.1 要求系统不自行猜测；
    4B 模型难以稳定遵守，因此在此以程序兜底。只替换"来客自报的姓氏/姓名 + 称谓"，
    不会误伤"宝姐姐""林妹妹"这类原著中的称呼。
    """
    if not text:
        return text
    facts = facts or {}
    replacements = [value for value in (facts.get("preferred"), facts.get("name")) if value]
    fallback = replacements[0] if replacements else "你"

    surname = (facts.get("surname") or "").strip()
    parts = [value for value in (surname, facts.get("name"), facts.get("preferred")) if value]
    if not parts:
        return text
    # 姓氏、名字，以及"姓氏＋名字"的组合（模型常写成"陈阿沅先生"）
    prefixes = list(parts)
    if surname:
        for other in (facts.get("name"), facts.get("preferred")):
            other = (other or "").strip()
            if other:
                prefixes.append(surname + other)
    prefixes = sorted(set(prefixes), key=len, reverse=True)

    pattern = re.compile("(" + "|".join(re.escape(item) for item in prefixes) + ")(" + "|".join(HONORIFICS) + ")")
    return pattern.sub(lambda _: fallback, text)


# ---------------------------------------------------------------- 流式生成

def extract_stream_objects(buffer: str, emitted_upto: int = 0) -> tuple[list[str], int]:
    """从流式 JSON 文本里截出"第 2 层"的完整对象。

    生成的结构是 {"sentences":[{...},{...}]}（主角另带 affection）：
    第 2 层对象就是每句台词与末尾的关系暗记。凑齐一个即可立刻下发，
    不必等整段 JSON 收尾，首句因此能明显提前。

    每次整体重扫（回复很短，代价可忽略），用 emitted_upto 保证不重复下发。
    """
    objects: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    start = -1
    index = 0
    length = len(buffer)

    while index < length:
        char = buffer[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "{":
            depth += 1
            if depth == 2:
                start = index
            index += 1
            continue
        if char == "}":
            if depth == 2 and start >= 0:
                if index + 1 > emitted_upto:
                    objects.append(buffer[start : index + 1])
                    emitted_upto = index + 1
                start = -1
            depth = max(0, depth - 1)
            index += 1
            continue
        index += 1

    return objects, emitted_upto


def _normalize_affection_block(block: Any) -> dict[str, Any]:
    from agent.persona.base import AFFECTION_EVENT_TYPES

    if not isinstance(block, dict):
        return {"delta": 0.0, "event_type": "其他", "reason": "未记录"}
    try:
        delta = float(block.get("delta", 0.0))
    except (TypeError, ValueError):
        delta = 0.0
    event_type = str(block.get("event_type") or "其他").strip()
    return {
        "delta": delta,
        "event_type": event_type if event_type in AFFECTION_EVENT_TYPES else "其他",
        "reason": str(block.get("reason") or "").strip(),
    }


def parse_affection(payload: Any) -> dict[str, Any]:
    """取出同一轮生成里的关系暗记；缺失时给出中性兜底。"""
    if not isinstance(payload, dict):
        return {"delta": 0.0, "event_type": "其他", "reason": "未记录"}
    return _normalize_affection_block(payload.get("affection"))


def generate_reply_stream(
    provider: LLMProvider,
    persona: Persona,
    context: DialogueContext,
) -> Iterator[tuple[str, Any]]:
    """流式生成：每凑齐一句就立刻交出 ("sentence", 句子)；主角最后另交 ("affection", 暗记)。

    逐句下发让前端在模型仍在续写时就能开始转场与打字，显著缩短首句等待。
    """
    messages = build_dialogue_messages(persona, context)
    schema = persona.reply_schema()
    wants_affection = persona.has_relationship

    buffer = ""
    cursor = 0
    emitted = 0
    affection: dict[str, Any] | None = None

    try:
        for chunk in provider.stream(messages, json_mode=True, max_tokens=REPLY_MAX_TOKENS, schema=schema):
            buffer += chunk
            objects, cursor = extract_stream_objects(buffer, cursor)
            if not objects:
                continue
            for raw_object in objects:
                try:
                    parsed = json.loads(raw_object)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                if parsed.get("text"):
                    built = _build(
                        str(parsed.get("text") or ""),
                        parsed.get("emotion"),
                        parsed.get("action"),
                        parsed.get("intensity"),
                        parsed.get("kind"),
                        persona,
                    )
                    for item in built:
                        emitted += 1
                        yield ("sentence", item)
                elif wants_affection and ("delta" in parsed or "event_type" in parsed):
                    affection = _normalize_affection_block(parsed)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("流式生成中断，改用整体解析：%s", exc)

    if emitted == 0:
        for item in parse_sentences(buffer, persona):
            emitted += 1
            yield ("sentence", item)

    if wants_affection:
        if affection is None:
            affection = parse_affection(extract_json(buffer))
        yield ("affection", affection)


def generate_reply(
    provider: LLMProvider,
    persona: Persona,
    context: DialogueContext,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """非流式版本：一次调用同时得到台词与关系暗记（供测试与降级路径使用）。"""
    messages = build_dialogue_messages(persona, context)
    raw = provider.complete(messages, json_mode=True, max_tokens=REPLY_MAX_TOKENS, schema=persona.reply_schema())
    return parse_sentences(raw, persona), parse_affection(extract_json(raw))


def generate_greeting(
    provider: LLMProvider,
    persona: Persona,
    context: DialogueContext,
) -> list[dict[str, Any]]:
    messages = build_greeting_messages(persona, context)
    raw = provider.complete(messages, json_mode=True, max_tokens=GREETING_MAX_TOKENS, schema=persona.reply_schema())
    return parse_sentences(raw, persona)
