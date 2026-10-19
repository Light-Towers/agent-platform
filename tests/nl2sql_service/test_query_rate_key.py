"""限流键取服务端断言租户（#103）：客户端可控的请求体 tenant_id 不是隔离依据。

钉四件事：
1. 无断言 dev：换 body tenant_id 不换桶（均 "anon"）——修复前换串即换桶可单向绕限流；
2. 断言绑定：桶取断言租户，body tenant_id 对键零影响；
3. 部署级 default_tenant 在场：桶取 default，body 仍零影响（默认值也是服务端值）；
4. dev 行为逐位兼容：空作用域仍落 "anon"（既有 test_load_guard.py 的桶语义不变）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_runtime.workspace_registry import bind_tenant_context, reset_tenant_context
from nl2sql_service.services.query_service import QueryService


class _NullAsyncCtx:
    async def __aenter__(self) -> "_NullAsyncCtx":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _RecordingGuard:
    """只记录限流/并发键的假 LoadGuard（slot 用法与真 guard 一致）。"""

    def __init__(self) -> None:
        self.keys: list[str] = []

    def slot(self, key: str) -> _NullAsyncCtx:
        self.keys.append(key)
        return _NullAsyncCtx()


def _settings(default_tenant: str = "") -> MagicMock:
    s = MagicMock()
    s.default_tenant = default_tenant
    s.default_workspace = ""
    s.datasource_label = "dw"
    s.datasource_id = "dw"
    s.sql_max_rows = 100
    s.sql_max_correct_retries = 2
    s.retrieval_top_k = 10
    s.rrf_k = 60
    s.tokenizer = "bigram"
    s.retrieval_score_margin = 0.0
    s.sql_max_rows_for_prompt = 50
    s.sql_prompt_max_bytes = 10000
    s.allowed_tables = []
    s.sensitive_columns = []
    s.default_query_role = "analyst"
    s.result_masking_enabled = False
    s.mask_keep_chars = 1
    s.admin_roles = []
    s.date_context_note = ""
    return s


async def _run_query(guard: _RecordingGuard, default_tenant: str = "", **kwargs) -> str:
    ctx = MagicMock()
    ctx.datasources = None
    ctx.load_guard = guard
    ctx.table_stats = []
    graph = MagicMock()

    async def _ainvoke(state):
        return {"answer": "ok", "sql": "SELECT 1"}

    graph.ainvoke = _ainvoke
    svc = QueryService(graph=graph, context=ctx, llm=None)
    with patch("nl2sql_service.conf.settings.get_settings", return_value=_settings(default_tenant)):
        await svc.query("问题", **kwargs)
    return guard.keys[-1]


async def test_body_tenant_does_not_change_bucket():
    guard = _RecordingGuard()
    keys: list[str] = []
    for body_tenant in ("evil-a", "evil-b", "evil-c"):
        keys.append(await _run_query(guard, tenant_id=body_tenant))
    assert keys == ["anon", "anon", "anon"], "无断言时换 body tenant 不得换桶（修复前可单向绕限流）"


async def test_asserted_tenant_is_the_bucket():
    token = bind_tenant_context("t-asserted")
    try:
        guard = _RecordingGuard()
        key = await _run_query(guard, tenant_id="evil")
    finally:
        reset_tenant_context(token)
    assert key == "t-asserted", "桶取断言租户，body tenant_id 对键零影响"


async def test_deployment_default_is_the_bucket_not_body():
    guard = _RecordingGuard()
    key = await _run_query(guard, default_tenant="acme", tenant_id="evil")
    assert key == "acme", "部署级 default 也是服务端值；body 对键零影响"
