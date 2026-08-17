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

    表 schema（无 tenant 隔离时）：
        memories(id BIGSERIAL, user_id TEXT, content TEXT, embedding VECTOR(dim))
    启用 tenant 隔离时追加 ``tenant_id TEXT NOT NULL`` 列并参与过滤。

    索引：HNSW（vector_cosine_ops）。dim 由 embedding 提供方派生。

    pool 策略：
      - 调用方传入 asyncpg 池 → 复用；
      - 否则（pool=None）→ 后端自建 asyncpg 池（需 database_url）。
    """

    def __init__(
        self,
        database_url: str = "",
        collection: str = "memories",
        tenant_id: str | None = None,
        embedder: Any | None = None,
    ) -> None:
        self._dsn = database_url
        self._table = collection
        self._tenant_id = tenant_id
        # 允许宿主注入自有 embedder（如 app 复用其 RAG 的 embedding，保证 dim/CI 一致）；
        # 未注入则用共享内核 embedder。
        self._embedder = embedder if embedder is not None else get_embedder()
        self._pool: Any = None
        logger.info(
            "PgVectorMemoryBackend 已配置表 %s (dim=%s, tenant=%s)",
            collection, self._embedder.dim, tenant_id,
        )

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            if not self._dsn:
                raise RuntimeError("PgVectorMemoryBackend 需要 database_url（内存模式不可用）")
            import asyncpg

            self._asyncpg = asyncpg
            self._pool = await self._asyncpg.create_pool(self._dsn)
        return self._pool

    async def _init_schema(self, conn: Any) -> None:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        if self._tenant_id is not None:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id BIGSERIAL PRIMARY KEY,"
                " tenant_id TEXT NOT NULL,"
                " user_id TEXT NOT NULL,"
                " content TEXT NOT NULL,"
                f" embedding VECTOR({self._dim}))"
            )
        else:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id BIGSERIAL PRIMARY KEY,"
                " user_id TEXT NOT NULL,"
                " content TEXT NOT NULL,"
                f" embedding VECTOR({self._dim}))"
            )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self._table}_hnsw"
            f" ON {self._table} USING hnsw (embedding vector_cosine_ops)"
        )

    async def _embed_one(self, text: str) -> list[float]:
        """优先走 async embed（避免嵌套事件循环死锁），回退到同步 embed。"""
        emb = self._embedder
        if hasattr(emb, "aembed"):
            return (await emb.aembed([text]))[0]
        return emb.embed([text])[0]

    async def recall(
        self, pool: Any, user_id: str, question: str, k: int = 3
    ) -> list[str]:
        if not question:
            return []
        vec = await self._embed_one(question)
        cp = pool or await self._ensure_pool()
        try:
            async with cp.acquire() as conn:
                if self._tenant_id is not None:
                    rows = await conn.fetch(
                        f"SELECT content FROM {self._table}"
                        " WHERE tenant_id=$1 AND user_id=$2"
                        " ORDER BY embedding <=> $3 LIMIT $4",
                        self._tenant_id, user_id, _to_pg_vector(vec), k,
                    )
                else:
                    rows = await conn.fetch(
                        f"SELECT content FROM {self._table}"
                        " WHERE user_id=$1"
                        " ORDER BY embedding <=> $2 LIMIT $3",
                        user_id, _to_pg_vector(vec), k,
                    )
            return [r["content"] for r in rows]
        finally:
            if pool is None:
                pass  # 自建池复用，不在此关闭

    def remember(self, pool: Any, user_id: str, content: str) -> None:
        """同步沉淀记忆（后台线程执行异步写入，不阻塞调用方）。"""
        import threading

        def _run() -> None:
            loop = _new_loop()
            try:
                loop.run_until_complete(self._aremember(pool, user_id, content))
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    async def _aremember(self, pool: Any, user_id: str, content: str) -> None:
        vec = await self._embed_one(content)
        cp = pool or await self._ensure_pool()
        async with cp.acquire() as conn:
            await self._init_schema(conn)
            if self._tenant_id is not None:
                await conn.execute(
                    f"INSERT INTO {self._table} (tenant_id, user_id, content, embedding)"
                    " VALUES ($1, $2, $3, $4)",
                    self._tenant_id, user_id, content, _to_pg_vector(vec),
                )
            else:
                await conn.execute(
                    f"INSERT INTO {self._table} (user_id, content, embedding)"
                    " VALUES ($1, $2, $3)",
                    user_id, content, _to_pg_vector(vec),
                )


def _to_pg_vector(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


def _new_loop():
    import asyncio

    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.new_event_loop()


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
