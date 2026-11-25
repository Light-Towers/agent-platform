"""ADR-0017/T4：创建 BM25+jieba 新集合（不删旧集合，供灰度切换）。

用法：
    python -m knowledge_service.scripts.create_bm25_collection --uri http://<host>:19530 \
        --collection product_manual_v4_bge_m3 --dim 1024

- 本脚本只建集合与索引，不写数据；数据由导入侧双写 / 重灌补齐。
- analyzer 配置来自 agent_runtime.retrieval_tokenizer.milvus_analyzer_params()（单一事实源）。
- 需要真机环境验证（T2）：自定义词典挂载方式、BM25 hybrid 腿、SDK/服务端兼容。
"""

from __future__ import annotations

import argparse
from typing import Any

from agent_runtime.retrieval_tokenizer import milvus_analyzer_params
from pymilvus import DataType, Function, FunctionType, MilvusClient


def build_schema(client: MilvusClient, collection: str, dim: int, bm25_field: str) -> Any:
    schema = client.create_schema(auto_id=True, enable_dynamic_fields=True)
    schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field(
        field_name="content",
        datatype=DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        analyzer_params=milvus_analyzer_params(),
    )
    schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field(field_name=bm25_field, datatype=DataType.SPARSE_FLOAT_VECTOR)
    # 业务字段与隔离字段（与旧集合逐字段镜像）
    for name in (
        "title",
        "parent_title",
        "file_title",
        "item_name",
        "tenant_id",
        "scope_type",
        "knowledge_id",
        "status",
        "embedding_model",
        "chunk_version",
        "created_at",
        "source_doc",
    ):
        datatype = DataType.INT64 if name == "created_at" else DataType.VARCHAR
        max_length = None if datatype == DataType.INT64 else (16 if name == "status" else 65535)
        if max_length is None:
            schema.add_field(field_name=name, datatype=datatype)
        else:
            schema.add_field(field_name=name, datatype=datatype, max_length=max_length)
    schema.add_function(
        Function(
            name="content_bm25_emb",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names=[bm25_field],
        )
    )
    return schema


def build_indexes(client: MilvusClient, bm25_field: str) -> Any:
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="dense_vector", index_name="dense_vector_index", index_type="HNSW", metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    index_params.add_index(
        field_name=bm25_field, index_name="bm25_sparse_index", index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25", params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    return index_params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--bm25-field", default="bm25_sparse")
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)

    client = MilvusClient(uri=args.uri, token=args.token or None)
    if client.has_collection(collection_name=args.collection):
        print(f"集合 {args.collection} 已存在，不重建（避免误删数据）")
        return 0
    client.create_collection(
        collection_name=args.collection,
        schema=build_schema(client, args.collection, args.dim, args.bm25_field),
        index_params=build_indexes(client, args.bm25_field),
    )
    print(f"已创建 BM25 集合 {args.collection}；analyzer={milvus_analyzer_params()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
