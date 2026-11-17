# -*- coding: utf-8 -*-
"""文档检索后端工厂：``DOC_BACKEND`` 开关（milvus | pgvector）→ ``DocumentStore``。

形状照 ``agent_core.memory.vector_backend.create_memory_backend``（MEMORY 后端的
既有模式）：协议在共享层、实现在各自层、配置依赖倒置——本工厂读 app 的 Settings，
把连接参数/embedder 注入实现（agent-runtime 不依赖 app.config，红线 1）。

关键不变量（本方案的根因修复点）：**上传写哪个后端，对话检索就查哪个后端**——
``/kb/uploads`` 与 ``rag_query`` 都经 ``get_document_store()`` 取同一份
``DOC_BACKEND`` 配置，保证两侧永远落到同一个后端实例。

本模块是「协议 → 具体实现」的唯一装配点：消费方（subagents/rag.py 等）只 import
本工厂与协议类型，不 import 任何具体后端（后端可切换的前提是依赖指向接口）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger
from agent_runtime.document_store import DocumentStore, MilvusDocumentStore

from agent_server.config import get_settings
from agent_server.rag.embed import resolve_provider
from agent_server.rag.pg_backend import PgVectorDocumentStore

logger = get_logger(__name__)

__all__ = ["create_document_store", "get_document_store"]


def _build_doc_embedder() -> Any:
    """构造文档集合的 embedding 提供方。

    优先 ``DOC_EMBED_*`` 专用配置（须与写该集合的模型一致，默认 bge-m3=1024 维）；
    未配置则回退 app 主 embedder——此时部署侧必须保证 EMBEDDING_* 与集合写入模型
    对齐（跨模型向量不可比，维度不符检索即失败降级，可发现、不静默混用）。
    """
    from agent_core.memory.embedder import RemoteEmbedder

    s = get_settings()
    if s.doc_embed_api_key:
        return RemoteEmbedder(
            api_key=s.doc_embed_api_key,
            base_url=s.doc_embed_base_url or "https://api.siliconflow.cn/v1",
            model=s.doc_embed_model or "BAAI/bge-m3",
            dim=s.doc_embed_dim or None,
        )
    provider = resolve_provider()
    if provider.dim != (s.doc_embed_dim or 1024):
        logger.warning(
            "DOC_BACKEND=milvus 主 embedder dim=%s 与文档集合预期 dim=%s 不一致，"
            "检索将失败降级；请配置 DOC_EMBED_* 或对齐 EMBEDDING_*",
            provider.dim, s.doc_embed_dim or 1024,
        )
    return provider


def _build_rerank_fn() -> Any | None:
    """rerank 注入（与 pgvector 后端同口径：rerank_enabled + key 才启用）。"""
    from agent_server.rag.rerank import get_reranker

    reranker = get_reranker()
    if reranker is None:
        return None

    def _rerank(query: str, texts: list[str]) -> list[float]:
        return reranker.compute_score([[query, t] for t in texts])

    return _rerank


def create_document_store(mode: str) -> DocumentStore | None:
    """按 mode 创建文档检索后端。

    - ``"milvus"`` → ``MilvusDocumentStore``（默认；``DOC_MILVUS_URI`` 未配置时返回
      None，由调用方降级为可读提示——不抛、不 500，Milvus 不可达不拖垮对话）；
    - ``"pgvector"`` → ``PgVectorDocumentStore``（降级/自启备选）；
    - 其他值 → ValueError（配置写错当场暴露，不静默回落）。
    """
    s = get_settings()
    if mode == "milvus":
        if not s.doc_milvus_uri:
            logger.warning("DOC_BACKEND=milvus 但 DOC_MILVUS_URI 未配置，文档检索不可用")
            return None
        return MilvusDocumentStore(
            uri=s.doc_milvus_uri,
            collection=s.doc_milvus_collection,
            embedder=_build_doc_embedder(),
            token=s.doc_milvus_token,
            rerank_fn=_build_rerank_fn(),
        )
    if mode == "pgvector":
        return PgVectorDocumentStore()
    raise ValueError(f"未知 DOC_BACKEND: {mode}")


def get_document_store() -> DocumentStore | None:
    """读取 ``DOC_BACKEND`` 配置返回后端实例（每次调用现取配置，测试可即时切换）。

    返回 None = 后端未配置（调用方给可读降级提示，不算错误）。
    """
    return create_document_store(get_settings().doc_backend)
