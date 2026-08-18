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

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent_core.logging import get_logger
from agent_core.memory.backend import MemoryBackend
from agent_core.memory.embedder import get_embedder

logger = get_logger(__name__)

DEFAULT_COLLECTION = "semantic_memory"

# 后台线程池：把阻塞式向量库 SDK（Milvus pymilvus）调用移出事件循环，
# 避免 LangGraph astream 等 async 上下文被同步 SDK 阻塞。
_MILVUS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="milvus-io")


def _run_sync(fn, *args, **kwargs):
    """在线程池执行阻塞调用并在事件循环内 await（避免阻塞 asyncio 调度）。

    兼容两种调用上下文：
      - async 主流程中已有 running loop → 用 get_running_loop；
      - 后台 daemon 线程的 ``loop.run_until_complete`` 内（Milvus.remember）→
        同样已有 running loop，故优先 get_running_loop，缺失时退回 get_event_loop。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    return loop.run_in_executor(_MILVUS_EXECUTOR, functools.partial(fn, *args, **kwargs))


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
        embedder: Any | None = None,
    ) -> None:
        self._collection_name = collection
        self._tenant_id = tenant_id
        self._uri = uri
        self._token = token or ""
        self._embedder = embedder or get_embedder()
        self._dim = self._embedder.dim
        self._coll: Any = None
        self._connected = False
        logger.info("MilvusMemoryBackend 已配置集合 %s (dim=%s)", collection, self._dim)

    def _connect(self) -> Any:
        """懒连接（同步，调用方负责放入 executor）。

        延迟到首次实际使用时连接，避免在对象构造期（可能处于事件循环中）执行
        阻塞式 ``connections.connect``，与 PgVectorMemoryBackend 的池惰性初始化一致。
        同样把 ``pymilvus`` 的（可选）import 放在此处，未安装时不影响对象构造与单测。
        """
        if self._connected and self._coll is not None:
            return self._coll
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
        self._connections.connect(alias="default", uri=self._uri, token=self._token)
        if not self._utility.has_collection(self._collection_name):
            self._create_collection()
        coll = self._Collection(self._collection_name)
        coll.load()
        self._coll = coll
        self._connected = True
        return coll

    async def _aembed(self, text: str) -> list[float]:
        """异步取单条 embedding，优先 ``aembed``（与 PgVectorMemoryBackend._embed_one 对齐）。

        避免事件循环内对 LocalFnEmbedder 调同步 ``embed``（其内部 asyncio.run 会死锁）；
        无 aembed 时回退同步 embed 并丢到线程池，不阻塞调度。
        """
        if hasattr(self._embedder, "aembed"):
            return (await self._embedder.aembed([text]))[0]
        vec = await _run_sync(self._embedder.embed, [text])
        return vec[0]

    def _create_collection(self) -> None:
        from pymilvus import CollectionSchema, DataType, FieldSchema

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self._dim),
        ]
        schema = CollectionSchema(fields=fields)
        self._Collection(name=self._collection_name, schema=schema)
        self._utility.create_index(
            self._collection_name,
            "embedding",
            {"index_type": "HNSW", "metric_type": "COSINE", "params": {"M": 8, "efConstruction": 200}},
        )

    @staticmethod
    def _escape_milvus_str(value: str) -> str:
        """转义 Milvus 标量过滤表达式中被视为字面量的字符串。

        Milvus expr 不支持参数占位符，字符串字面量需用双引号包裹。若 ``value``
        含双引号/反斜杠，会被解释为表达式语法（注入风险）。这里对反斜杠与双引号
        做转义，并拒绝换行等非法字符，保证 expr 只作字面量匹配。
        """
        if not isinstance(value, str) or not value:
            raise ValueError("Milvus 过滤字段必须为非空字符串")
        if any(ch in value for ch in "\n\r\t"):
            raise ValueError("Milvus 过滤字段含非法控制字符")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return escaped

    async def recall(
        self, pool: Any, user_id: str, question: str, k: int = 3
    ) -> list[str]:
        if not question:
            return []
        vec = await self._aembed(question)
        coll = await _run_sync(self._connect)
        safe_user = self._escape_milvus_str(user_id)
        safe_tenant = self._escape_milvus_str(self._tenant_id)
        expr = f'user_id == "{safe_user}" and tenant_id == "{safe_tenant}"'

        def _search() -> list[str]:
            res = coll.search(
                data=[vec],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=k,
                expr=expr,
                output_fields=["content"],
            )
            return [hit.entity.get("content") for hit in res[0]] if res else []

        return await _run_sync(_search)

    def remember(self, pool: Any, user_id: str, content: str) -> None:
        """同步沉淀记忆（后台线程执行异步写入，不阻塞调用方）。

        与 PgVectorMemoryBackend.remember 一致：起一个 daemon 线程跑完整 asyncio
        写入流程（含 async embed + 线程池包裹的 Milvus insert），避免：
          1) 在调用方事件循环中同步阻塞 SDK；
          2) 对 LocalFnEmbedder 同步嵌入造成 asyncio.run 嵌套死锁。
        """
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
        vec = await self._aembed(content)
        coll = await _run_sync(self._connect)
        await _run_sync(
            coll.insert, [[user_id], [self._tenant_id], [content], [vec]]
        )


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
        self._dim = self._embedder.dim
        self._pool: Any = None
        logger.info(
            "PgVectorMemoryBackend 已配置表 %s (dim=%s, tenant=%s)",
            collection, self._dim, tenant_id,
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
                f" embedding VECTOR({self._dim}),"
                " memory_type TEXT NOT NULL DEFAULT 'semantic',"
                " importance FLOAT NOT NULL DEFAULT 0.5,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        else:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id BIGSERIAL PRIMARY KEY,"
                " user_id TEXT NOT NULL,"
                " content TEXT NOT NULL,"
                f" embedding VECTOR({self._dim}),"
                " memory_type TEXT NOT NULL DEFAULT 'semantic',"
                " importance FLOAT NOT NULL DEFAULT 0.5,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self._table}_hnsw"
            f" ON {self._table} USING hnsw (embedding vector_cosine_ops)"
        )
        # ADR-0004 阶段 1：存量库迁移——新列 IF NOT EXISTS 不作用于已存在表，
        # 需要幂等 ALTER（duplicate_column 失败可忽略）。
        for _ddl in (
            f"ALTER TABLE {self._table} ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'",
            f"ALTER TABLE {self._table} ADD COLUMN importance FLOAT NOT NULL DEFAULT 0.5",
            f"ALTER TABLE {self._table} ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        ):
            try:
                await conn.execute(_ddl)
            except Exception:
                # duplicate_column 等幂等失败忽略
                pass

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
