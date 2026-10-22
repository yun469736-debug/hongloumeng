# -*- coding: utf-8 -*-
"""隐藏好感度与七阶段关系规则。

模型只给出语义判断与事件类型，数值钳制、阶段门槛、滞回缓冲与慢热条件都在这里执行：
前端只看到关系阶段，看不到数值。
"""

from __future__ import annotations

import logging
from typing import Any

from agent.db import repository

logger = logging.getLogger(__name__)

STAGES = ["初识", "留意", "相熟", "信赖", "知己", "情动", "相守"]

# 阶段门槛（好感度 0～100）
THRESHOLDS: dict[str, float] = {
    "初识": 0.0,
    "留意": 12.0,
    "相熟": 26.0,
    "信赖": 42.0,
    "知己": 58.0,
    "情动": 78.0,
    "相守": 93.0,
}

# 滞回缓冲：普通摩擦不会立即降级，需跌破「门槛 - 缓冲」才回落
HYSTERESIS = 4.0

# 单轮变化上限（程序限制，模型不得越权）
MAX_GAIN = 2.5
MAX_LOSS = 2.5

# 慢热门槛：轮数不能替代关键条件
STAGE_GATES: dict[str, int] = {"情动": 40, "相守": 80}

# 按事件类型限制单轮权重；重复恭维与机械迎合不计入关系进展
EVENT_CAPS: dict[str, tuple[float, float]] = {
    "有意义互动": (0.0, 2.0),
    "关怀善意": (0.0, MAX_GAIN),
    "如约而至": (0.0, MAX_GAIN),
    "普通闲聊": (-0.5, 0.3),
    "重复恭维": (-0.5, 0.0),
    "敷衍刷单": (-1.0, 0.0),
    "轻度冒犯": (-2.0, 0.0),
    "重大背弃": (-MAX_LOSS, -1.0),
    "其他": (-0.5, 0.5),
}

MEANINGFUL_EVENTS = {"有意义互动", "关怀善意", "如约而至"}
IMMEDIATE_DOWNGRADE_EVENTS = {"重大背弃"}


def clamp_delta(delta: float, event_type: str) -> float:
    low, high = EVENT_CAPS.get(event_type, EVENT_CAPS["其他"])
    bounded = max(-MAX_LOSS, min(MAX_GAIN, float(delta)))
    return round(max(low, min(high, bounded)), 2)


def _gate_met(stage: str, meaningful_count: int) -> bool:
    required = STAGE_GATES.get(stage)
    return True if required is None else meaningful_count >= required


def compute_stage(
    affection: float,
    current_stage: str,
    meaningful_count: int,
    force_downgrade: bool = False,
) -> str:
    index = STAGES.index(current_stage) if current_stage in STAGES else 0

    while index + 1 < len(STAGES):
        nxt = STAGES[index + 1]
        if affection >= THRESHOLDS[nxt] and _gate_met(nxt, meaningful_count):
            index += 1
        else:
            break

    while index > 0:
        current = STAGES[index]
        if affection < THRESHOLDS[current] - HYSTERESIS or force_downgrade:
            index -= 1
            force_downgrade = False
        else:
            break

    return STAGES[index]


def apply_assessment(
    user_id: str,
    character_id: str,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """把模型评估落成一次关系结算，并持久化。"""
    state = repository.get_affection(user_id, character_id)
    affection = state["affection"]
    stage = state["stage"]
    meaningful_count = state["meaningful_count"]

    event_type = str(assessment.get("event_type") or "其他").strip()
    if event_type not in EVENT_CAPS:
        event_type = "其他"
    reason = str(assessment.get("reason") or "").strip()

    applied = clamp_delta(float(assessment.get("delta") or 0.0), event_type)
    affection = max(0.0, min(100.0, affection + applied))
    if event_type in MEANINGFUL_EVENTS:
        meaningful_count += 1

    next_stage = compute_stage(
        affection,
        stage,
        meaningful_count,
        force_downgrade=event_type in IMMEDIATE_DOWNGRADE_EVENTS,
    )

    repository.upsert_affection(user_id, character_id, affection, next_stage, meaningful_count)
    repository.record_event(user_id, character_id, event_type, reason)

    return {
        "affection": round(affection, 2),
        "stage": next_stage,
        "previous_stage": stage,
        "stage_changed": next_stage != stage,
        "applied_delta": applied,
        "event_type": event_type,
        "reason": reason,
        "meaningful_count": meaningful_count,
    }
