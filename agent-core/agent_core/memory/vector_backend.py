# -*- coding: utf-8 -*-
"""语义长期记忆的向量存储后端（可切换，所有子包统一）。

架构决策：
  - 默认向量后端 = **Milvus**（专用向量库，水平扩展、写入吞吐优于 pgvector）。
  - 备选向量后端 = **PostgreSQL + pgvector**（保留为可切换方案）。
  - Embedding 来源 = **共享 agent_core.memory.embedder**（按配置动态远程/本地切换）。

两个向量后端都实现 ``agent_core.memory.MemoryBackend`` 协议（recall / remember），
由 ``create_memory_backend(mode)`` 工厂按 ``VECTOR_BACKEND`` 环境变量切换。

依赖均为懒加载：缺包时抛出明确 ImportError，不在模块导入期阻断主链路。

此前 Milvus 后端实现在 deepagents/agent/memory/vector_backends.py，PgVector 实现另在
app/memory/memory_backend.py，现已统一收口到内核，子包直接 import。
"""

from __future__ import annotations

import os
from typing import Any

from agent_core.logging import get_logger
from agent_core.memory.backend import MemoryBackend
from agent_core.memory.embedder import get_embedder

logger = get_logger(__name__)

DEFAULT_COLLECTION = "semantic_memory"


# ==========================================================================
# Milvus 后端（默认）
# ==========================================================================
class MilvusMemoryBackend(MemoryBackend):
    """Milvus 语义记忆后端。

    集合 schema：
        id (AutoID, primary)
        user_id (VarChar)
        tenant_id (VarChar)
        content (VarChar, 原文)
        embedding (FloatVector, dim)
    索引：COSINE（HNSW）。
    """

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        token: str = "",
        collection: str = DEFAULT_COLLECTION,
        tenant_id: str = "default",
    ) -> None:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            connections,
            utility,
        )

        self._Collection = Collection
        self._utility = utility
        self._connections = connections
        self._DataType = DataType
        self._FieldSchema = FieldSchema
        self._CollectionSchema = CollectionSchema
        self._collection_name = collection
        self._tenant_id = tenant_id
        self._embedder = get_embedder()
        self._dim = self._embedder.dim

        connections.connect(alias="default", uri=uri, token=token or "")
        if not utility.has_collection(collection):
            self._create_collection()
        self._coll: Collection = Collection(collection)
        self._coll.load()
        logger.info("MilvusMemoryBackend 已连接集合 %s (dim=%s)", collection, self._dim)

    def _create_collection(self) -> None:
        fields = [
            FieldSchema(name="id", dtype=self._DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="user_id", dtype=self._DataType.VARCHAR, max_length=128),
            FieldSchema(name="tenant_id", dtype=self._DataType.VARCHAR, max_length=128),
            FieldSchema(name="content", dtype=self._DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=self._DataType.FLOAT_VECTOR, dim=self._dim),
        ]
        schema = self._CollectionSchema(fields=fields)
        self._Collection(name=self._collection_name, schema=schema)
        self._utility.create_index(
            self._collection_name,
            "embedding",
            {"index_type": "HNSW", "metric_type": "COSINE", "params": {"M": 8, "efConstruction": 200}},
        )

    async def recall(
        self, pool: Any, user_id: str, question: str, k: int = 3
    ) -> list[str]:
        if not question:
            return []
        vec = self._embedder.embed([question])[0]
        expr = f'user_id == "{user_id}" and tenant_id == "{self._tenant_id}"'
        res = self._coll.search(
            data=[vec],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=k,
            expr=expr,
            output_fields=["content"],
        )
        return [hit.entity.get("content") for hit in res[0]] if res else []

    def remember(self, pool: Any, user_id: str, content: str) -> None:
        vec = self._embedder.embed([content])[0]
        self._coll.insert([[user_id], [self._tenant_id], [content], [vec]])


# ==========================================================================
# PostgreSQL + pgvector 备选后端
# ==========================================================================
class PgVectorMemoryBackend(MemoryBackend):
    """PostgreSQL + pgvector 语义记忆后端（备选方案）。

    表 schema：memory_embeddings(id, tenant_id, user_id, content, embedding VECTOR(dim))
    索引：HNSW（vector_cosine_ops）。dim 由 embedding 提供方派生。
    """

    def __init__(
        self,
        database_url: str,
        collection: str = "memory_embeddings",
        tenant_id: str = "default",
    ) -> None:
        import asyncpg

        self._asyncpg = asyncpg
        self._dsn = database_url
        self._table = collection
        self._tenant_id = tenant_id
        self._embedder = get_embedder()
        self._dim = self._embedder.dim
        self._pool: Any = None
        logger.info("PgVectorMemoryBackend 已配置表 %s (dim=%s)", collection, self._dim)

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            self._pool = await self._asyncpg.create_pool(self._dsn)
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._table} ("
                    " id BIGSERIAL PRIMARY KEY,"
                    " tenant_id TEXT NOT NULL,"
                    " user_id TEXT NOT NULL,"
                    " content TEXT NOT NULL,"
                    f" embedding VECTOR({self._dim}))"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._table}_hnsw"
                    f" ON {self._table} USING hnsw (embedding vector_cosine_ops)"
                )
        return self._pool

    async def recall(
        self, pool: Any, user_id: str, question: str, k: int = 3
    ) -> list[str]:
        if not question:
            return []
        vec = self._embedder.embed([question])[0]
        use_self = pool is None
        cp = pool or await self._ensure_pool()
        try:
            async with cp.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT content FROM {self._table}"
                    " WHERE tenant_id=$1 AND user_id=$2"
                    " ORDER BY embedding <=> $3 LIMIT $4",
                    self._tenant_id, user_id, _to_pg_vector(vec), k,
                )
            return [r["content"] for r in rows]
        finally:
            if use_self:
                pass  # 自建池复用，不在此关闭

    def remember(self, pool: Any, user_id: str, content: str) -> None:
        raise RuntimeError(
            "PgVectorMemoryBackend.remember 为异步后端，请通过 semantic_memory 门面调用（异步写入）"
        )


def _to_pg_vector(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


# ==========================================================================
# 工厂
# ==========================================================================
def create_memory_backend(
    mode: str = "milvus",
    *,
    uri: str = "http://localhost:19530",
    token: str = "",
    database_url: str = "",
    collection: str = DEFAULT_COLLECTION,
    tenant_id: str = "default",
) -> MemoryBackend:
    """按 mode 创建向量后端。

    mode="milvus" → MilvusMemoryBackend（默认）
    mode="pg"     → PgVectorMemoryBackend（备选）
    embedding 维度由共享 embedder 动态派生（远程 bge-m3=1024 / 本地 bge-small-zh=512）。
    """
    if mode == "milvus":
        return MilvusMemoryBackend(uri=uri, token=token, collection=collection, tenant_id=tenant_id)
    if mode == "pg":
        if not database_url:
            raise ValueError("pg 后端需要 database_url")
        return PgVectorMemoryBackend(database_url=database_url, collection=collection, tenant_id=tenant_id)
    raise ValueError(f"未知 VECTOR_BACKEND: {mode}")


__all__ = ["MilvusMemoryBackend", "PgVectorMemoryBackend", "create_memory_backend", "DEFAULT_COLLECTION"]
