"""能力层身份注入回归（ADR-0007 §4.3）。

`_sanitize_identity` 与 `general_qa` 是「模型可填参数 → 身份边界」的两道口。
本文件钉住三条不变量：

1. kwargs 里的 ``tenant_id`` / ``user_id`` / ``api_key`` 一律剔除；
2. 租户取服务端断言 ContextVar，未绑定才回落部署级 default；
3. ``general_qa`` 的图状态优先使用服务端断言 user，LLM/kwargs 不得覆盖。
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.workspace_registry import (
    bind_tenant_context,
    bind_user_context,
    reset_tenant_context,
    reset_user_context,
)
from agent_server import capabilities
from agent_server.capabilities import (
    _GENERAL_QA_INPUT_SCHEMA,
    _run_general_qa,
    _sanitize_identity,
)


def _settings(default_tenant_id: str = "deploy-default") -> SimpleNamespace:
    return SimpleNamespace(default_tenant_id=default_tenant_id)


def test_sanitize_identity_strips_llm_identity_and_uses_asserted_tenant(monkeypatch):
    monkeypatch.setattr(capabilities, "get_settings", lambda: _settings())
    token = bind_tenant_context("tenant-asserted")
    try:
        out = _sanitize_identity(
            {
                "query": "q",
                "workspace_id": "w",
                "tenant_id": "tenant-from-prompt",
                "user_id": "user-from-prompt",
                "api_key": "sk-leak",
            }
        )
    finally:
        reset_tenant_context(token)

    assert out == {"query": "q", "workspace_id": "w", "tenant_id": "tenant-asserted"}


def test_sanitize_identity_falls_back_to_deploy_default(monkeypatch):
    monkeypatch.setattr(capabilities, "get_settings", lambda: _settings("deploy-default"))
    out = _sanitize_identity({"query": "q", "tenant_id": "tenant-from-prompt"})
    assert out["tenant_id"] == "deploy-default"


def test_general_qa_schema_does_not_expose_identity_fields():
    props = _GENERAL_QA_INPUT_SCHEMA["properties"]
    assert "tenant_id" not in props
    assert "user_id" not in props
    assert "api_key" not in props


class _CapturingGraph:
    def __init__(self):
        self.states = []
        self.configs = []

    async def astream(self, state, config, stream_mode):
        self.states.append(state)
        self.configs.append(config)
        yield {"synthesize": {"answer": "ok"}}


async def test_general_qa_uses_asserted_user_not_kwargs(monkeypatch):
    monkeypatch.setattr(capabilities, "get_settings", lambda: _settings())
    graph = _CapturingGraph()
    tenant_token = bind_tenant_context("tenant-asserted")
    user_token = bind_user_context("user-asserted")
    try:
        answer = await _run_general_qa(
            graph,
            question="hello",
            workspace_id="w",
            user_id="user-from-prompt",
            tenant_id="tenant-from-prompt",
            thread_id="t-1",
        )
    finally:
        reset_user_context(user_token)
        reset_tenant_context(tenant_token)

    assert answer == "ok"
    assert graph.states[0]["tenant_id"] == "tenant-asserted"
    assert graph.states[0]["user_id"] == "user-asserted"
    assert graph.states[0]["workspace_id"] == "w"
    assert graph.states[0]["question"] == "hello"
    assert graph.configs[0] == {"configurable": {"thread_id": "t-1"}}


async def test_general_qa_keeps_explicit_user_when_not_asserted(monkeypatch):
    monkeypatch.setattr(capabilities, "get_settings", lambda: _settings())
    graph = _CapturingGraph()
    await _run_general_qa(graph, question="hello", user_id="observer")
    assert graph.states[0]["user_id"] == "observer"
