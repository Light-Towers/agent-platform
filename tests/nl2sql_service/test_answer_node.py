"""answer 合成节点与降级拒答用例（2026-10-18，M0-4 + §5.11-V3）。

钉五件事：
1. 成功执行必过 answer 节点，产出非空 answer（此前 execute_sql → END，
   `query_service` 恒返回空 answer——M0-4 判据）；
2. 结果进 prompt 前按**双上限**截断（行 + 字节，先到先截）；
3. 超上限走"汇总统计 + 前 N 行样例"而非裸截断——模型答"总数多少"时
   裸截断行会给错答案（§5.11-V3-2）；
4. LLM 不可用/返回空时给确定性兜底结论，不断链；
5. 什么都没召回到时明确拒答（fallback=True），不回空 answer。
"""

from __future__ import annotations

from typing import Any

from nl2sql_service.agent.nodes.answer import answer, summarize_result
from nl2sql_service.agent.nodes.generate_sql import build_aggregation_hint, generate_sql
from nl2sql_service.services.query_service import QueryService


class _StubLLM:
    enabled = True

    def __init__(self, reply: str = "上月销售额为 12000 元。") -> None:
        self.reply = reply
        self.prompt: str | None = None

    async def invoke(self, prompt: str) -> str:
        self.prompt = prompt
        return self.reply


# ---------------------------------------------------------------------------
# 双上限结果视图
# ---------------------------------------------------------------------------
def test_small_result_passes_through_whole():
    rows = [{"city": "北京", "cnt": 3}, {"city": "上海", "cnt": 5}]
    text, stats = summarize_result(rows, max_rows=100, max_bytes=51200)
    assert stats == {"rows": 2, "truncated": False}
    assert "北京" in text and "上海" in text


def test_over_row_limit_falls_back_to_summary_plus_sample():
    rows = [{"city": f"c{i}", "cnt": i} for i in range(250)]
    text, stats = summarize_result(rows, max_rows=100, max_bytes=51200)
    assert stats["truncated"] is True
    assert stats["rows"] == 250
    assert stats["sample_rows"] == 100
    assert "【汇总统计】" in text and "总行数" in text
    assert "仅可用于举例，不可用于回答总量" in text
    # 汇总值可作答：数值列聚合必须出现在文本里
    assert "cnt" in text


def test_over_byte_limit_also_truncates():
    rows = [{"blob": "x" * 400} for _ in range(200)]  # 全量 80KB > 50KB
    text, stats = summarize_result(rows, max_rows=1000, max_bytes=51200)
    assert stats["truncated"] is True
    assert stats["sample_rows"] < 200, "行数没超但字节超时必须收缩样例"
    assert len(text.encode("utf-8")) <= 51200, f"截断后仍超字节上限: {len(text.encode('utf-8'))}"


def test_none_result_is_explicit():
    text, stats = summarize_result(None)
    assert stats["rows"] == 0
    assert "无结果" in text


def test_single_row_wider_than_limit_keeps_summary_only():
    """单行就超字节上限：退到"仅汇总统计"，不许死循环也不许超限。"""
    rows = [{"blob": "x" * 60000}]
    text, stats = summarize_result(rows, max_rows=100, max_bytes=51200)
    assert stats["truncated"] is True
    assert stats["sample_rows"] == 0
    assert "样例行因体量上限全部省略" in text
    assert len(text.encode("utf-8")) <= 51200


# ---------------------------------------------------------------------------
# answer 节点
# ---------------------------------------------------------------------------
async def test_answer_node_uses_llm_and_state_slots():
    llm = _StubLLM()
    out = await answer(
        {
            "query": "上个月销售额",
            "sql": "SELECT sum(amount) FROM orders LIMIT 1",
            "result": [{"sum": 12000}],
            "llm": llm,
            "date_info": "当前时间：2026-10-18 09:00 周日（+0800）",
            "tables": [{"table_name": "orders"}],
            "columns": [{"table_name": "orders", "column_name": "amount"}],
            "metrics": [],
            "values": [],
        }
    )
    assert out["answer"] == "上月销售额为 12000 元。"
    assert llm.prompt is not None
    assert "SELECT sum(amount)" in llm.prompt, "SQL 必须进 answer prompt"
    assert "12000" in llm.prompt, "结果必须进 answer prompt"


async def test_answer_node_falls_back_when_llm_disabled():
    out = await answer({"query": "q", "sql": "SELECT 1 LIMIT 1", "result": [{"n": 1}], "llm": None})
    assert out["answer"], "LLM 不可用时 answer 不许为空（M0-4 判据）"
    assert "1 行" in out["answer"]


async def test_answer_node_falls_back_when_llm_returns_empty():
    out = await answer(
        {"query": "q", "sql": "SELECT 1 LIMIT 1", "result": [{"n": 1}], "llm": _StubLLM(reply="  ")}
    )
    assert out["answer"], "LLM 返回空（超时降级）时必须给确定性结论"


async def test_answer_node_passes_through_error_state():
    out = await answer({"query": "q", "sql": "SELECT 1", "result": None, "error": "查询被拒绝", "llm": _StubLLM()})
    assert out["answer"] == ""


# ---------------------------------------------------------------------------
# 聚合引导（§5.11-V3-3）
# ---------------------------------------------------------------------------
def test_aggregation_hint_only_when_table_stats_are_large():
    hint = build_aggregation_hint({"table_stats": [{"table_name": "dwd_orders", "row_estimate": 400_000_000}]})
    assert "dwd_orders" in hint and "聚合函数" in hint

    assert build_aggregation_hint({"table_stats": [{"table_name": "dim_city", "row_estimate": 36}]}) == ""
    assert build_aggregation_hint({}) == ""
    assert build_aggregation_hint({"table_stats": []}) == ""


async def test_generate_sql_includes_aggregation_hint():
    llm = _StubLLM(reply="SELECT 1 LIMIT 1")
    await generate_sql(
        {
            "query": "统计订单总量",
            "llm": llm,
            "tables": [],
            "columns": [],
            "metrics": [],
            "values": [],
            "table_stats": [{"table_name": "dwd_orders", "row_estimate": 400_000_000}],
        }
    )
    assert llm.prompt is not None
    assert "聚合函数" in llm.prompt, "大表候选必须带聚合引导"


# ---------------------------------------------------------------------------
# 降级拒答
# ---------------------------------------------------------------------------
async def test_query_service_refuses_when_nothing_recalled():
    class _Graph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"sql": "", "error": "", "answer": "", "result": None}

    out = await QueryService(graph=_Graph(), context=None, llm=None).query("一个莫名其妙的问题")
    assert out["fallback"] is True
    assert "拒绝猜测" in out["answer"], "零召回必须显式拒答而不是空 answer"


async def test_query_service_keeps_success_response_shape():
    class _Graph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"sql": "SELECT 1 LIMIT 1", "error": "", "answer": "共 1 行", "result": [{"n": 1}]}

    out = await QueryService(graph=_Graph(), context=None, llm=None).query("q")
    assert out["fallback"] is False
    assert out["answer"] == "共 1 行"
