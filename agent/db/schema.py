# -*- coding: utf-8 -*-
"""正式迁移脚本：表结构幂等建立，并把旧版 `daiyu_*` 表整体搬迁到中性前缀 `hlm_*`。

命名缘由：加入配角之后，`hlm_chat` 里会同时存着林黛玉与薛宝钗等所有人的台词，
再叫 `daiyu_chat` 就会误导后来读代码的人。共享表与"黛玉专属"表的分工见各表注释。
"""

from __future__ import annotations

import logging

from agent.config import settings
from agent.db.connection import connection, ensure_database

logger = logging.getLogger(__name__)

# 旧前缀 → 新前缀（仅当旧表存在且新表不存在时才搬迁，可重复执行）
LEGACY_RENAMES = (
    ("daiyu_users", "hlm_users"),
    ("daiyu_chat", "hlm_chat"),
    ("daiyu_memory_long", "hlm_memory_long"),
    ("daiyu_memory_candidate", "hlm_memory_candidate"),
    ("daiyu_affection", "hlm_affection"),
    ("daiyu_events", "hlm_events"),
)

# 需要补上 character_id 的"私有"表（搬迁过来的旧数据都属于林黛玉）
PRIVATE_TABLES = ("hlm_memory_long", "hlm_memory_candidate")

SHARED_TABLES = "hlm_users / hlm_chat / hlm_user_profile / hlm_character_state"
PROTAGONIST_TABLES = "hlm_memory_long / hlm_memory_candidate / hlm_affection / hlm_events"

STATEMENTS = (
    # 共享：用户与全局游戏时钟
    """
    CREATE TABLE IF NOT EXISTS hlm_users (
      user_id      VARCHAR(64)  NOT NULL,
      game_day     INT          NOT NULL DEFAULT 1,
      game_period  VARCHAR(16)  NOT NULL DEFAULT '清晨',
      created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 共享：房间公开发言记录（所有人的台词都在这里，任何真实角色都能读）
    """
    CREATE TABLE IF NOT EXISTS hlm_chat (
      id            BIGINT       NOT NULL AUTO_INCREMENT,
      user_id       VARCHAR(64)  NOT NULL,
      session_id    VARCHAR(64)  NOT NULL DEFAULT '',
      scene         VARCHAR(32)  NOT NULL DEFAULT '',
      speaker       VARCHAR(64)  NOT NULL,
      text          TEXT         NOT NULL,
      emotion       VARCHAR(32)  NOT NULL DEFAULT '',
      action        VARCHAR(32)  NOT NULL DEFAULT '',
      kind          VARCHAR(32)  NOT NULL DEFAULT '',
      self_turn     TINYINT      NOT NULL DEFAULT 0,
      evidence_json TEXT         NULL,
      created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (id),
      KEY idx_chat_user (user_id, id),
      KEY idx_chat_scene (user_id, scene, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 共享：来客自报的"公开"信息（姓名、称呼、性别、身份）——所有真实角色都能感知
    """
    CREATE TABLE IF NOT EXISTS hlm_user_profile (
      user_id     VARCHAR(64)  NOT NULL,
      fact_key    VARCHAR(32)  NOT NULL,
      fact_value  VARCHAR(255) NOT NULL,
      updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, fact_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 主角专属：长期压缩记忆
    """
    CREATE TABLE IF NOT EXISTS hlm_memory_long (
      id           BIGINT       NOT NULL AUTO_INCREMENT,
      user_id      VARCHAR(64)  NOT NULL,
      character_id VARCHAR(64)  NOT NULL DEFAULT '林黛玉',
      content      TEXT         NOT NULL,
      category     VARCHAR(32)  NOT NULL DEFAULT '',
      priority     INT          NOT NULL DEFAULT 1,
      forgotten    TINYINT      NOT NULL DEFAULT 0,
      created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (id),
      KEY idx_memory_owner (user_id, character_id, forgotten)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 主角专属：候选记忆（每轮先记，下一轮统一压缩）
    """
    CREATE TABLE IF NOT EXISTS hlm_memory_candidate (
      id           BIGINT       NOT NULL AUTO_INCREMENT,
      user_id      VARCHAR(64)  NOT NULL,
      character_id VARCHAR(64)  NOT NULL DEFAULT '林黛玉',
      content      TEXT         NOT NULL,
      category     VARCHAR(32)  NOT NULL DEFAULT '',
      priority     INT          NOT NULL DEFAULT 1,
      created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (id),
      KEY idx_candidate_owner (user_id, character_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 主角专属：隐藏好感度与七阶段
    """
    CREATE TABLE IF NOT EXISTS hlm_affection (
      user_id            VARCHAR(64)  NOT NULL,
      character_id       VARCHAR(64)  NOT NULL,
      affection          DECIMAL(6,2) NOT NULL DEFAULT 0.00,
      stage              VARCHAR(16)  NOT NULL DEFAULT '初识',
      meaningful_count   INT          NOT NULL DEFAULT 0,
      updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, character_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 共享：十二位人物的心绪/态度/心事——"原著剧情影响到人物"的落点
    """
    CREATE TABLE IF NOT EXISTS hlm_character_state (
      user_id       VARCHAR(64)  NOT NULL,
      character_id  VARCHAR(64)  NOT NULL,
      mood          VARCHAR(32)  NOT NULL DEFAULT '',
      attitude      DECIMAL(4,2) NOT NULL DEFAULT 2.50,
      secret        VARCHAR(255) NOT NULL DEFAULT '',
      updated_day   INT          NOT NULL DEFAULT 1,
      updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, character_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 共享：入梦择章的进度
    """
    CREATE TABLE IF NOT EXISTS hlm_dream_progress (
      user_id       VARCHAR(64)  NOT NULL,
      chapter_key   VARCHAR(32)  NOT NULL,
      segment_index INT          NOT NULL DEFAULT 0,
      status        VARCHAR(16)  NOT NULL DEFAULT 'started',
      settled       TINYINT      NOT NULL DEFAULT 0,
      cast_json     VARCHAR(512) NOT NULL DEFAULT '',
      created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, chapter_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 共享：入梦择章做过的选择（只结算一次时用来对账）
    """
    CREATE TABLE IF NOT EXISTS hlm_dream_choice (
      id          BIGINT       NOT NULL AUTO_INCREMENT,
      user_id     VARCHAR(64)  NOT NULL,
      chapter_key VARCHAR(32)  NOT NULL,
      node_key    VARCHAR(16)  NOT NULL,
      option_key  VARCHAR(8)   NOT NULL,
      created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (id),
      KEY idx_dream_choice (user_id, chapter_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 主角专属：关系事件流水
    """
    CREATE TABLE IF NOT EXISTS hlm_events (
      id           BIGINT       NOT NULL AUTO_INCREMENT,
      user_id      VARCHAR(64)  NOT NULL,
      character_id VARCHAR(64)  NOT NULL,
      event_type   VARCHAR(64)  NOT NULL,
      detail       TEXT         NULL,
      created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (id),
      KEY idx_event_user (user_id, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def _existing_tables(cursor) -> set[str]:
    cursor.execute(
        "SELECT table_name AS name FROM information_schema.tables WHERE table_schema = %s",
        (settings.mysql_db,),
    )
    return {str(row["name"]) for row in cursor.fetchall()}


def _rename_legacy(cursor) -> list[str]:
    """把旧版 daiyu_* 表整体搬迁到 hlm_*；已搬过或不存在则跳过。"""
    tables = _existing_tables(cursor)
    renamed: list[str] = []
    for old, new in LEGACY_RENAMES:
        if old in tables and new not in tables:
            cursor.execute(f"RENAME TABLE `{old}` TO `{new}`")
            renamed.append(f"{old} → {new}")
            tables.discard(old)
            tables.add(new)
    return renamed


def _has_column(cursor, table: str, column: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) AS total FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
        (settings.mysql_db, table, column),
    )
    row = cursor.fetchone() or {}
    return int(row.get("total") or 0) > 0


def _ensure_private_owner_column(cursor) -> None:
    """旧表没有 character_id；补上并让历史数据归属林黛玉。"""
    for table in PRIVATE_TABLES:
        if not _has_column(cursor, table, "character_id"):
            cursor.execute(
                f"ALTER TABLE `{table}` ADD COLUMN character_id VARCHAR(64) NOT NULL DEFAULT '林黛玉' AFTER user_id"
            )
            logger.info("已为 %s 补上 character_id 列", table)


def _ensure_chat_scene_column(cursor) -> None:
    """旧库的 hlm_chat 没有 scene；补上，历史记录归为未分房。"""
    if not _has_column(cursor, "hlm_chat", "scene"):
        cursor.execute(
            "ALTER TABLE `hlm_chat` ADD COLUMN scene VARCHAR(32) NOT NULL DEFAULT '' AFTER session_id"
        )
        logger.info("已为 hlm_chat 补上 scene 列（历史记录 scene 为空，只在全量回看里出现）")


def migrate(seed_user_id: str | None = None) -> None:
    """建库 + 搬迁旧表 + 建表 + 种默认用户。可重复执行。"""
    ensure_database()
    with connection() as conn:
        with conn.cursor() as cursor:
            renamed = _rename_legacy(cursor)
            if renamed:
                logger.info("旧表已搬迁：%s", "，".join(renamed))

            for statement in STATEMENTS:
                cursor.execute(statement)

            _ensure_private_owner_column(cursor)
            _ensure_chat_scene_column(cursor)

            user_id = seed_user_id or settings.default_user_id
            cursor.execute(
                "INSERT IGNORE INTO hlm_users (user_id, game_day, game_period) VALUES (%s, 1, '清晨')",
                (user_id,),
            )
            cursor.execute(
                "INSERT IGNORE INTO hlm_affection (user_id, character_id, affection, stage, meaningful_count) "
                "VALUES (%s, '林黛玉', 0.00, '初识', 0)",
                (user_id,),
            )
    logger.info("迁移完成，默认用户：%s", seed_user_id or settings.default_user_id)
