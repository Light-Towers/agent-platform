"""filter_table 白名单交集与开关用例（#109）。

_derive_tables 让本节点由空转变活后的三个风险在此钉死：① 每请求多一次 LLM
往返 ⇒ 开关默认关（不过滤、不调用）；② LLM 输出不可直信——只允许在派生清单内
收窄，清单外表名/字符串数组/非法 JSON/调用异常一律回落派生清单；③ llm_calls
计数只在确有一次有效收窄时递增（与旧代码成功分支形状一致）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from nl2sql_service.agent.nodes.filter_table import filter_table

_DERIVED = [{"table_name": "orders"}, {"table_name": "users"}]


class _FakeLLM:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.enabled = True
        self.calls = 0
        self._result = result
        self._exc = exc

    async def invoke(self, prompt: str) -> Any:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def _state(llm: Any, tables: list | None = None, enabled: bool = True, llm_calls: int = 0) -> dict:
    return {
        "effective_query": "上个月销售额",
        "tables": _DERIVED if tables is None else tables,
        "llm": llm,
        "filter_table_enabled": enabled,
        "llm_calls": llm_calls,
    }


async def test_switch_off_no_llm_call_and_passthrough():
    """默认关 ⇒ 零 LLM 调用、派生清单直通（与复活前行为逐位一致）。"""
    llm = _FakeLLM(result='["orders"]')
    out = await filter_table(_state(llm, enabled=False))
    assert out == {"tables": _DERIVED}
    assert llm.calls == 0


async def test_switch_on_narrows_within_derived():
    llm = _FakeLLM(result='["orders"]')
    out = await filter_table(_state(llm))
    assert out == {"tables": [{"table_name": "orders"}], "llm_calls": 1}
    assert llm.calls == 1


async def test_hallucinated_table_never_enters():
    """清单外表名被白名单拦下——不引入派生清单之外的表（#109 核心）。"""
    llm = _FakeLLM(result='["orders", "secret_table"]')
    out = await filter_table(_state(llm))
    assert out == {"tables": [{"table_name": "orders"}], "llm_calls": 1}


async def test_all_hallucinated_falls_back_to_full_derived():
    """LLM 只选清单外表（全幻觉）⇒ 全量回落，不清空表清单。"""
    llm = _FakeLLM(result='["secret_a", "secret_b"]')
    out = await filter_table(_state(llm))
    assert out == {"tables": _DERIVED}
    assert "llm_calls" not in out


async def test_string_array_output_never_leaks_strings_into_state():
    """旧代码会把 LLM 的字符串数组直塞 state["tables"]（下游按 dict 取 table_name
    全线取空）——新代码只输出派生清单内的 dict 条目，字符串形状被交集消化。"""
    llm = _FakeLLM(result='["orders", "oops"]')
    out = await filter_table(_state(llm))
    assert out["tables"] == [{"table_name": "orders"}]
    assert all(isinstance(t, dict) for t in out["tables"])


async def test_invalid_json_falls_back_to_derived():
    llm = _FakeLLM(result="not json at all")
    out = await filter_table(_state(llm))
    assert out == {"tables": _DERIVED}


async def test_llm_error_falls_back_to_derived():
    llm = _FakeLLM(exc=RuntimeError("llm down"))
    out = await filter_table(_state(llm))
    assert out == {"tables": _DERIVED}


async def test_empty_pick_falls_back_to_derived():
    """空选视为无效输出——不把"空"当过滤结果把表清单清空。"""
    llm = _FakeLLM(result="[]")
    out = await filter_table(_state(llm))
    assert out == {"tables": _DERIVED}


async def test_dict_shaped_pick_supported():
    """LLM 返回 {"table_name": ...} 形状同样收（与候选表序列化形状对称）。"""
    llm = _FakeLLM(result='[{"table_name": "users"}]')
    out = await filter_table(_state(llm))
    assert out == {"tables": [{"table_name": "users"}], "llm_calls": 1}


async def test_llm_calls_accumulates():
    llm = _FakeLLM(result='["orders"]')
    out = await filter_table(_state(llm, llm_calls=5))
    assert out["llm_calls"] == 6


async def test_no_tables_short_circuits_without_llm():
    llm = MagicMock()
    out = await filter_table(_state(llm, tables=[]))
    assert out == {"tables": []}
    assert not hasattr(llm, "invoke") or llm.invoke.call_count == 0
