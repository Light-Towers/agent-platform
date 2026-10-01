"""SQL 子能力：Vanna 式管线封装为图节点可调用的证据生产者。"""

from agent_core.memory._tenant_gate import _TENANT_UNSET
from agent_runtime.workspace_registry import server_tenant_id

from agent_server.config import get_settings
from agent_server.sql.pipeline import format_result, text_to_sql


async def sql_query(
    query: str, llm=None, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> list[str]:
    from agent_runtime.db import get_pool

    # tenant 取服务端上下文（同 rag，不收客户端表单值）。
    if tenant_id is _TENANT_UNSET:
        tenant_id = server_tenant_id(get_settings().default_tenant_id)
    payload = await text_to_sql(
        get_pool(), query, llm=llm, workspace_id=workspace_id, tenant_id=tenant_id
    )
    return [format_result(payload)]
