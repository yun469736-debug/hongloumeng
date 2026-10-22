"""创建四大名著 Collection；不会覆盖已存在的 Collection。"""

from __future__ import annotations

import argparse

from pymilvus import DataType, Function, FunctionType, MilvusClient

from four_classics_common import (
    DEFAULT_COLLECTION,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_TOKEN,
    DEFAULT_URI,
    detect_embedding_dimension,
    milvus_client,
    ollama_client,
)


def build_schema(dimension: int):
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("book_name", DataType.VARCHAR, max_length=32)
    schema.add_field("chapter_no", DataType.INT64)
    schema.add_field("chapter_title", DataType.VARCHAR, max_length=512)
    schema.add_field("chunk_no", DataType.INT64)
    schema.add_field(
        "content",
        DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        enable_match=True,
    )
    schema.add_field("char_start", DataType.INT64)
    schema.add_field("char_end", DataType.INT64)
    schema.add_field("source_file", DataType.VARCHAR, max_length=512)
    schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
    schema.add_field("splitter_version", DataType.VARCHAR, max_length=32)
    schema.add_field("chunk_size", DataType.INT64)
    schema.add_field("chunk_overlap", DataType.INT64)
    schema.add_field("created_at", DataType.INT64)
    schema.add_field("metadata", DataType.JSON)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
    schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="content_bm25",
            input_field_names=["content"],
            output_field_names=["sparse_vector"],
            function_type=FunctionType.BM25,
        )
    )
    return schema


def build_indexes(client: MilvusClient):
    indexes = client.prepare_index_params()
    indexes.add_index(
        field_name="embedding",
        index_name="embedding_hnsw",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    indexes.add_index(
        field_name="sparse_vector",
        index_name="content_bm25_index",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    return indexes


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dimension = detect_embedding_dimension(ollama_client(args.ollama_host), args.model)
    client = milvus_client(args.uri, args.token)
    try:
        if client.has_collection(args.collection):
            description = client.describe_collection(args.collection)
            print(f"Collection 已存在，未做修改：{args.collection}")
            print(f"模型 {args.model} 当前向量维度：{dimension}")
            print(f"现有字段数：{len(description.get('fields', []))}")
            return
        client.create_collection(
            collection_name=args.collection,
            schema=build_schema(dimension),
            index_params=build_indexes(client),
        )
        print(f"已创建 Collection：{args.collection}（向量维度 {dimension}）")
    finally:
        client.close()


if __name__ == "__main__":
    main()

