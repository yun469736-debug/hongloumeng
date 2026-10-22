# -*- coding: utf-8 -*-
"""MySQL 连接。数据访问层只依赖这里暴露的连接，便于日后迁移云服务器。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from agent.config import mysql_config, settings

logger = logging.getLogger(__name__)


@contextmanager
def connection(with_db: bool = True) -> Iterator[pymysql.connections.Connection]:
    conn = pymysql.connect(cursorclass=DictCursor, **mysql_config(with_db=with_db))
    try:
        yield conn
    finally:
        conn.close()


def ensure_database() -> None:
    """创建业务库（若不存在）。仅在建库/迁移时调用。"""
    with connection(with_db=False) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_db}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    logger.info("数据库就绪：%s", settings.mysql_db)


def ping() -> bool:
    try:
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("MySQL 不可用：%s", exc)
        return False
