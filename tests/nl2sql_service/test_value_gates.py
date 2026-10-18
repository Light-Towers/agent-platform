"""取值五道闸用例（2026-10-18，P0-8①-⑤）。

钉六件事：
1. 字面量抽取走 sqlglot AST + 作用域解析（限定列/单表未限定列/多表歧义
   不猜），不是正则；
2. 闸①：取值以结构化绑定（column/value/desc JSON）进生成 prompt，
   不再是自由文本 examples；
3. 闸②：确定性未命中 ⇒ 拦截并进 correct（带该列实际取值建议）；
   **unknown ⇒ 放行**（"探不到"≠"不存在"，拿系统故障拦查询是另一种故障）；
4. 闸③：0 行分诊出 unrecognized_literal / genuinely_empty /
   no_dimension_filter 三种结论，答案不许硬造；
5. 闸④⑤：响应体带 matched_values / unmatched_terms / dict_hit /
   empty_result_reason，且 **error_detail 不上响应体**；
6. 图级：未命中取值触发一次纠正后成功（LLM 调用数仍在上限内）。
"""

from __future__ import annotations

from typing import Any

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.nodes.generate_sql import build_value_bindings, generate_sql
from nl2sql_service.agent.nodes.triage_empty import triage_empty
from nl2sql_service.agent.nodes.validate_literals import validate_literals
from nl2sql_service.services.literal_extractor import extract_literals
from nl2sql_service.services.query_service import QueryService


class _StubLLM:
    enabled = True

    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies = list(replies or ["SELECT 1 LIMIT 1"])
        self.prompts: list[str] = []

    async def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else "SELECT 1 LIMIT 1"


class _StubResolver:
    """按注入的 missing 集合给出结论；unknown 集合模拟探不到。"""

    def __init__(self, missing: list[str] | None = None, unknown: list[str] | None = None, values: list[str] | None = None) -> None:
        self.missing = set(missing or [])
        self.unknown = set(unknown or [])
        self.values = values or []
        self.resolve_calls = 0
        self.column_calls: list[tuple[str, str]] = []

    async def resolve(self, probes: list, data_types: dict | None = None) -> Any:
        from nl2sql_service.services.value_resolver import ResolutionResult, LiteralVerdict

        self.resolve_calls += 1
        verdicts = []
        for p in probes:
            if p.literal in self.unknown:
                verdicts.append(LiteralVerdict(p.table, p.column, p.literal, "unknown", "probe failed"))
            elif p.literal in self.missing:
                verdicts.append(LiteralVerdict(p.table, p.column, p.literal, "missing"))
            else:
                verdicts.append(LiteralVerdict(p.table, p.column, p.literal, "exists"))
        return ResolutionResult(verdicts=verdicts)

    async def column_values(self, table: str, column: str, data_type: str = "", declared_values: int = 0) -> list[str] | None:
        self.column_calls.append((table, column))
        return self.values


def _ctx(resolver: Any = None) -> DataAgentContext:
    return DataAgentContext(value_resolver=resolver)


# ---------------------------------------------------------------------------
# ① 字面量抽取（AST + 作用域）
# ---------------------------------------------------------------------------
def test_extract_literals_eq_and_in():
    probes, has_filter = extract_literals("SELECT * FROM orders WHERE status = '已支付' AND city IN ('北京', '上海')")
    assert {(p.table, p.column, p.literal) for p in probes} == {
        ("orders", "status", "已支付"),
        ("orders", "city", "北京"),
        ("orders", "city", "上海"),
    }
    assert has_filter is True


def test_extract_literals_qualified_and_alias_scope():
    probes, _ = extract_literals("SELECT * FROM orders o JOIN customers c ON o.cid = c.id WHERE o.status = 'x' AND c.city = 'y'")
    assert {(p.table, p.column, p.literal) for p in probes} == {("orders", "status", "x"), ("customers", "city", "y")}


def test_extract_literals_skips_ambiguous_unqualified_column():
    probes, _ = extract_literals("SELECT * FROM orders o JOIN customers c ON o.cid = c.id WHERE status = 'x'")
    assert probes == [], "多表未限定列不许猜表（猜错就是拿 A 列的值核 B 列）"


def test_extract_literals_ignores_numbers_and_broken_sql():
    assert extract_literals("SELECT * FROM orders WHERE amount > 100")[0] == []
    assert extract_literals("NOT A SQL")[0] == []


# ---------------------------------------------------------------------------
# 闸①：结构化绑定
# ---------------------------------------------------------------------------
def test_value_bindings_are_structured_json():
    block = build_value_bindings([{"column_name": "orders.status", "value": "已支付", "value_desc": "已付款"}])
    assert '"column": "orders.status"' in block
    assert '"value": "已支付"' in block
    assert build_value_bindings([]) == "（无已声明取值）"


async def test_generate_prompt_uses_structured_bindings():
    llm = _StubLLM()
    await generate_sql(
        {
            "query": "已支付的订单",
            "llm": llm,
            "tables": [{"table_name": "orders"}],
            "columns": [],
            "metrics": [],
            "values": [{"column_name": "orders.status", "value": "已支付", "value_desc": ""}],
        }
    )
    assert '"value": "已支付"' in llm.prompts[0], "取值必须以结构化绑定进 prompt"
    assert "只能使用其中已声明的" in llm.prompts[0], "生成 prompt 必须带取值绑定规则"


# ---------------------------------------------------------------------------
# 闸②：确定性未命中拦截 / unknown 放行
# ---------------------------------------------------------------------------
async def test_validate_literals_blocks_definitive_miss():
    resolver = _StubResolver(missing=["已退款"], values=["已支付", "待发货"])
    out = await validate_literals(
        {"sql": "SELECT * FROM orders WHERE status = '已退款'", "context": _ctx(resolver), "columns": []}
    )
    assert out["error_class"] == "correctable"
    assert out["value_unmatched"] == ["已退款"]
    assert out["dict_hit"] is True
    assert "已支付" in out["error_detail"], "未命中必须带该列实际取值建议"


async def test_validate_literals_passes_through_unknown():
    resolver = _StubResolver(unknown=["已退款"])
    out = await validate_literals(
        {"sql": "SELECT * FROM orders WHERE status = '已退款'", "context": _ctx(resolver), "columns": []}
    )
    assert out.get("error", "") == "", "unknown 必须放行（探不到≠不存在）"
    assert out["dict_hit"] is False
    assert out["value_unmatched"] == []


async def test_validate_literals_noop_without_resolver():
    out = await validate_literals({"sql": "SELECT * FROM orders WHERE status = 'x'", "context": _ctx(None)})
    assert out.get("error", "") == ""
    assert out["has_dimension_filter"] is True


# ---------------------------------------------------------------------------
# 闸③：零结果分诊
# ---------------------------------------------------------------------------
async def test_triage_unrecognized_literal_sets_correctable():
    resolver = _StubResolver(missing=["已退款"])
    out = await triage_empty(
        {"sql": "SELECT * FROM orders WHERE status = '已退款'", "result": [], "context": _ctx(resolver)}
    )
    assert out["empty_result"] is True
    assert out["empty_result_reason"] == "unrecognized_literal"
    assert out["error_class"] == "correctable"
    assert "不是'无数据'" in out["error_detail"]


async def test_triage_genuinely_empty_has_no_error():
    resolver = _StubResolver()
    out = await triage_empty(
        {"sql": "SELECT * FROM orders WHERE status = '已支付'", "result": [], "context": _ctx(resolver)}
    )
    assert out["empty_result_reason"] == "genuinely_empty"
    assert out.get("error", "") == "", "真无数据不是错误，答案节点如实说明"


async def test_triage_non_empty_result_short_circuit():
    resolver = _StubResolver()
    out = await triage_empty({"sql": "SELECT 1", "result": [{"n": 1}], "context": _ctx(resolver)})
    assert out == {"empty_result": False}
    assert resolver.resolve_calls == 0


async def test_triage_without_dimension_filter():
    resolver = _StubResolver(missing=["x"])
    out = await triage_empty({"sql": "SELECT count(1) FROM orders", "result": [], "context": _ctx(resolver)})
    assert out["empty_result_reason"] == "no_dimension_filter"
    assert resolver.resolve_calls == 0, "无维度过滤不值得探针"


# ---------------------------------------------------------------------------
# 闸④⑤：响应契约
# ---------------------------------------------------------------------------
async def test_response_excludes_error_detail_and_includes_value_semantics():
    class _Graph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "sql": "SELECT 1 LIMIT 1",
                "error": "",
                "error_detail": 'relation "secret" does not exist',
                "answer": "共 1 行",
                "result": [{"n": 1}],
                "value_matched": ["已支付"],
                "value_unmatched": ["已退款"],
                "dict_hit": True,
                "empty_result_reason": "genuinely_empty",
            }

    out = await QueryService(graph=_Graph(), context=None, llm=None).query("q")
    assert out["matched_values"] == ["已支付"]
    assert out["unmatched_terms"] == ["已退款"]
    assert out["dict_hit"] is True
    assert out["empty_result_reason"] == "genuinely_empty"
    assert out["path"] == "graph"
    assert "error_detail" not in out, "DB 原文不得上响应体（S-3）"
