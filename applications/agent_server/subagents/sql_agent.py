"""SQL 子能力：改调 nl2sql-service（A 方案 Stage ③，agent_server/sql 已退役）。

此前本模块封装 agent_server 自有的 Vanna 式管线（`sql/pipeline.py` +
`schema_store` 训练三件套）；该路已退役（ADR-0011 选项 A：收敛到 nl2sql-service
的 14 节点图——取值核验 / 多轮继承 / 查询追溯都是旧路没有的）。本模块现在是
**瘦客户端**：POST `/api/query`，把响应格式化成图节点可用的证据文本。

降级契约（同 `subagents/search.py`）：`NL2SQL_SERVICE_URL` 未配置时返回明确
提示而非静默空结果——调用方（Planner）要能区分"没配服务"与"查了没有"。

身份：tenant 取服务端上下文（同 rag，不收客户端表单值——ADR-0007），作为
请求体字段透传；nl2sql 侧有自己的服务端断言优先级（断言 > 请求体 > default），
部署了内部签名头时以断言为准。
"""

from agent_core.memory._tenant_gate import _TENANT_UNSET
from agent_runtime.workspace_registry import server_tenant_id

from agent_server.config import get_settings

#: 与 capabilities.py 注册该 skill 时的 timeout_ms 对齐（问数含 LLM 生成 + 执行）
_TIMEOUT_S = 30.0


def format_nl2sql_evidence(data: dict) -> str:
    """nl2sql `/api/query` 响应 → 证据文本（SQL + 答案；失败带分类错误）。

    零结果分诊理由（P0-8③）一并带出：调用方要能区分"真没数据"与"字面量没识别
    所以没查到"——后者重述问题可能就成了，前者才是真答案。
    """
    if data.get("error"):
        return f"问数失败：{data['error']}"
    parts: list[str] = []
    sql = data.get("sql")
    if sql:
        parts.append(f"执行的 SQL：{sql}")
    parts.append(data.get("answer") or "（无答案）")
    reason = data.get("empty_result_reason")
    if reason:
        parts.append(f"（零结果原因：{reason}）")
    return "\n".join(parts)


async def sql_query(
    query: str, llm=None, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> list[str]:
    """问数证据生产（图节点调用）。llm 参数保留兼容调用方签名——LLM 现由
    nl2sql-service 持有（OPENCODE_GATEWAY 等），本服务不再自带生成模型。"""
    import httpx

    settings = get_settings()
    url = settings.nl2sql_service_url
    if not url:
        return ["问数服务未配置（NL2SQL_SERVICE_URL 为空）"]

    if tenant_id is _TENANT_UNSET:
        tenant_id = server_tenant_id(settings.default_tenant_id)
    payload: dict = {"query": query, "tenant_id": tenant_id}
    if workspace_id:
        payload["workspace_id"] = workspace_id

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(f"{url}/api/query", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [f"问数服务错误：HTTP {exc.response.status_code}"]
    except httpx.HTTPError as exc:
        return [f"问数服务不可达（{type(exc).__name__}）：{url}"]
    return [format_nl2sql_evidence(data)]
