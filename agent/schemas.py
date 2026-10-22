# -*- coding: utf-8 -*-
"""请求模型与事件构造。事件字典直接序列化为 NDJSON 单行。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DialogueRequest(BaseModel):
    """前端一次发言携带的房间上下文。speaker 显式声明本轮由谁应答。"""

    user_id: str = "local_default"
    text: str
    speaker: str | None = None
    present_characters: list[str] = Field(default_factory=lambda: ["林黛玉"])
    scene: str | None = None
    # 只在 /api/greeting 上有意义：entry 入席、leave 离席
    greeting_kind: str | None = None
    # 本轮里的第几个开口（0 起）。大于 0 时看不到同轮前面人的答复，
    # 否则 4B 模型会直接把前一位的answer 换个字复述一遍。
    round_index: int = 0


class ResetRequest(BaseModel):
    user_id: str = "local_default"
    confirm: bool = False


class DreamEnterRequest(BaseModel):
    """入梦：挑一章进去，或接着上次的进度。"""

    user_id: str = "local_default"
    chapter_key: str
    cast: list[str] = Field(default_factory=list)
    restart: bool = False


class DreamChooseRequest(BaseModel):
    user_id: str = "local_default"
    chapter_key: str
    node_key: str
    option_key: str


class DreamLeaveRequest(BaseModel):
    user_id: str = "local_default"
    chapter_key: str


def speaker_start(speaker: str) -> dict[str, Any]:
    return {"type": "speaker_start", "speaker": speaker}


def speaker_end(speaker: str) -> dict[str, Any]:
    return {"type": "speaker_end", "speaker": speaker}


def sentence(
    speaker: str,
    text: str,
    emotion: str,
    action: str,
    intensity: float,
    kind: str = "性格推演",
    confidence: float | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """一句话事件；stageDirection 由前端按立绘状态自行补全。"""
    event: dict[str, Any] = {
        "type": "sentence",
        "speaker": speaker,
        "emotion": emotion,
        "action": action,
        "intensity": round(float(intensity), 3),
        "stageDirection": "",
        "text": text,
        "kind": kind,
        "source": "agent",
    }
    if confidence is not None:
        event["confidence"] = round(float(confidence), 3)
    if evidence:
        event["evidence"] = evidence
    return event


def stage_event(speaker: str, stage: str, previous: str | None = None, affection: float | None = None) -> dict[str, Any]:
    """只给阶段，不给隐藏数值。配角不参与，因此也不会发出此事件。"""
    event: dict[str, Any] = {"type": "stage", "speaker": speaker, "stage": stage}
    if previous is not None:
        event["previous"] = previous
    if affection is not None:
        event["affection"] = round(float(affection), 2)
    return event


def error_event(message: str, detail: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "error", "message": message}
    if detail:
        event["detail"] = detail
    return event


def round_end(settlement: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "round_end"}
    if settlement:
        event["settlement"] = settlement
    return event
