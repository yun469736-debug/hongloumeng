# -*- coding: utf-8 -*-
"""数据访问层：会话记录、公开档案、记忆、好感度、人物状态与事件。

共享：hlm_users（用户与游戏时钟）、hlm_chat（房间公开记录）、hlm_user_profile（公开自报信息）、
      hlm_character_state（十二位人物的心绪/态度/心事，不向界面暴露）
主角专属：hlm_memory_long / hlm_memory_candidate / hlm_affection / hlm_events
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from agent.config import settings
from agent.db.connection import connection



# ---------------------------------------------------------------- 入梦择章

def dream_progress(user_id: str, chapter_key: str) -> dict[str, Any] | None:
    """某章的进度；没进过则返回 None。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT chapter_key, segment_index, status, settled, cast_json "
                "FROM hlm_dream_progress WHERE user_id = %s AND chapter_key = %s",
                (user_id, chapter_key),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return {
        "chapter_key": str(row["chapter_key"]),
        "segment_index": int(row["segment_index"] or 0),
        "status": str(row["status"] or "started"),
        "settled": bool(row["settled"]),
        "cast": [item for item in str(row["cast_json"] or "").split(",") if item],
    }


def dream_all_progress(user_id: str) -> dict[str, dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT chapter_key, segment_index, status, settled, cast_json "
                "FROM hlm_dream_progress WHERE user_id = %s",
                (user_id,),
            )
            rows = list(cursor.fetchall())
    return {
        str(row["chapter_key"]): {
            "segment_index": int(row["segment_index"] or 0),
            "status": str(row["status"] or "started"),
            "settled": bool(row["settled"]),
            "cast": [item for item in str(row["cast_json"] or "").split(",") if item],
        }
        for row in rows
    }


def dream_save_progress(
    user_id: str,
    chapter_key: str,
    *,
    segment_index: int | None = None,
    status: str | None = None,
    settled: bool | None = None,
    cast: list[str] | None = None,
) -> None:
    """只更新传入的字段；其余保持原样。"""
    current = dream_progress(user_id, chapter_key) or {
        "segment_index": 0, "status": "started", "settled": False, "cast": [],
    }
    next_index = current["segment_index"] if segment_index is None else int(segment_index)
    next_status = current["status"] if status is None else status
    next_settled = current["settled"] if settled is None else bool(settled)
    next_cast = current["cast"] if cast is None else list(cast)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_dream_progress "
                "(user_id, chapter_key, segment_index, status, settled, cast_json) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE segment_index = VALUES(segment_index), "
                "status = VALUES(status), settled = VALUES(settled), cast_json = VALUES(cast_json)",
                (
                    user_id, chapter_key, next_index, next_status,
                    1 if next_settled else 0, ",".join(next_cast),
                ),
            )


def dream_record_choice(user_id: str, chapter_key: str, node_key: str, option_key: str) -> None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_dream_choice (user_id, chapter_key, node_key, option_key) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, chapter_key, node_key, option_key),
            )


def dream_choices(user_id: str, chapter_key: str) -> dict[str, str]:
    """这一章做过的选择：节点 → 选项。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT node_key, option_key FROM hlm_dream_choice "
                "WHERE user_id = %s AND chapter_key = %s ORDER BY id",
                (user_id, chapter_key),
            )
            rows = list(cursor.fetchall())
    return {str(row["node_key"]): str(row["option_key"]) for row in rows}


def dream_forget(user_id: str, chapter_key: str) -> None:
    """把某一章退回未入梦状态（进度与选择都清掉，状态效果不回收）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM hlm_dream_progress WHERE user_id = %s AND chapter_key = %s",
                (user_id, chapter_key),
            )
            cursor.execute(
                "DELETE FROM hlm_dream_choice WHERE user_id = %s AND chapter_key = %s",
                (user_id, chapter_key),
            )


# ---------------------------------------------------------------- 用户

def ensure_user(user_id: str) -> dict[str, Any]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO hlm_users (user_id, game_day, game_period) VALUES (%s, 1, '清晨')",
                (user_id,),
            )
            cursor.execute(
                "SELECT user_id, game_day, game_period FROM hlm_users WHERE user_id = %s",
                (user_id,),
            )
            return cursor.fetchone() or {"user_id": user_id, "game_day": 1, "game_period": "清晨"}


def advance_period(user_id: str) -> dict[str, Any]:
    """一次有效会谈结束，推进一个时段；夜间之后进入次日清晨。

    跨过一日时要顺带做人物态度的每日回归——见 decay_attitudes。
    """
    order = ["清晨", "午后", "黄昏", "夜间"]
    user = ensure_user(user_id)
    current = user.get("game_period") or "清晨"
    day = int(user.get("game_day") or 1)
    index = order.index(current) if current in order else 0
    rolled_over = index + 1 >= len(order)
    if rolled_over:
        day += 1
        nxt = order[0]
    else:
        nxt = order[index + 1]
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE hlm_users SET game_day = %s, game_period = %s WHERE user_id = %s",
                (day, nxt, user_id),
            )
    decayed = decay_attitudes(user_id, day) if rolled_over else 0
    return {"user_id": user_id, "game_day": day, "game_period": nxt, "attitude_decayed": decayed}


def reset_user(user_id: str) -> None:
    """完整世界重置：删除该用户的全部关系、记忆、聊天、事件与游戏时钟。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            for table in (
                "hlm_chat",
                "hlm_user_profile",
                "hlm_character_state",
                "hlm_dream_progress",
                "hlm_dream_choice",
                "hlm_memory_long",
                "hlm_memory_candidate",
                "hlm_events",
                "hlm_affection",
                "hlm_users",
            ):
                cursor.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))


# ---------------------------------------------------------------- 公开档案（所有真实角色都可感知）

def upsert_profile_fact(user_id: str, fact_key: str, fact_value: str) -> None:
    value = (fact_value or "").strip()
    if not fact_key or not value:
        return
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_user_profile (user_id, fact_key, fact_value) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE fact_value = VALUES(fact_value)",
                (user_id, fact_key, value),
            )


def get_profile_facts(user_id: str) -> dict[str, str]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT fact_key, fact_value FROM hlm_user_profile WHERE user_id = %s",
                (user_id,),
            )
            return {str(row["fact_key"]): str(row["fact_value"]) for row in cursor.fetchall()}


# ---------------------------------------------------------------- 房间公开记录

def append_chat(
    user_id: str,
    session_id: str,
    speaker: str,
    text: str,
    emotion: str = "",
    action: str = "",
    kind: str = "",
    self_turn: bool = False,
    evidence_json: str | None = None,
    scene: str = "",
) -> int:
    """记一条公开发言。scene 标出它发生在哪间房——「房里最近说过的话」只认本房。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_chat "
                "(user_id, session_id, scene, speaker, text, emotion, action, kind, self_turn, evidence_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id, session_id, scene, speaker, text,
                    emotion, action, kind, 1 if self_turn else 0, evidence_json,
                ),
            )
            return int(cursor.lastrowid or 0)


def recent_chat(user_id: str, scene: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """最近若干条公开发言，含说话人姓名——用于组装「房间记录」。

    给了 scene 就只看那间房：换院子之后，上一间房说过的话不该再被当成「房里说过的话」。
    """
    size = limit or settings.short_term_turns
    with connection() as conn:
        with conn.cursor() as cursor:
            if scene:
                cursor.execute(
                    "SELECT id, speaker, text, emotion, action, kind, self_turn, created_at "
                    "FROM hlm_chat WHERE user_id = %s AND scene = %s ORDER BY id DESC LIMIT %s",
                    (user_id, scene, size),
                )
            else:
                cursor.execute(
                    "SELECT id, speaker, text, emotion, action, kind, self_turn, created_at "
                    "FROM hlm_chat WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                    (user_id, size),
                )
            rows = list(cursor.fetchall())
    rows.reverse()
    return rows


def full_history(user_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, speaker, text, emotion, action, kind, self_turn, created_at "
                "FROM hlm_chat WHERE user_id = %s ORDER BY id ASC LIMIT %s",
                (user_id, limit),
            )
            return list(cursor.fetchall())


# ---------------------------------------------------------------- 人物状态（十二位共享，不向界面暴露）

# 态度取 0～5，中点 2.5；每过一个游戏日向中点线性回归 0.5（满值/见底回到中点需整整五天）
ATTITUDE_MIN = 0.0
ATTITUDE_MAX = 5.0
ATTITUDE_MID = 2.5
ATTITUDE_STEP = 0.5

_STATE_COLS = "user_id, character_id, mood, attitude, secret, updated_day"


def _state_row(row: dict[str, Any] | None, user_id: str, character_id: str) -> dict[str, Any]:
    if not row:
        return {
            "user_id": user_id,
            "character_id": character_id,
            "mood": "",
            "attitude": ATTITUDE_MID,
            "secret": "",
            "updated_day": 1,
        }
    # 注意：attitude 可能是 Decimal('0.00')，它在 Python 里是 falsy，
    # 写成 row.get("attitude") or ATTITUDE_MID 会把"见底"静默读成中点。
    raw_attitude = row.get("attitude")
    return {
        "user_id": str(row["user_id"]),
        "character_id": str(row["character_id"]),
        "mood": str(row.get("mood") or ""),
        "attitude": ATTITUDE_MID if raw_attitude is None else float(raw_attitude),
        "secret": str(row.get("secret") or ""),
        "updated_day": int(row.get("updated_day") or 1),
    }


def ensure_character_state(user_id: str, character_id: str) -> dict[str, Any]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO hlm_character_state (user_id, character_id) VALUES (%s, %s)",
                (user_id, character_id),
            )
            cursor.execute(
                f"SELECT {_STATE_COLS} FROM hlm_character_state WHERE user_id = %s AND character_id = %s",
                (user_id, character_id),
            )
            return _state_row(cursor.fetchone(), user_id, character_id)


def all_character_states(user_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {_STATE_COLS} FROM hlm_character_state WHERE user_id = %s ORDER BY character_id",
                (user_id,),
            )
            return [_state_row(row, user_id, str(row.get("character_id") or "")) for row in cursor.fetchall()]


def set_character_state(
    user_id: str,
    character_id: str,
    *,
    mood: str | None = None,
    secret: str | None = None,
    attitude: float | None = None,
    game_day: int = 1,
) -> dict[str, Any]:
    """改动人物状态。只传要改的项，其余保持原样。"""
    current = ensure_character_state(user_id, character_id)
    next_mood = current["mood"] if mood is None else str(mood).strip()[:32]
    next_secret = current["secret"] if secret is None else str(secret).strip()[:255]
    if attitude is None:
        next_attitude = current["attitude"]
    else:
        next_attitude = max(ATTITUDE_MIN, min(ATTITUDE_MAX, float(attitude)))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE hlm_character_state SET mood = %s, secret = %s, attitude = %s, updated_day = %s "
                "WHERE user_id = %s AND character_id = %s",
                (next_mood, next_secret, next_attitude, int(game_day), user_id, character_id),
            )
    return {
        **current,
        "mood": next_mood,
        "secret": next_secret,
        "attitude": next_attitude,
        "updated_day": int(game_day),
    }


def adjust_attitude(user_id: str, character_id: str, delta: float, game_day: int = 1) -> dict[str, Any]:
    current = ensure_character_state(user_id, character_id)
    return set_character_state(
        user_id, character_id, attitude=current["attitude"] + float(delta), game_day=game_day
    )


def decay_attitudes(user_id: str, game_day: int) -> int:
    """每过一个游戏日，态度向中点 2.5 线性回归 0.5，不会越过中点。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE hlm_character_state SET attitude = CASE "
                "WHEN attitude > %s THEN GREATEST(%s, attitude - %s) "
                "WHEN attitude < %s THEN LEAST(%s, attitude + %s) "
                "ELSE attitude END, updated_day = %s WHERE user_id = %s",
                (
                    ATTITUDE_MID, ATTITUDE_MID, ATTITUDE_STEP,
                    ATTITUDE_MID, ATTITUDE_MID, ATTITUDE_STEP,
                    int(game_day), user_id,
                ),
            )
            return int(cursor.rowcount or 0)


def state_lines(user_id: str, character_id: str) -> list[str]:
    """渲染成提示词里的几行。数值本身不下发，只给取向。"""
    state = ensure_character_state(user_id, character_id)
    lines: list[str] = []
    if state["mood"]:
        lines.append("你此刻的心绪：" + state["mood"])
    if state["secret"]:
        lines.append("你近来搁在心上的一件事：" + state["secret"])
    attitude = state["attitude"]
    if attitude >= 3.6:
        lines.append("你对这位来客已存了几分看重。")
    elif attitude >= 2.9:
        lines.append("你对这位来客略有好感。")
    elif attitude <= 1.4:
        lines.append("你对这位来客颇为不以为然。")
    elif attitude <= 2.1:
        lines.append("你对这位来客略有保留。")
    return lines


# ---------------------------------------------------------------- 私有记忆（主角专属）

def add_candidate(user_id: str, character_id: str, content: str, category: str = "", priority: int = 1) -> int:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_memory_candidate (user_id, character_id, content, category, priority) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, character_id, content, category, priority),
            )
            return int(cursor.lastrowid or 0)


def list_candidates(user_id: str, character_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, content, category, priority FROM hlm_memory_candidate "
                "WHERE user_id = %s AND character_id = %s ORDER BY priority DESC, id ASC",
                (user_id, character_id),
            )
            return list(cursor.fetchall())


def clear_candidates(user_id: str, character_id: str, ids: Sequence[int] | None = None) -> None:
    with connection() as conn:
        with conn.cursor() as cursor:
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"DELETE FROM hlm_memory_candidate WHERE user_id = %s AND character_id = %s "
                    f"AND id IN ({placeholders})",
                    (user_id, character_id, *ids),
                )
            else:
                cursor.execute(
                    "DELETE FROM hlm_memory_candidate WHERE user_id = %s AND character_id = %s",
                    (user_id, character_id),
                )


def add_long_memory(user_id: str, character_id: str, content: str, category: str = "", priority: int = 1) -> int:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_memory_long (user_id, character_id, content, category, priority) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, character_id, content, category, priority),
            )
            return int(cursor.lastrowid or 0)


def list_long_memory(
    user_id: str,
    character_id: str,
    limit: int | None = None,
    include_forgotten: bool = False,
) -> list[dict[str, Any]]:
    size = limit or settings.long_term_limit
    clause = "" if include_forgotten else "AND forgotten = 0"
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, content, category, priority, forgotten FROM hlm_memory_long "
                f"WHERE user_id = %s AND character_id = %s {clause} ORDER BY priority DESC, id ASC LIMIT %s",
                (user_id, character_id, size),
            )
            return list(cursor.fetchall())


def mark_forgotten(user_id: str, ids: Iterable[int]) -> int:
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    placeholders = ",".join(["%s"] * len(ids))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE hlm_memory_long SET forgotten = 1 WHERE user_id = %s AND id IN ({placeholders})",
                (user_id, *ids),
            )
            return int(cursor.rowcount or 0)


# ---------------------------------------------------------------- 好感度与事件（主角专属）

def get_affection(user_id: str, character_id: str) -> dict[str, Any]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO hlm_affection (user_id, character_id, affection, stage, meaningful_count) "
                "VALUES (%s, %s, 0.00, '初识', 0)",
                (user_id, character_id),
            )
            cursor.execute(
                "SELECT affection, stage, meaningful_count FROM hlm_affection WHERE user_id = %s AND character_id = %s",
                (user_id, character_id),
            )
            row = cursor.fetchone() or {"affection": 0, "stage": "初识", "meaningful_count": 0}
    return {
        "affection": float(row["affection"]),
        "stage": row["stage"],
        "meaningful_count": int(row["meaningful_count"]),
    }


def upsert_affection(user_id: str, character_id: str, affection: float, stage: str, meaningful_count: int) -> None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_affection (user_id, character_id, affection, stage, meaningful_count) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE affection = VALUES(affection), stage = VALUES(stage), "
                "meaningful_count = VALUES(meaningful_count)",
                (user_id, character_id, affection, stage, meaningful_count),
            )


def record_event(user_id: str, character_id: str, event_type: str, detail: str = "") -> None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO hlm_events (user_id, character_id, event_type, detail) VALUES (%s, %s, %s, %s)",
                (user_id, character_id, event_type, detail),
            )


def triggered_vignettes(user_id: str) -> set[str]:
    """这局里已经经历过的房间小关目。按用户记，不分人物——同一件事在同一个世界里只发生一次。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT event_type FROM hlm_events "
                "WHERE user_id = %s AND event_type LIKE '关目:%%'",
                (user_id,),
            )
            return {str(row["event_type"])[3:] for row in cursor.fetchall()}


def recent_event_types(user_id: str, character_id: str, limit: int = 8) -> list[str]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT event_type FROM hlm_events WHERE user_id = %s AND character_id = %s "
                "ORDER BY id DESC LIMIT %s",
                (user_id, character_id, limit),
            )
            return [str(row["event_type"]) for row in cursor.fetchall()]
