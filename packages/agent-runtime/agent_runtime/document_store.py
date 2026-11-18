# -*- coding: utf-8 -*-
"""文档向量检索统一契约（协议）+ Milvus 默认实现（可切换后端，参考 MemoryBackend 模式）。

背景（ADR-0009 未决「存储合并」；plan-knowledge-base-model-2026-11-17）：
平台此前「UI 上传写 KS 的 Milvus、对话检索读 agent_server 自己的 pgvector」，两条
链路无双写无同步 ⇒ 上传的文档在对话里永远搜不到。修复方式**不是合并两个物理存储**
（ADR-0009 的 A/B 重启条件均未满足，不重开），而是：

- 抽象一份「文档向量检索」协议（本文件的 ``DocumentStore``）；
- 两个可替换实现：``MilvusDocumentStore``（默认）与宿主侧 ``PgVectorDocumentStore``
  （降级/自举备选，见 ``applications/agent_server/rag/pg_backend.py``）；
- 上传与检索经同一个 ``DOC_BACKEND`` 开关落到**同一个后端实例**（断裂的根因就是
  两条链路各写各的存储）。

协议形状对齐既有 ``agent_core.memory.MemoryBackend``（recall/remember）+``VECTOR_BACKEND``
工厂模式（``agent_core.memory.vector_backend.create_memory_backend``）：

- ``tenant_id``：必填安全边界（服务端断言；契约层无隐式默认，漏传即 TypeError/fail-fast）；
- ``workspace_id``：可选归属维（缺省 ``"default"``；pgvector 侧与 tenant 成对过滤，
  ADR-0006 T9）；
- ``knowledge_id``：可选知识库过滤，空 = 召回租户全部知识库（多库默认全库，选库是
  高级能力；老数据无 knowledge_id 时选库模式不召回、全库模式照常）；
- ``pool``：按调用传入（pgvector 用连接池，Milvus 忽略），契约层 object 占位。

Milvus 集合 schema 的单一事实源在 KS 侧 ``node_import_milvus.create_collection``
（上传管线的唯一写入方）；本文件的 schema 是其**逐字段镜像**（新增 knowledge_id /
workspace_id 两个标量字段，见集合版本 v2）。任何一侧改字段，另一侧必须同步——
「先建集合的一方」决定另一方的写入/检索行为。

依赖均为懒加载：缺 pymilvus 时抛出明确 ImportError，不在模块导入期阻断主链路
（与 agent_core.memory.vector_backend 同一纪律）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agent_core.logging import get_logger
from agent_core.memory._tenant_gate import resolve_tenant

logger = get_logger(__name__)

#: 平台文档集合默认名（v3：新增 status 软删除字段，Milvus 不能给已有集合加字段 ⇒ 换名）。
#: **不得**复用 KS 旧集合 product_manual_v1_bge_m3（缺 v2/v3 字段）或 v2 集合（缺 status）。
#: 同一集合名部署侧 KS 与平台必须指向一致（KS 经 CHUNKS_COLLECTION env，平台经 DOC_MILVUS_COLLECTION）。
DEFAULT_DOC_COLLECTION = "platform_doc_v3_bge_m3"

#: 单条检索默认条数（调用方一般显式传 settings.rag_top_k，这里只是兜底）。
DEFAULT_TOP_K = 5

#: 混合检索稠密/稀疏两路权重（与 KS 检索节点 norm_score=True 的 WeightedRanker 对齐）。
_DENSE_WEIGHT = 0.5
_SPARSE_WEIGHT = 0.5


class DocumentStoreUnavailable(RuntimeError):
    """文档检索后端不可用（如 pgvector 后端但 DATABASE_URL 未配置）。

    调用方（rag_query 等）捕获后降级为**可读提示**——不是错误，不 500、
    不拖垮对话。与工厂返回 None（后端未配置）是同一降级语义的两个入口：
    None = 配置层面没得选；本异常 = 配置了但运行时不可用。
    """


@dataclass
class DocumentChunk:
    """待入库文档分块（与宿主侧 ``agent_server.rag.chunker.Chunk`` 结构兼容）。"""

    text: str
    heading: str = ""


@runtime_checkable
class DocumentStore(Protocol):
    """文档向量检索后端契约：add_documents / retrieve / delete_document 三件套。

    返回/入参约定：
    - ``add_document`` 返回 doc_id（后端自生成）；
    - ``delete_document`` 返回删除条数（按 doc_id 对称删除）；
    - ``retrieve`` 返回 ``[{id, source, heading, content, score}]``，按相关性降序。
    """

    async def add_document(
        self,
        pool: object,
        source: str,
        chunks: list[DocumentChunk],
        workspace_id: str = "default",
        *,
        tenant_id: str,
        knowledge_id: str = "",
    ) -> str:
        """文档入库：向量化后批量写入；返回 doc_id。"""
        ...

    async def delete_document(
        self, pool: object, doc_id: str, workspace_id: str = "default", *, tenant_id: str
    ) -> int:
        """删除文档及其所有分块（与 add_document 对称）。返回删除条数。"""
        ...

    async def retrieve(
        self,
        pool: object,
        query: str,
        top_k: int | None = None,
        workspace_id: str = "default",
        *,
        tenant_id: str,
        knowledge_id: str = "",
    ) -> list[dict]:
        """混合检索：tenant 精确谓词（安全边界）+ workspace/knowledge 可选过滤。"""
        ...


# ==========================================================================
# Milvus 实现（默认后端）
# ==========================================================================
def _escape_milvus_string(value: str) -> str:
    """Milvus 过滤表达式字符串转义（与 KS escape_milvus_string_utils 同语义）。

    为什么用「转义」而不是内核记忆后端的「拒绝」语义：本集合由 KS 管线**原样**
    写入标量值（item_name/knowledge_id 等不含转义），过滤侧转义后仍可与字面值
    匹配（KS 生产在用）；内核 MilvusMemoryBackend 的拒绝语义是与其自身写入侧
    （写入前先转义）配套的，两套集合语义不同，不可混用。
    """
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return s.replace("\r", " ").replace("\n", " ").replace("\t", " ")


class MilvusDocumentStore:
    """Milvus 文档检索后端（dense COSINE + sparse IP + WeightedRanker 混合）。

    与 KS 上传管线共用同一 Milvus 实例与集合：上传（KS /upload 管线）与对话检索
    （本类）落同一处，`DOC_BACKEND=milvus` 时由 ``create_document_store`` 工厂装配。

    embedder：内核 ``EmbeddingProvider`` 形状（.dim / .embed / 可选 .aembed）。
    **必须与写该集合的模型一致**（KS 默认 bge-m3=1024 维）——跨模型向量不可比，
    维度不符时检索侧报错降级，不会静默混用。
    """

    def __init__(
        self,
        uri: str,
        collection: str = DEFAULT_DOC_COLLECTION,
        embedder: Any | None = None,
        token: str = "",
        rerank_fn: Any | None = None,
    ) -> None:
        if not uri:
            raise ValueError("MilvusDocumentStore 需要 uri（DOC_MILVUS_URI）")
        self._uri = uri
        self._token = token or ""
        self._collection = collection
        self._embedder = embedder
        self._rerank_fn = rerank_fn
        self._client: Any = None
        self._connected = False
        logger.info(
            "MilvusDocumentStore 已配置集合 %s (dim=%s, uri=%s)",
            collection, getattr(embedder, "dim", "?"), uri,
        )

    # ---- 连接与集合 ----
    def _connect(self) -> Any:
        """懒连接（同步；调用方负责放入 executor）。pymilvus 缺包时此处抛明确 ImportError。"""
        if self._connected and self._client is not None:
            return self._client
        from pymilvus import MilvusClient

        client = MilvusClient(uri=self._uri, token=self._token)
        if not client.has_collection(collection_name=self._collection):
            dim = self._require_embedder().dim
            self._create_collection(client, dim)
        self._client = client
        self._connected = True
        return client

    def _require_embedder(self) -> Any:
        if self._embedder is None:
            raise RuntimeError("MilvusDocumentStore 未配置 embedder（建集合/向量化需要）")
        return self._embedder

    def _create_collection(self, client: Any, dim: int) -> None:
        """建集合 + 索引：逐字段镜像 KS ``node_import_milvus.create_collection``（v2 增量：
        knowledge_id / workspace_id 两个标量字段）。两侧改动必须同步。"""
        from pymilvus import DataType

        schema = client.create_schema(auto_id=True, enable_dynamic_fields=True)
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="part", datatype=DataType.INT8)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="scope_type", datatype=DataType.VARCHAR, max_length=32)
        # v2 新增：多知识库过滤键（空 = 未分库，全库模式可召回、选库模式不召回）
        schema.add_field(field_name="knowledge_id", datatype=DataType.VARCHAR, max_length=256)
        # v2 新增：归属维（与 pgvector 侧 ADR-0006 T9 成对谓词同语义；KS 管线缺省 default）
        schema.add_field(field_name="workspace_id", datatype=DataType.VARCHAR, max_length=128)
        # v3 软删除（与 KS node_import_milvus.create_collection 镜像）
        schema.add_field(field_name="status", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="embedding_model", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="chunk_version", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="created_at", datatype=DataType.INT64)
        schema.add_field(field_name="source_doc", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=dim)

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_vector_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "normalize": True, "quantization": "none"},
        )
        client.create_collection(collection_name=self._collection, schema=schema, index_params=index_params)
        logger.info("Milvus 文档集合已创建：%s (dim=%s)", self._collection, dim)

    # ---- 过滤表达式 ----
    @staticmethod
    def _build_filter(tenant_id: str, workspace_id: str, knowledge_id: str) -> str:
        """标量过滤：tenant_id 严格谓词（安全边界）+ workspace/knowledge 可选。

        knowledge_id 为空 ⇒ 不加该子句（全库模式；老数据未分库也可召回）。
        v3 起所有检索都带 status != REVOKED（软删除；老数据 status 空仍可召回）。
        """
        expr = 'status != "REVOKED"'
        expr += f' and tenant_id == "{_escape_milvus_string(tenant_id)}"'
        if workspace_id:
            expr += f' and workspace_id == "{_escape_milvus_string(workspace_id)}"'
        if knowledge_id:
            expr += f' and knowledge_id == "{_escape_milvus_string(knowledge_id)}"'
        return expr

    # ---- embedding ----
    async def _aembed(self, texts: list[str]) -> list[list[float]]:
        """异步批量 embedding：统一 aembed / 同步 embed 分支（与内核 embed_one 同形）。"""
        embedder = self._require_embedder()
        if hasattr(embedder, "aembed"):
            return await embedder.aembed(texts)
        return await asyncio.to_thread(embedder.embed, texts)

    # ---- 协议实现 ----
    async def add_document(
        self,
        pool: object,
        source: str,
        chunks: list[DocumentChunk],
        workspace_id: str = "default",
        *,
        tenant_id: str,
        knowledge_id: str = "",
    ) -> str:
        """文档入库（平台侧直写；常规上传走 KS /upload 管线落同一集合）。

        doc_id 平台自生成，作为动态字段随行写入（集合 schema 未声明该字段，
        enable_dynamic_fields=True 使 KS 写入的行可缺省它），保证 delete_document
        与 pgvector 后端对称可用。
        """
        del pool  # Milvus 后端不使用 pg 连接池（协议占位参数）
        tenant = resolve_tenant(tenant_id)
        doc_id = uuid.uuid4().hex[:12]
        if not chunks:
            return doc_id
        embedder = self._require_embedder()
        texts = [c.text for c in chunks]
        dense = await self._aembed(texts)
        from agent_runtime.vector_sparse import build_sparse_vectors

        sparse = build_sparse_vectors(texts)
        now = int(time.time())
        rows = [
            {
                "content": c.text,
                "title": c.heading or "",
                "parent_title": "",
                "part": i % 128,  # INT8 上限；仅序号展示用，不参与过滤
                "file_title": source or "",
                "item_name": "",
                "tenant_id": tenant,
                "scope_type": "PRIVATE",
                "knowledge_id": knowledge_id or "",
                "workspace_id": workspace_id or "default",
                "status": "active",  # v3 软删除：新写入即有效；REVOKED 由 P3 删除端点产出
                "embedding_model": getattr(embedder, "model_name", "") or "",
                "chunk_version": "v1-title-aware",
                "created_at": now,
                "source_doc": source or "",
                "sparse_vector": sp,
                "dense_vector": vec,
                "doc_id": doc_id,  # 动态字段
            }
            for i, (c, vec, sp) in enumerate(zip(chunks, dense, sparse))
        ]
        client = await asyncio.to_thread(self._connect)
        await asyncio.to_thread(client.insert, collection_name=self._collection, data=rows)
        return doc_id

    async def delete_document(
        self, pool: object, doc_id: str, workspace_id: str = "default", *, tenant_id: str
    ) -> int:
        """按 doc_id（动态字段）+ tenant 删除；返回删除条数（Milvus delete 无计数，语义近似）。"""
        del pool
        tenant = resolve_tenant(tenant_id)
        client = await asyncio.to_thread(self._connect)
        expr = (
            f"{self._build_filter(tenant, workspace_id, '')} "
            f'and doc_id == "{_escape_milvus_string(doc_id)}"'
        )
        await asyncio.to_thread(client.delete, collection_name=self._collection, filter=expr)
        return 1  # Milvus delete 不回条数；调用方按"已提交删除"计（幂等）

    async def retrieve(
        self,
        pool: object,
        query: str,
        top_k: int | None = None,
        workspace_id: str = "default",
        *,
        tenant_id: str,
        knowledge_id: str = "",
    ) -> list[dict]:
        """混合检索：dense(COSINE) + sparse(IP) 双路 + WeightedRanker 加权融合。

        返回 [{id, source, heading, content, score}]（与 pgvector 后端同形状），
        按融合相关性降序；rerank_fn 注入时对融合候选做相关性重排。
        """
        del pool
        if not query:
            return []
        tenant = resolve_tenant(tenant_id)
        k = int(top_k or DEFAULT_TOP_K)
        vec = await self._aembed([query])
        from agent_runtime.vector_sparse import build_sparse_vector

        sparse_vec = build_sparse_vector(query)
        client = await asyncio.to_thread(self._connect)
        expr = self._build_filter(tenant, workspace_id or "default", knowledge_id)

        def _search() -> list[dict]:
            from pymilvus import AnnSearchRequest, WeightedRanker

            dense_req = AnnSearchRequest(
                data=[vec[0]], anns_field="dense_vector",
                param={"metric_type": "COSINE"}, expr=expr, limit=k,
            )
            sparse_req = AnnSearchRequest(
                data=[sparse_vec], anns_field="sparse_vector",
                param={"metric_type": "IP"}, expr=expr, limit=k,
            )
            res = client.hybrid_search(
                collection_name=self._collection,
                reqs=[dense_req, sparse_req],
                ranker=WeightedRanker(_DENSE_WEIGHT, _SPARSE_WEIGHT, norm_score=True),
                limit=k,
                output_fields=["chunk_id", "content", "title", "parent_title", "source_doc", "file_title"],
            )
            hits = res[0] if res else []
            return [
                {
                    "id": hit.get("id"),
                    "source": (hit.get("entity") or {}).get("source_doc")
                    or (hit.get("entity") or {}).get("file_title") or "",
                    "heading": (hit.get("entity") or {}).get("title") or "",
                    "content": (hit.get("entity") or {}).get("content") or "",
                    "score": round(float(hit.get("distance") or 0.0), 6),
                }
                for hit in hits
            ]

        candidates = await asyncio.to_thread(_search)
        if not candidates:
            return []
        if self._rerank_fn is not None:
            try:
                scores = await asyncio.to_thread(
                    self._rerank_fn, query, [c["content"] for c in candidates]
                )
                ordered = sorted(
                    zip(candidates, scores), key=lambda x: x[1], reverse=True
                )[:k]
                return [
                    {**c, "score": round(float(sc), 6)} for c, sc in ordered
                ]
            except Exception as e:  # noqa: BLE001 — rerank 失败回退融合序（与 pgvector 后端同口径）
                logger.warning("Milvus 文档检索 rerank 失败，回退融合序: %s", e)
        return candidates


__all__ = [
    "DocumentChunk",
    "DocumentStore",
    "DocumentStoreUnavailable",
    "MilvusDocumentStore",
    "DEFAULT_DOC_COLLECTION",
    "DEFAULT_TOP_K",
]
