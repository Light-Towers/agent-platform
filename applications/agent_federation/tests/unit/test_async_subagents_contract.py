"""E-1 联邦契约对齐单测（优化 E / P4.1 / S-1）。

覆盖 `_HttpSubAgent.ainvoke` 在 E1_CONTRACT_ASSERT 开关 on/off 下的：
  - 合法 QueryResponse(dict) 通过校验并规整；
  - 非法 dict 抛 ValueError；
  - 旧 adapter list 路径；
  - 开关 off 时回退到原规整（不抛错）。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_agent_federation_root = str(Path(__file__).resolve().parents[2])
if _agent_federation_root not in sys.path:
    sys.path.insert(0, _agent_federation_root)

from agent.async_subagents import _HttpSubAgent  # noqa: E402


class _FakeSvc:
    name = "test-svc"
    graph_id = "test"
    url = "http://localhost:9999"
    endpoint = "/api/query"


def _make_agent(monkeypatch, json_data):
    """构造 _HttpSubAgent，并将其 ainvoke 内的 httpx 调用替换为返回 json_data 的 mock。"""

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)

    monkeypatch.setattr("agent.async_subagents.httpx.AsyncClient", lambda *a, **kw: client)
    return _HttpSubAgent(_FakeSvc(), "desc")


async def test_contract_pass_query_response(monkeypatch):
    agent = _make_agent(monkeypatch, {"answer": "ok", "fallback": False})
    out = await agent.ainvoke({"query": "hi"})
    assert out["answer"] == "ok"


async def test_contract_pass_sql_query_response(monkeypatch):
    # wenda 返回 SqlQueryResponse（QueryResponse 子类，含 sql/error 超集字段）
    agent = _make_agent(monkeypatch, {"answer": "a", "sql": "SELECT 1", "error": None})
    out = await agent.ainvoke({"query": "q"})
    assert out["answer"] == "a"
    assert out["sql"] == "SELECT 1"


async def test_contract_fail_invalid_dict(monkeypatch):
    # QueryResponse 要求 answer 为 str，传 int 应校验失败
    agent = _make_agent(monkeypatch, {"answer": 123})
    with pytest.raises(ValueError, match="不符合 shared_schemas.QueryResponse 契约"):
        await agent.ainvoke({"query": "q"})


async def test_legacy_list_path(monkeypatch):
    agent = _make_agent(monkeypatch, [{"text": "a"}, {"text": "b"}])
    out = await agent.ainvoke({"query": "q"})
    assert out["answer"] == "a b"


async def test_switch_off_falls_back(monkeypatch):
    monkeypatch.setattr("agent.async_subagents._E1_CONTRACT_ASSERT", False)
    # 非法 dict 在开关 off 时不抛错，按原规整返回
    agent = _make_agent(monkeypatch, {"answer": 123})
    out = await agent.ainvoke({"query": "q"})
    assert out["answer"] == 123


# --- TB-6：kefu 返回符合性逐项核验（消费侧双向契约） ---


async def test_kefu_real_fields_extracted(monkeypatch):
    """kefu /invoke 真实返回的 QueryResponse 字段应被消费侧完整提取。"""
    kefu_response = {
        "answer": "您的订单已发货",
        "data": {"content": {"intent": "logistics"}, "source": "kefu-service", "metadata": {}},
        "trace_id": "trace-abc",
        "latency_ms": 12.5,
        "intent": "logistics",
        "fallback": False,
    }
    agent = _make_agent(monkeypatch, kefu_response)
    out = await agent.ainvoke({"query": "订单到哪了"})
    # 形状断言通过 + 字段透传
    assert out["answer"] == "您的订单已发货"
    assert out["trace_id"] == "trace-abc"
    assert out["latency_ms"] == 12.5
    assert out["intent"] == "logistics"
    assert out["data"]["content"]["intent"] == "logistics"


async def test_content_assert_warns_on_empty_answer(monkeypatch, caplog):
    """TB-6 盲区：answer 为空属形状合法但内容空洞，内容断言应告警（不抛错）。"""
    import logging

    agent = _make_agent(monkeypatch, {"answer": "", "fallback": False})
    with caplog.at_level(logging.WARNING, logger="agent.async_subagents"):
        out = await agent.ainvoke({"query": "q"})
    assert out["answer"] == ""
    assert any("answer 为空" in r.message for r in caplog.records)


async def test_content_assert_switch_off(monkeypatch, caplog):
    """E1_CONTENT_ASSERT=off 时，空 answer 不告警（可独立回滚）。"""
    import logging

    monkeypatch.setattr("agent.async_subagents._E1_CONTENT_ASSERT", False)
    agent = _make_agent(monkeypatch, {"answer": ""})
    with caplog.at_level(logging.WARNING, logger="agent.async_subagents"):
        out = await agent.ainvoke({"query": "q"})
    assert out["answer"] == ""
    assert not any("answer 为空" in r.message for r in caplog.records)
