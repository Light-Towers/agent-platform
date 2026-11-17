# -*- coding: utf-8 -*-
"""PgVector 文档检索后端：``DocumentStore`` 协议的降级/自举实现。

包装 ``agent_server.rag.store`` 的既有模块函数（add_document / retrieve_chunks /
delete_document），**复用其全部逻辑、不改检索行为**——pgvector + BM25 + RRF + 可选
rerank 的链路原样保留，只把「函数调用」升级为「可切换后端」。

隔离契约不变（ADR-0006 T9）：``tenant_id`` 安全边界（服务端上下文，漏传经
``resolve_tenant`` fail-fast）；``workspace_id`` 归属维，读写谓词成对出现。
``knowledge_id`` 为可选知识库过滤：空 = 召回租户全部库（多库默认全库）。
"""

from __future__ import annotations

from agent_runtime.document_store import DocumentChunk, DocumentStoreUnavailable

from agent_server.rag import store


class PgVectorDocumentStore:
    """pgvector 文档检索后端（pgvector + BM25 + RRF，与 Milvus 后端同一协议）。"""

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
        if pool is None:
            raise DocumentStoreUnavailable("DATABASE_URL 未配置")
        # store.add_document 只读 chunk.text，DocumentChunk（text/heading）与其
        # chunker.Chunk 结构兼容，直接透传不做拷贝。
        return await store.add_document(
            pool, source, chunks, workspace_id, tenant_id=tenant_id, knowledge_id=knowledge_id
        )

    async def delete_document(
        self, pool: object, doc_id: str, workspace_id: str = "default", *, tenant_id: str
    ) -> int:
        return await store.delete_document(pool, doc_id, workspace_id, tenant_id=tenant_id)

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
        # pool 为 None（内存模式）≠ 空结果：后端没有可用存储，抛不可用信号由
        # 调用方降级为「知识库未启用」（原 rag_query 前置检查的语义原样搬进来）。
        if pool is None:
            raise DocumentStoreUnavailable("DATABASE_URL 未配置")
        return await retrieve_chunks_scoped(
            pool, query, top_k, workspace_id, tenant_id=tenant_id, knowledge_id=knowledge_id
        )


async def retrieve_chunks_scoped(
    pool: object,
    query: str,
    top_k: int | None,
    workspace_id: str,
    *,
    tenant_id: str,
    knowledge_id: str = "",
) -> list[dict]:
    """retrieve_chunks 的薄转发（独立函数便于测试 monkeypatch，不藏第二套逻辑）。"""
    return await store.retrieve_chunks(
        pool, query, top_k, workspace_id, tenant_id=tenant_id, knowledge_id=knowledge_id
    )


__all__ = ["PgVectorDocumentStore", "retrieve_chunks_scoped"]
