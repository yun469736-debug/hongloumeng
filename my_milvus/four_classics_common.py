"""四大名著 Milvus 工具的共享配置与辅助函数。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import ollama
from pymilvus import MilvusClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URI = "http://127.0.0.1:19530"
DEFAULT_TOKEN = "root:Milvus"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "bge-m3"
DEFAULT_COLLECTION = "four_classics_chunks"
SPLITTER_VERSION = "chapter-char-v1"

BOOK_FILES = (
    "《三国演义》.txt",
    "《水浒传》.txt",
    "《红楼梦》.txt",
    "《西游记》.txt",
)


def milvus_client(uri: str, token: str) -> MilvusClient:
    return MilvusClient(uri=uri, token=token, timeout=60)


def ollama_client(host: str) -> ollama.Client:
    return ollama.Client(host=host, trust_env=False, timeout=180)


def detect_embedding_dimension(client: ollama.Client, model: str) -> int:
    response = client.embed(model=model, input=["向量维度检测"])
    vectors = response.embeddings
    if not vectors or not vectors[0]:
        raise RuntimeError(f"Ollama 模型 {model!r} 没有返回向量")
    return len(vectors[0])


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def logical_id(
    book_name: str,
    chapter_no: int,
    chunk_no: int,
    chunk_size: int,
    chunk_overlap: int,
) -> str:
    """生成稳定主键，同一逻辑分块可安全重跑并覆盖。"""
    identity = "\x1f".join(
        (
            book_name,
            str(chapter_no),
            str(chunk_no),
            str(chunk_size),
            str(chunk_overlap),
            SPLITTER_VERSION,
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()

