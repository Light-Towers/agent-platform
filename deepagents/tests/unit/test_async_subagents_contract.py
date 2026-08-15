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

_deepagents_root = str(Path(__file__).resolve().parents[2])
if _deepagents_root not in sys.path:
    sys.path.insert(0, _deepagents_root)

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
