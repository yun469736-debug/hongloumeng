"""将项目根目录的四大名著分块后批量写入 Milvus。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.split_utils import split_text
from utils.text_processor import extract_text

from four_classics_common import (
    BOOK_FILES,
    DEFAULT_COLLECTION,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_TOKEN,
    DEFAULT_URI,
    SPLITTER_VERSION,
    content_hash,
    logical_id,
    milvus_client,
    ollama_client,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, help="每本书最多处理的分块数，用于验证")
    parser.add_argument("--dry-run", action="store_true", help="只解析和统计，不调用 Ollama/Milvus")
    return parser.parse_args()


def rows_for_book(path: Path, chunk_size: int, chunk_overlap: int):
    book_name = path.stem.strip("《》")
    chunks = split_text(
        extract_text(path),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    rows = []
    now = int(time.time())
    for chunk in chunks:
        rows.append(
            {
                "id": logical_id(
                    book_name,
                    chunk["chapter_id"],
                    chunk["chapter_chunk_id"],
                    chunk_size,
                    chunk_overlap,
                ),
                "book_name": book_name,
                "chapter_no": chunk["chapter_id"],
                "chapter_title": chunk["chapter_title"],
                "chunk_no": chunk["chapter_chunk_id"],
                "content": chunk["content"],
                "char_start": chunk["start"],
                "char_end": chunk["end"],
                "source_file": path.name,
                "content_hash": content_hash(chunk["content"]),
                "splitter_version": SPLITTER_VERSION,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "created_at": now,
                "metadata": {"global_chunk_no": chunk["chunk_id"]},
            }
        )
    return rows


def batches(items, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def existing_hashes(client, collection: str, ids: list[str]) -> dict[str, str]:
    quoted = ",".join(f'"{item}"' for item in ids)
    found = client.query(
        collection_name=collection,
        filter=f"id in [{quoted}]",
        output_fields=["id", "content_hash"],
        limit=len(ids),
        consistency_level="Strong",
    )
    return {row["id"]: row["content_hash"] for row in found}


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size 必须大于 0")
    paths = [PROJECT_ROOT / name for name in BOOK_FILES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少文件：" + "、".join(missing))

    prepared = []
    for path in paths:
        rows = rows_for_book(path, args.chunk_size, args.chunk_overlap)
        if args.limit is not None:
            rows = rows[: args.limit]
        prepared.append((path, rows))
        print(f"{path.name}: {len(rows)} 个待处理分块")
    if args.dry_run:
        print("预演完成：未连接 Ollama 或 Milvus，未写入数据。")
        return

    embedding = ollama_client(args.ollama_host)
    db = milvus_client(args.uri, args.token)
    inserted = skipped = updated = 0
    try:
        if not db.has_collection(args.collection):
            raise RuntimeError("Collection 不存在，请先运行 create_four_classics_collection.py")
        db.load_collection(args.collection)
        for path, rows in prepared:
            completed = 0
            total = len(rows)
            for batch in batches(rows, args.batch_size):
                old_hashes = existing_hashes(db, args.collection, [row["id"] for row in batch])
                changed = [row for row in batch if old_hashes.get(row["id"]) != row["content_hash"]]
                skipped += len(batch) - len(changed)
                if changed:
                    response = embedding.embed(
                        model=args.model,
                        input=[row["content"] for row in changed],
                        truncate=False,
                    )
                    if len(response.embeddings) != len(changed):
                        raise RuntimeError("Ollama 返回的向量数量与文本块数量不一致")
                    for row, vector in zip(changed, response.embeddings):
                        row["embedding"] = vector
                    db.upsert(collection_name=args.collection, data=changed)
                    inserted += sum(row["id"] not in old_hashes for row in changed)
                    updated += sum(row["id"] in old_hashes for row in changed)
                for _ in batch:
                    completed += 1
                    print(f"{path.stem}已完成：{completed}块/{total}块", flush=True)
            print(f"{path.name}: 处理完成")
        db.flush(args.collection)
        print(f"完成：新增 {inserted}，更新 {updated}，跳过 {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
