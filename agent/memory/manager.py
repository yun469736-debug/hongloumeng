# -*- coding: utf-8 -*-
"""记忆与公开档案的抽取。

分工（对应已确认的设计）：
- 公开档案 hlm_user_profile：来客自报的身份事实（姓名、姓氏、称呼、性别、身份、所在地、生日），
  所有真实角色都能感知；
- 私有长期记忆：只有林黛玉有，存放偏好、厌恶、"请记住"的叮嘱等她自己的印象；
- 被定向遗忘的内容永久排除在她的提示词之外，旧聊天仍可回看。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent.db import repository

logger = logging.getLogger(__name__)

# 属于"公开档案"的类别：来客当众自报的身份事实
PROFILE_CATEGORIES = ("姓名", "姓氏", "称呼", "性别", "身份", "所在地", "生日")
# 属于主角私有记忆的类别：她对来客的印象与叮嘱
PRIVATE_CATEGORIES = ("偏好", "厌恶", "叮嘱")

FACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!你)我(?:叫|名字叫|名字是)([^\s，。！？、,]{1,12})"), "姓名"),
    (re.compile(r"我姓([\u4e00-\u9fa5]{1,2})"), "姓氏"),
    (re.compile(r"叫我([^\s，。！？、,]{1,12})"), "称呼"),
    (re.compile(r"(?:你可以|你就)叫我([^\s，。！？、,]{1,12})"), "称呼"),
    (re.compile(r"我(?:是|乃)(?:一?[个位])?(男|女)(?:生|人|的|孩子)?"), "性别"),
    (re.compile(r"我的性别是(男|女)"), "性别"),
    (re.compile(r"我的生日(?:是|在)?([^\s。！？、,]{1,16})"), "生日"),
    (re.compile(r"我(?:喜欢|爱听|爱吃|爱看|最爱)([^\s。！？、,]{1,20})"), "偏好"),
    (re.compile(r"我(?:讨厌|不喜欢|不爱)([^\s。！？、,]{1,20})"), "厌恶"),
    (re.compile(r"我(?:住在|家在|在)([^\s，。！？、,]{1,20})"), "所在地"),
    (re.compile(r"我(?:是|做)([^\s，。！？、,]{1,20})"), "身份"),
)

# 用户主动要求记住：提升为高优先级候选记忆（主角私有）
REMEMBER_PATTERNS = (
    re.compile(r"(?:请|帮我|要|你)?记(?:住|得|下)[：:，,]?\s*(.+)"),
    re.compile(r"别忘了[：:，,]?\s*(.+)"),
)

FORGET_PATTERNS = (
    re.compile(r"忘(?:记|掉|了)(?:关于|有关)?[：:，,]?\s*(.+)"),
    re.compile(r"别再提(?:起)?[：:，,]?\s*(.+)"),
    re.compile(r"不要再提(?:起)?[：:，,]?\s*(.+)"),
)

TRAILING = "。！？，,、.~～ 吧了呢啊哦"

# 自报姓名/称呼时常带的口语尾巴，必须剥掉，否则会污染称呼守卫
GENDER_WORDS = {"男生", "女生", "男的", "女的", "男人", "女人", "男", "女"}

NAME_FILLERS = (
    "就好啦", "就好了", "就行了", "就成", "就好", "好了", "就行",
    "吧", "啦", "呀", "哦", "了", "呗", "嘛", "哈",
)


def _strip_name_filler(value: str) -> str:
    text = (value or "").strip()
    changed = True
    while changed and len(text) > 1:
        changed = False
        for filler in NAME_FILLERS:
            if text.endswith(filler) and len(text) > len(filler):
                text = text[: -len(filler)].strip()
                changed = True
    return text


def _clean(text: str) -> str:
    return (text or "").strip().strip(TRAILING).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def extract_facts(text: str) -> dict[str, str]:
    """从这句话里取出所有自报事实，按类别归并（同类取最先出现的）。"""
    facts: dict[str, str] = {}
    for pattern, category in FACT_PATTERNS:
        if category in facts:
            continue
        match = pattern.search(text or "")
        if not match:
            continue
        value = _clean(match.group(1))
        if category in ("姓名", "称呼"):
            value = _strip_name_filler(value)
        if category == "身份" and value in GENDER_WORDS:
            continue  # "我是女生" 已被性别捕获，不必再记一遍身份
        if value:
            facts[category] = value
    return facts


def profile_from_text(text: str) -> dict[str, str]:
    """只取"公开身份事实"那一部分，可直接写入 hlm_user_profile。"""
    facts = extract_facts(text)
    return {key: value for key, value in facts.items() if key in PROFILE_CATEGORIES}


def address_facts(profile: dict[str, str]) -> dict[str, str]:
    """把公开档案转成称呼守卫需要的字段名。"""
    return {
        "surname": (profile.get("姓氏") or "").strip(),
        "name": (profile.get("姓名") or "").strip(),
        "preferred": (profile.get("称呼") or "").strip(),
    }


def collect_candidates(user_text: str) -> list[dict[str, Any]]:
    """主角私有的候选记忆：她对来客的印象与叮嘱。每轮先记，下一轮统一压缩。"""
    text = (user_text or "").strip()
    if not text:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern in REMEMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            content = _clean(match.group(1))
            if content and content not in seen:
                seen.add(content)
                candidates.append({"content": content, "category": "叮嘱", "priority": 3})
            break

    facts = extract_facts(text)
    for category, value in facts.items():
        if category not in PRIVATE_CATEGORIES:
            continue
        label = f"{category}：{value}"
        if label in seen:
            continue
        seen.add(label)
        candidates.append({"content": label, "category": category, "priority": 2})

    return candidates


def compress_candidates(user_id: str, character_id: str) -> dict[str, int]:
    """统一压缩、去重并写入长期记忆。"""
    candidates = repository.list_candidates(user_id, character_id)
    if not candidates:
        return {"moved": 0, "skipped": 0}

    existing = [
        _normalize(row["content"])
        for row in repository.list_long_memory(user_id, character_id, limit=200, include_forgotten=True)
    ]
    moved = 0
    skipped = 0
    consumed: list[int] = []

    for candidate in candidates:
        content = (candidate.get("content") or "").strip()
        if not content:
            consumed.append(int(candidate["id"]))
            continue
        key = _normalize(content)
        duplicate = any(key == item or key in item or item in key for item in existing if item)
        if duplicate:
            skipped += 1
        else:
            repository.add_long_memory(
                user_id,
                character_id,
                content,
                category=str(candidate.get("category") or ""),
                priority=int(candidate.get("priority") or 1),
            )
            existing.append(key)
            moved += 1
        consumed.append(int(candidate["id"]))

    repository.clear_candidates(user_id, character_id, consumed)
    return {"moved": moved, "skipped": skipped}


def build_memory_lines(user_id: str, character_id: str) -> list[str]:
    lines: list[str] = []
    for row in repository.list_long_memory(user_id, character_id):
        category = (row.get("category") or "").strip()
        content = (row.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{category}] {content}" if category else content)
    return lines


def detect_forget_request(text: str) -> str | None:
    """识别"请你忘记……"这类定向遗忘请求。"""
    if not text or ("忘" not in text and "别再提" not in text and "不要再提" not in text):
        return None
    for pattern in FORGET_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = _clean(match.group(1))
            if len(topic) >= 1:
                return topic
    return None


def forget_topic(user_id: str, character_id: str, topic: str) -> dict[str, Any]:
    """定向遗忘：命中内容永久排除在检索、摘要与关系判断之外。"""
    key = _normalize(topic)
    if not key:
        return {"count": 0, "contents": []}
    hits = [
        row
        for row in repository.list_long_memory(user_id, character_id, limit=500)
        if key in _normalize(row.get("content") or "") or _normalize(row.get("content") or "") in key
    ]
    count = repository.mark_forgotten(user_id, [int(row["id"]) for row in hits])
    return {"count": count, "contents": [str(row.get("content") or "") for row in hits]}
