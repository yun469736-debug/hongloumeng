# -*- coding: utf-8 -*-
"""集中配置：全部来自环境变量，缺省值可本机直接跑通。

连接信息与密钥只从环境变量（或项目根目录 .env）读取，不写入代码、不提交仓库。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _str(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or value == "" else value


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(_str(key, str(default)))
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = _str(key, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """运行时配置快照。"""

    # Ollama / 本地模型
    ollama_host: str = field(default_factory=lambda: _str("OLLAMA_HOST", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _str("OLLAMA_MODEL", "qwen3.5:4b"))
    embed_model: str = field(default_factory=lambda: _str("EMBED_MODEL", "bge-m3"))

    # Milvus 向量库
    milvus_uri: str = field(default_factory=lambda: _str("MILVUS_URI", "http://127.0.0.1:19530"))
    milvus_token: str = field(default_factory=lambda: _str("MILVUS_TOKEN", "root:Milvus"))
    milvus_collection: str = field(default_factory=lambda: _str("MILVUS_COLLECTION", "four_classics_chunks"))
    rag_book: str = field(default_factory=lambda: _str("RAG_BOOK", "红楼梦"))
    rag_top_k: int = field(default_factory=lambda: _int("RAG_TOP_K", 4))
    rag_min_score: float = field(default_factory=lambda: _float("RAG_MIN_SCORE", 0.42))

    # MySQL
    mysql_host: str = field(default_factory=lambda: _str("MYSQL_HOST", "127.0.0.1"))
    mysql_port: int = field(default_factory=lambda: _int("MYSQL_PORT", 3306))
    mysql_user: str = field(default_factory=lambda: _str("MYSQL_USER", "root"))
    mysql_password: str = field(default_factory=lambda: _str("MYSQL_PASSWORD", ""))
    mysql_db: str = field(default_factory=lambda: _str("MYSQL_DB", "daiyu_agent"))

    # 模型提供器：ollama（默认自托管）| deepseek（需人工开启）
    llm_provider: str = field(default_factory=lambda: _str("LLM_PROVIDER", "ollama"))
    deepseek_api_key: str = field(default_factory=lambda: _str("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: _str("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    deepseek_model: str = field(default_factory=lambda: _str("DEEPSEEK_MODEL", "deepseek-chat"))

    # 生成参数：默认关闭思考、限制上下文与输出，缩短首句等待
    think: bool = field(default_factory=lambda: _bool("LLM_THINK", False))
    num_ctx: int = field(default_factory=lambda: _int("LLM_NUM_CTX", 4096))
    num_predict: int = field(default_factory=lambda: _int("LLM_NUM_PREDICT", 300))
    temperature: float = field(default_factory=lambda: _float("LLM_TEMPERATURE", 0.8))
    keep_alive: str = field(default_factory=lambda: _str("LLM_KEEP_ALIVE", "30m"))

    # 会话与记忆
    default_user_id: str = field(default_factory=lambda: _str("DEFAULT_USER_ID", "local_default"))
    short_term_turns: int = field(default_factory=lambda: _int("SHORT_TERM_TURNS", 6))
    long_term_limit: int = field(default_factory=lambda: _int("LONG_TERM_LIMIT", 40))

    # 服务
    host: str = field(default_factory=lambda: _str("AGENT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("AGENT_PORT", 8000))
    cors_origins: str = field(default_factory=lambda: _str("AGENT_CORS_ORIGINS", "*"))


settings = Settings()


def mysql_config(with_db: bool = True) -> dict:
    """返回 pymysql.connect 所需参数；with_db=False 用于建库。"""
    config = {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "charset": "utf8mb4",
        "autocommit": True,
    }
    if with_db:
        config["database"] = settings.mysql_db
    return config
