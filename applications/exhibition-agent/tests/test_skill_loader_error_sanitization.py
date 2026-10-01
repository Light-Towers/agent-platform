"""C 类堆栈回显收敛的行为回归（Batch 4）：skill_loader 的 5xx 出口与工具 502。

覆盖 4 个曾经把异常原文写进对外响应体的站点：
- ``POST /api/chat`` 的兜底 500；
- ``POST /api/invoke`` 的 httpx 502；
- ``GET /api/health`` 的 warehouse 探活 502；
- ``ExhibitionAgent._execute_tool`` 的 502 body（经 ``/api/chat`` 的 tool_calls 轨迹回传客户端）。

断言两面：① 对外文案 = kernel 固定文案；② 异常消息里的内部主机/路径不得出现在响应体。
直接调用 handler（不建 TestClient），与本仓其余测试一致，避开 lifespan/中间件装配。
"""

from __future__ import annotations

import json

import httpx
import pytest
from agent_core.guardrails.errors import SANITIZED_5XX_MSG

from exhibition_agent.skill_loader import agent as agent_module
from exhibition_agent.skill_loader import app as app_module
from exhibition_agent.skill_loader.agent import ExhibitionAgent
from exhibition_agent.skill_loader.parser import Endpoint

# 异常消息里的敏感内容：内网主机 + 内部路径（历史实现会原样回显给客户端）
SECRET = "connection refused host=10.0.0.1 file=/opt/secrets/db.yaml"

WAREHOUSE_URL = "http://warehouse.internal:8000"


class _RaisingAgent:
    """agent.chat 抛异常，模拟 LLM/tool 链路内部故障。"""

    async def chat(self, messages: list[dict]) -> dict:
        raise ValueError(SECRET)


class _FakeLLM:
    configured = True

    def config_info(self) -> dict:
        return {"configured": True, "model": "gpt-test", "base_url": "https://llm.test", "api_key_set": False}


class _FailingClient:
    """httpx.AsyncClient 替身：任何请求都抛 RequestError（消息含敏感内容）。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __call__(self, *args, **kwargs) -> "_FailingClient":
        return self

    async def __aenter__(self) -> "_FailingClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url, **kwargs):
        raise self._exc

    async def post(self, url, **kwargs):
        raise self._exc

    async def delete(self, url, **kwargs):
        raise self._exc


@pytest.fixture(autouse=True)
def _isolate_skill_loader_state():
    """skill_loader 用模块级全局缓存 agent/llm，测试后必须复位，避免污染同 session。"""
    yield
    app_module._agent = None
    app_module._llm = None


@pytest.fixture
def fail_httpx(monkeypatch):
    def _install(exc: Exception) -> None:
        monkeypatch.setattr(app_module.httpx, "AsyncClient", _FailingClient(exc))
        monkeypatch.setattr(agent_module.httpx, "AsyncClient", _FailingClient(exc))

    return _install


async def test_chat_500_returns_fixed_text_without_exception_message():
    app_module._agent = _RaisingAgent()
    app_module._llm = _FakeLLM()

    resp = await app_module.chat(app_module.ChatRequest(messages=[{"role": "user", "content": "查一下场馆"}]))
    body = resp.body.decode("utf-8")

    assert resp.status_code == 500
    assert json.loads(body)["error"] == SANITIZED_5XX_MSG
    # 诊断信息仍可用，但只有不含密钥的配置摘要
    assert json.loads(body)["llm_config"]["api_key_set"] is False
    assert SECRET not in body
    assert "10.0.0.1" not in body


async def test_invoke_502_keeps_url_but_masks_exception(fail_httpx):
    fail_httpx(httpx.ConnectError(SECRET))

    resp = await app_module.invoke(app_module.InvokeRequest(method="GET", path="/api/venue/list"))
    body = resp.body.decode("utf-8")
    payload = json.loads(body)

    assert resp.status_code == 502
    assert payload["error"] == "warehouse 服务不可达，请稍后重试"
    # url 是本地拼出的调用目标（/api/config 亦已暴露），保留供排障；异常消息不保留
    assert payload["url"].startswith(app_module.WAREHOUSE_BASE_URL)
    assert SECRET not in body


async def test_health_502_exposes_only_exception_class(fail_httpx):
    fail_httpx(httpx.ConnectError(SECRET))

    resp = await app_module.health()
    body = resp.body.decode("utf-8")
    payload = json.loads(body)

    assert resp.status_code == 502
    assert payload["status"] == "fail"
    assert payload["error"] == "warehouse 健康检查失败"
    assert payload["error_type"] == "ConnectError"
    assert SECRET not in body


async def test_agent_tool_error_body_is_masked(fail_httpx):
    """工具结果会同时喂给 LLM 与经 /api/chat 回传客户端，故也必须脱敏。"""
    fail_httpx(httpx.ConnectError(SECRET))
    endpoint = Endpoint(method="GET", path="/api/venue/list", group="查询域")
    agent_obj = ExhibitionAgent(WAREHOUSE_URL, _FakeLLM(), [endpoint])
    func_name = next(iter(agent_obj.func_name_to_endpoint))

    result = await agent_obj._execute_tool(func_name, {})
    dumped = json.dumps(result, ensure_ascii=False)

    assert result["status_code"] == 502
    assert result["body"]["error"] == "warehouse 服务不可达，请稍后重试"
    assert SECRET not in dumped
