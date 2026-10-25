"""执行期纠错回路用例（2026-10-18，方案 §5.11-E2 实装）。

钉四件事：
1. execute_sql 输出三分类 error_class；fatal（权限拒绝/连接失败）**不进**
   correct——喂 3 轮也改不出来，还扩大注入面；
2. correctable/rewritable 且未达 correct 上限 → 进 correct_sql；达上限 →
   错误终态（END）；
3. correct prompt 带 error_detail（DB 原文，对外分类消息无修正信息量）
   与 attempted_sql（已尝试序列，没有它模型会把同一处错改三遍）；
4. 对外响应不含 DB 原文（error_detail 只进 prompt/日志，S-3 联动）。

全部 stub：LLM 不发真实请求，dw 是脚本化 fake。
"""

from __future__ import annotations

from typing import Any

import pytest
from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.graph import END, _route_after_execute, build_graph
from nl2sql_service.agent.nodes.execute_sql import classify_error, classify_error_class, execute_sql
from nl2sql_service.services.query_service import QueryService


class _ScriptedLLM:
    """按序返回预制回复；prompts 记录每次调用（证 correct prompt 的内容）。"""

    enabled = True

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else ""


class _ScriptedDw:
    """前 failures 次执行抛 exc，之后返回 rows。"""

    def __init__(self, failures: int, exc: BaseException, rows: list[dict] | None = None) -> None:
        self.failures = failures
        self.exc = exc
        self.rows = rows or [{"n": 1}]
        self.calls = 0

    async def execute_readonly(self, sql: str) -> list[dict]:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return self.rows


class _Ctx(DataAgentContext):
    """只挂 dw 的上下文：召回各路的 repository 默认 None（节点自行跳过）。"""

    def __init__(self, dw_repository: Any) -> None:
        super().__init__(dw_repository=dw_repository)


# ---------------------------------------------------------------------------
# 三分类
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError('column "x" does not exist'), "correctable"),
        (RuntimeError('relation "orders" does not exist'), "correctable"),
        (RuntimeError("syntax error at or near \"FORM\""), "correctable"),
        (RuntimeError('invalid input syntax for type integer: "abc"'), "correctable"),
        (RuntimeError("canceling statement due to statement timeout"), "rewritable"),
        (RuntimeError("permission denied for table orders"), "fatal"),
        (RuntimeError("could not connect to server"), "fatal"),
        (RuntimeError("boom"), "fatal"),
    ],
)
def test_classify_error_class(exc: RuntimeError, expected: str):
    assert classify_error_class(exc) == expected


def test_classify_error_message_stays_external_facing():
    # 对外分类消息契约不变（S-3 已落地部分被本用例钉住）
    assert classify_error(RuntimeError("permission denied for table orders")) == "查询被拒绝：当前账号无权访问相关数据"
    assert classify_error(RuntimeError('column "x" does not exist')) == "查询失败：表、字段或语法不正确"


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"error": ""}, "triage_empty"),
        ({"error": "查询失败", "error_class": "correctable", "correct_count": 0}, "correct_sql"),
        (
            {"error": "查询超时", "error_class": "rewritable", "correct_count": 1, "sql_max_correct_retries": 3},
            "correct_sql",
        ),
        # fatal：权限拒绝/连接失败不喂模型
        ({"error": "查询被拒绝", "error_class": "fatal", "correct_count": 0}, END),
        # 未识别分类不进 correct（防注入面扩大）
        ({"error": "查询执行失败", "error_class": "boom", "correct_count": 0}, END),
        # 达上限落错误终态
        (
            {"error": "查询失败", "error_class": "correctable", "correct_count": 3, "sql_max_correct_retries": 3},
            END,
        ),
        (
            {"error": "查询失败", "error_class": "rewritable", "correct_count": 2, "sql_max_correct_retries": 2},
            END,
        ),
    ],
)
def test_route_after_execute(state: dict[str, Any], expected: str):
    assert _route_after_execute(state) == expected


# ---------------------------------------------------------------------------
# error_detail 截断（只进 prompt/日志）
# ---------------------------------------------------------------------------
async def test_error_detail_truncated_to_500_chars():
    dw = _ScriptedDw(99, RuntimeError('column "x" does not exist' + "y" * 600))
    out = await execute_sql({"sql": "SELECT 1", "context": _Ctx(dw_repository=dw)})
    assert out["error_class"] == "correctable"
    assert len(out["error_detail"]) == 500
    assert out["error_detail"].startswith('column "x" does not exist')


async def test_execute_success_clears_stale_error_fields():
    dw = _ScriptedDw(0, RuntimeError("unused"))
    out = await execute_sql({"sql": "SELECT 1", "context": _Ctx(dw_repository=dw)})
    assert out["error"] == "" and out["error_detail"] == "" and out["error_class"] == ""
    assert out["result"] == [{"n": 1}]


# ---------------------------------------------------------------------------
# 图级：correctable → 纠正一次后成功
# ---------------------------------------------------------------------------
async def test_correctable_failure_triggers_one_correction_then_succeeds():
    llm = _ScriptedLLM(
        [
            "not-json",  # extract_keywords 的抽取结果（解析失败回落分词）
            "SELECT amount FROM orders LIMIT 1",  # generate_sql
            "SELECT amount AS n FROM orders LIMIT 1",  # correct_sql
            "共 1 行。",  # answer 合成（M0-4）
        ]
    )
    dw = _ScriptedDw(1, RuntimeError('column "x" does not exist'))
    graph = build_graph()

    result = await graph.ainvoke(
        {"query": "统计销售额", "context": _Ctx(dw_repository=dw), "llm": llm, "sql_max_correct_retries": 3}
    )

    assert result["error"] == ""
    assert result["result"] == [{"n": 1}]
    assert result["error_class"] == "", "成功轮必须清空 error_class，否则路由会把成功轮送进 correct"
    assert result["answer"] == "共 1 行。", "成功执行必须产出非空 answer（M0-4）"
    assert dw.calls == 2
    assert len(llm.prompts) == 4, f"LLM 调用次数异常: {len(llm.prompts)}"

    correct_prompt = llm.prompts[2]
    assert 'column "x" does not exist' in correct_prompt, "DB 原文必须进 correct prompt"
    assert "SELECT amount FROM orders LIMIT 1" in correct_prompt, "已尝试的 SQL 必须进 correct prompt"
    assert "已尝试" in correct_prompt


# ---------------------------------------------------------------------------
# 图级：attempted_sql 跨轮累积
# ---------------------------------------------------------------------------
async def test_attempted_sql_accumulates_across_failures():
    llm = _ScriptedLLM(
        [
            "not-json",
            "SELECT a FROM orders LIMIT 1",
            "SELECT b FROM orders LIMIT 1",
            "SELECT c AS n FROM orders LIMIT 1",
            "共 1 行。",  # answer
        ]
    )
    dw = _ScriptedDw(2, RuntimeError('column "x" does not exist'))
    graph = build_graph()

    result = await graph.ainvoke(
        {"query": "统计销售额", "context": _Ctx(dw_repository=dw), "llm": llm, "sql_max_correct_retries": 3}
    )

    assert result["result"] == [{"n": 1}]
    assert dw.calls == 3
    assert len(llm.prompts) == 5
    # 第二次纠正时，prompt 里必须已有两次失败痕迹
    assert "SELECT a FROM orders LIMIT 1" in llm.prompts[3]
    assert "SELECT b FROM orders LIMIT 1" in llm.prompts[3]


# ---------------------------------------------------------------------------
# 图级：fatal → 0 次纠正，对外只有分类文案
# ---------------------------------------------------------------------------
async def test_permission_denied_never_enters_correction():
    llm = _ScriptedLLM(["not-json", "SELECT amount FROM orders LIMIT 1"])
    dw = _ScriptedDw(99, RuntimeError("permission denied for table orders"))
    graph = build_graph()

    result = await graph.ainvoke(
        {"query": "统计销售额", "context": _Ctx(dw_repository=dw), "llm": llm, "sql_max_correct_retries": 3}
    )

    assert dw.calls == 1, "fatal 类错误不得触发纠正回路"
    assert len(llm.prompts) == 2, "fatal 类错误不得产生 correct prompt"
    assert result["error"] == "查询被拒绝：当前账号无权访问相关数据"
    assert result["error_class"] == "fatal"
    assert "permission denied" in result["error_detail"], "原文只留在 error_detail"


# ---------------------------------------------------------------------------
# 对外响应不含 DB 原文（S-3 联动）
# ---------------------------------------------------------------------------
async def test_query_service_response_excludes_error_detail():
    class _Graph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "sql": "SELECT 1",
                "error": "查询执行失败",
                "error_detail": 'relation "secret" does not exist',
                "result": None,
            }

    out = await QueryService(graph=_Graph(), context=None, llm=None).query("统计销售额")

    assert out["error"] == "查询执行失败"
    assert "error_detail" not in out, "DB 原文不得随响应体返回"
