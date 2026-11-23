"""RAG 子能力：经 ``DocumentStore`` 协议的混合检索证据收集。

依赖指向接口（步骤 2 根因修复点）：本模块只 import 协议、工厂与降级常量，
**不 import 任何具体后端**（pgvector/Milvus 的可切换性取决于此）。用哪个后端由
``DOC_BACKEND`` 配置经 ``agent_server.rag.backend.get_document_store`` 决定。
"""

from agent_core.logging import get_logger
from agent_core.memory._tenant_gate import _TENANT_UNSET
from agent_runtime.db import get_pool
from agent_runtime.document_store import DocumentStoreUnavailable
from agent_runtime.workspace_registry import server_tenant_id

from agent_server.config import get_settings
from agent_server.evidence_sink import current_sink
from agent_server.rag.backend import get_document_store
from agent_server.subagents.degradation import (
    KNOWLEDGE_DISABLED,
    KNOWLEDGE_NO_HIT,
    KNOWLEDGE_UNAVAILABLE,
)

logger = get_logger(__name__)


async def rag_query(
    query: str,
    workspace_id: str = "default",
    knowledge_id: str = "",
    *,
    tenant_id: str = _TENANT_UNSET,
) -> list[str]:
    """文档检索证据收集（后端可切换：milvus | pgvector）。

    ``knowledge_id``：可选知识库过滤（对话区"知识范围"选择器透传），空 = 全部知识库。

    降级链（可读、不 500、不拖垮对话）：
    - 后端未配置（DOC_BACKEND=milvus 但 DOC_MILVUS_URI 空，工厂返回 None）
      → ``KNOWLEDGE_DISABLED``；
    - 后端运行时不可用（pgvector 且 DATABASE_URL 未配置）→ ``KNOWLEDGE_DISABLED``；
    - 检索零结果 → ``KNOWLEDGE_NO_HIT``；
    - 后端异常（Milvus 不可达等）→ ``KNOWLEDGE_UNAVAILABLE``（服务失败口径，
      不计空证据，与「问数服务不可达」先例一致）。
    """
    store = get_document_store()
    if store is None:
        return [f"{KNOWLEDGE_DISABLED}（文档检索后端 DOC_BACKEND 未配置）"]
    pool = get_pool()
    # tenant 取服务端上下文（ADR-0006 T9：不收客户端表单值）：显式传入优先，
    # 否则回退部署级 DEFAULT_TENANT_ID（单租户）；无论哪条路径都是具体租户。
    if tenant_id is _TENANT_UNSET:
        tenant_id = server_tenant_id(get_settings().default_tenant_id)
    try:
        chunks = await store.retrieve(
            pool, query, get_settings().rag_top_k, workspace_id,
            tenant_id=tenant_id, knowledge_id=knowledge_id,
        )
    except DocumentStoreUnavailable as e:
        logger.warning("文档检索后端不可用: %s", e)
        return [f"{KNOWLEDGE_DISABLED}（{e}）"]
    except Exception as e:  # noqa: BLE001 — 后端故障降级为可读提示，不拖垮对话
        logger.error("文档检索失败: %s", e)
        return [f"{KNOWLEDGE_UNAVAILABLE}：{e}"]
    if not chunks:
        return [f"{KNOWLEDGE_NO_HIT}相关内容"]
    # 富回答旁路：在拍平成 list[str] 之前把结构化 chunks 存入请求级 sink，
    # 供 SSE 出口的 rich adapter 构造 citations/images（plan-image-citation-e2e §2.2）。
    # 降级路径（上方 return）不写池——避免把"无命中"提示当证据。
    sink = current_sink()
    if sink is not None:
        sink.rag_chunks.extend(chunks)
    return [
        f"[来源: {c['source']} / {c['heading'] or '无标题'}] {c['content']}" for c in chunks
    ]
