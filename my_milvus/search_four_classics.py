"""使用 Ollama bge 模型检索四大名著 Collection。"""

from __future__ import annotations

import argparse

from four_classics_common import (
    DEFAULT_COLLECTION,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_TOKEN,
    DEFAULT_URI,
    milvus_client,
    ollama_client,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--book", help="仅检索指定书名，例如 红楼梦")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    vector = ollama_client(args.ollama_host).embed(
        model=args.model, input=[args.query]
    ).embeddings[0]
    db = milvus_client(args.uri, args.token)
    try:
        results = db.search(
            collection_name=args.collection,
            data=[vector],
            anns_field="embedding",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            filter=f'book_name == "{args.book}"' if args.book else "",
            limit=args.limit,
            output_fields=["book_name", "chapter_no", "chapter_title", "chunk_no", "content"],
        )
        for rank, hit in enumerate(results[0], 1):
            entity = hit["entity"]
            preview = entity["content"].replace("\n", " ")[:160]
            print(
                f"{rank}. {entity['book_name']} 第{entity['chapter_no']}回 "
                f"{entity['chapter_title']} [score={hit['distance']:.4f}]\n{preview}\n"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()

