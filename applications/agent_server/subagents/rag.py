"""RAG 子能力：混合检索证据收集。"""

from agent_core.memory._tenant_gate import _TENANT_UNSET
from agent_runtime.db import get_pool
from agent_runtime.workspace_registry import server_tenant_id

from agent_server.config import get_settings
from agent_server.rag.store import retrieve_chunks


async def rag_query(
    query: str, workspace_id: str = "default", *, tenant_id: str = _TENANT_UNSET,
) -> list[str]:
    pool = get_pool()
    if pool is None:
        return ["知识库未启用（DATABASE_URL 未配置）"]
    # tenant 取服务端上下文（ADR-0006 T9：不收客户端表单值）：显式传入优先，
    # 否则回退部署级 DEFAULT_TENANT_ID（单租户）；无论哪条路径都是具体租户。
    if tenant_id is _TENANT_UNSET:
        tenant_id = server_tenant_id(get_settings().default_tenant_id)
    chunks = await retrieve_chunks(
        pool, query, get_settings().rag_top_k, workspace_id, tenant_id=tenant_id
    )
    if not chunks:
        return ["知识库中未检索到相关内容"]
    return [
        f"[来源: {c['source']} / {c['heading'] or '无标题'}] {c['content']}" for c in chunks
    ]
