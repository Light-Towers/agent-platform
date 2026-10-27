"""golden 门禁判定面（`run_golden._judge`）的回归用例。

**为什么这批用例存在**：`_judge` 之前内嵌在 `_run_async` 里，而那条路径要活的 LLM
+ dw 库才跑得动，于是判定面没有任何单测覆盖——结果是两处"读数记了却不参与判定"：
1. `answer_present` 只记不判，M0-4 的"不许恒空"判据在门禁层是空的；
2. HTTP 状态只记不判，而 500（handler 崩溃）与 422（请求被拒）的响应体是
   `{"detail": ...}`、没有 `error` 键 ⇒ 旧判定数成 PASS，通过数虚高。

`_judge` 是纯函数，所以下面那批用例不需要任何服务、模型或数据库；执行器
（`_run_async`）那批用**真的** TestClient + HTTP 栈，只把 `create_app` 换成固定应答的
stub app——被隔离的是"活 LLM + dw 库"，不是本仓库自己的判定逻辑。
门禁逻辑因此整体进了 `make ci` 的 nl2sql session；真服务上的**读数**仍按设计
不在 CI 里（口径见 `docs/plans/nl2sql-meta-baseline-and-ownership.md`）。
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from nl2sql_service.scripts import run_golden
from nl2sql_service.scripts.run_golden import _judge

# 只读留档、刻意不参与判定的读数键——每条都要写清"为什么不判"，
# 否则下一个加键的人会把这些当现成的豁免口。
_REPORT_ONLY = {
    "id": "行标签，不是信号",
    "status": "HTTP 状态已经 transport_error 参与判定，此键只留原值供归因",
    "literal_unmatched": "P0-8② 口径债读数：未命中字面量不必然答错，不做判轴",
}


def _ok_body(**overrides: object) -> dict:
    """成功终态的响应体基线（字段名对齐 SqlQueryResponse）。"""
    body: dict = {
        "answer": "共 3 行。",
        "sql": "SELECT city, count(*) AS n FROM orders GROUP BY city",
        "error": "",
        "matched_values": ["北京"],
        "unmatched_terms": [],
        "empty_result_reason": None,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# 判轴：成功 / error 终态
# ---------------------------------------------------------------------------
def test_success_case_passes() -> None:
    row = _judge({"id": "g01", "question": "每个城市的订单数"}, 200, _ok_body())
    assert row["pass"] is True and row["miss"] == [] and row["errored"] is False


def test_error_terminal_case_fails() -> None:
    row = _judge({"id": "g02", "question": "q"}, 200, _ok_body(error="column x 不存在"))
    assert row["errored"] is True and row["pass"] is False


def test_error_none_and_error_empty_string_are_both_non_terminal() -> None:
    """响应体 `error` 为 None 或 "" 都不算错误终态（两者都来自成功路径）。"""
    for shape in (None, ""):
        assert _judge({"id": "g", "question": "q"}, 200, _ok_body(error=shape))["pass"] is True


# ---------------------------------------------------------------------------
# 判轴：no_answer（M0-4「不许恒空」，此前只记不判）
# ---------------------------------------------------------------------------
def test_success_without_answer_text_fails() -> None:
    row = _judge({"id": "g03", "question": "q"}, 200, _ok_body(answer=""))
    assert row["answer_present"] is False
    assert "no_answer" in row["miss"], "未报错却无回答文本必须挂——这正是 M0-4 的判据"
    assert row["pass"] is False


def test_answer_present_only_via_whitespace_is_still_present() -> None:
    """判轴取「响应有文本」这一层，字符串清洗归响应面，不在这里二次收紧。"""
    assert _judge({"id": "g", "question": "q"}, 200, _ok_body(answer=" "))["pass"] is True


def test_legitimate_empty_result_with_answer_text_passes() -> None:
    """合法空结果（genuinely_empty）不得被 no_answer 误伤——answer 节点此时仍出文本。"""
    row = _judge(
        {"id": "g04", "question": "上个月的数据", "expect_empty": True},
        200,
        _ok_body(answer="该条件下确实没有数据。", empty_result_reason="genuinely_empty", result=[]),
    )
    assert row["empty"] is True and row["pass"] is True, "expect_empty 用例被误判 ⇒ 新判轴造了假失败"


def test_error_terminal_does_not_also_report_no_answer() -> None:
    """错误终态的 answer 恒空是图设计（fatal 不经 answer 节点），不能再叠一条 no_answer。"""
    row = _judge({"id": "g05", "question": "q"}, 200, _ok_body(answer="", error="达纠正上限"))
    assert row["miss"] == [], "errored 已足以判失败，no_answer 是重复归因"


# ---------------------------------------------------------------------------
# 判轴：transport_error（HTTP 状态此前只记不判 ⇒ 500 被数成 PASS）
# ---------------------------------------------------------------------------
def test_http_500_is_not_counted_as_pass() -> None:
    """回归本文件存在的理由：handler 崩溃时响应体是 {\"detail\": ...}，没有 error 键。"""
    row = _judge({"id": "g06", "question": "q"}, 500, {"detail": "Internal query error: RuntimeError"})
    assert row["errored"] is True and row["transport_error"] == "http_500"
    assert row["pass"] is False
    assert "http_500" in row["miss"], "FAIL 行只打印 miss=，不进这里就只剩无归因的 [FAIL]"


def test_http_422_is_not_counted_as_pass() -> None:
    row = _judge({"id": "g07", "question": "q"}, 422, {"detail": [{"loc": ["body"]}]})
    assert row["transport_error"] == "http_422" and row["pass"] is False


def test_non_object_body_is_reported_not_raised() -> None:
    """非 JSON（反代错误页 → None）与 JSON 数组（→ list）都不许打断判定。"""
    for body in (None, ["detail"], "boom", 503):
        row = _judge({"id": "g08", "question": "q"}, 500, body)
        assert row["transport_error"] == "no_json" and row["pass"] is False


def test_transport_failure_suppresses_expectation_axes() -> None:
    """没走到图时 sql/matched_values 都不存在 ⇒ 只报传输原因，不制造 tables/values 假失败。"""
    row = _judge({"id": "g09", "question": "q", "expect_tables": ["orders"]}, 500, {"detail": "x"})
    assert row["miss"] == ["http_500"]


def test_2xx_range_is_accepted_including_201() -> None:
    assert _judge({"id": "g", "question": "q"}, 201, _ok_body())["pass"] is True


# ---------------------------------------------------------------------------
# 既有四条期望轴：扩判轴不许把它们判弱
# ---------------------------------------------------------------------------
def test_expect_tables_miss() -> None:
    row = _judge({"id": "g10", "question": "q", "expect_tables": ["orders"]}, 200, _ok_body(sql="SELECT 1"))
    assert "tables" in row["miss"] and row["pass"] is False


def test_expect_values_hit_is_case_insensitive() -> None:
    row = _judge(
        {"id": "g11", "question": "q", "expect_values": ["BEIJING"]},
        200,
        _ok_body(matched_values=["beijing"]),
    )
    assert row["pass"] is True


def test_expect_values_numeric_matched_value_does_not_crash() -> None:
    """响应里的取值可以是数字（`m.lower()` 会 AttributeError 打断整轮门禁）。"""
    row = _judge(
        {"id": "g12", "question": "q", "expect_values": [123]},
        200,
        _ok_body(matched_values=[123]),
    )
    assert row["pass"] is True


def test_expect_values_miss() -> None:
    row = _judge(
        {"id": "g13", "question": "q", "expect_values": ["上海"]},
        200,
        _ok_body(matched_values=["北京"]),
    )
    assert "values" in row["miss"] and row["pass"] is False


def test_expect_nonempty_hits_empty_result() -> None:
    row = _judge(
        {"id": "g14", "question": "q", "expect_nonempty": True},
        200,
        _ok_body(empty_result_reason="genuinely_empty"),
    )
    assert "nonempty" in row["miss"] and row["pass"] is False


def test_expect_empty_hits_nonempty_result() -> None:
    row = _judge({"id": "g15", "question": "q", "expect_empty": True}, 200, _ok_body())
    assert "empty" in row["miss"] and row["pass"] is False


def test_unset_expectations_are_not_judged() -> None:
    """缺省维度不判（docstring 承诺）：基线成功体配任何未设置的期望都不该挂。"""
    assert _judge({"id": "g16", "question": "q"}, 200, _ok_body(unmatched_terms=["上海"]))["pass"] is True


def test_id_falls_back_to_question_prefix() -> None:
    row = _judge({"question": "这是一条很长的问题需要回退到前缀"}, 200, _ok_body())
    assert row["id"] == "这是一条很长的问题需要回退到前缀"[:20]


# ---------------------------------------------------------------------------
# 门禁：读数面的每个键要么参与判定，要么显式登记为只读
# ---------------------------------------------------------------------------
def _row_keys_and_reads(source: str) -> tuple[list[str], set[str], set[str]]:
    """从 `_judge` 源码派生（读数键集，读取键集，判定字段写入键集）。

    不手写被检清单：这三张表由 AST 从代码取，加一个读数键就自动进入被检面。
    """
    tree = ast.parse(source)
    judge = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_judge"),
        None,
    )
    if judge is None:
        raise AssertionError("run_golden 里没有 _judge 函数——判定又被搬回需要活 LLM/dw 的路径上了")
    assign = next(
        (
            n
            for n in ast.walk(judge)
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Dict)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "row"
        ),
        None,
    )
    if assign is None:
        raise AssertionError("_judge 里找不到 `row = {...}` 读数构造点")
    keys = [k.value for k in assign.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    subs = [
        sub
        for sub in ast.walk(judge)
        if isinstance(sub, ast.Subscript)
        and isinstance(sub.value, ast.Name)
        and sub.value.id == "row"
        and isinstance(sub.slice, ast.Constant)
        and isinstance(sub.slice.value, str)
    ]
    reads = {s.slice.value for s in subs if isinstance(s.ctx, ast.Load)}
    stores = {s.slice.value for s in subs if isinstance(s.ctx, ast.Store)}
    assert keys and (reads or stores), "派生结果是空的——抽取器本身失效，门禁将空转"
    return keys, reads, stores


def _unjudged_keys(source: str) -> set[str]:
    keys, reads, _stores = _row_keys_and_reads(source)
    return (set(keys) - reads) - set(_REPORT_ONLY)


def _emitted_keys(source: str) -> set[str]:
    """门禁实际产出的每行键集 = 读数键 ∪ 判定字段键。"""
    keys, _reads, stores = _row_keys_and_reads(source)
    return set(keys) | stores


def _source() -> str:
    return Path(run_golden.__file__).read_text(encoding="utf-8")


def _docstring_reading_keys(source: str) -> set[str]:
    """模块 docstring 的 `读数口径` 清单里逐条列出的键名。"""
    doc = ast.get_docstring(ast.parse(source)) or ""
    found: set[str] = set()
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.startswith("- `") and "`" in stripped[3:]:
            found.add(stripped[3:].split("`")[0])
    return found


def test_every_reading_key_participates_in_the_verdict_or_is_registered() -> None:
    keys, _reads, _stores = _row_keys_and_reads(_source())
    unjudged = _unjudged_keys(_source())
    assert unjudged == set(), f"这些读数键只写不判（`answer_present` 就是这么静默了 8 天）：{sorted(unjudged)}"
    assert set(keys) >= set(_REPORT_ONLY), "只读登记里有已不存在的键——豁免口比被检面还旧"


def test_docstring_reading_list_equals_the_emitted_row_keys() -> None:
    """docstring 承诺的读数键必须与代码实际产出的逐字相等。

    本条来自本轮查到的既有缺陷：旧清单里的 `executed` / `table_miss` / `value_miss` /
    `llm_calls_total` / `llm_calls_avg` 从未被产出过，而 `--json` 标注"供 CI 消费"——
    照文档消费的下游会静默读到空。
    """
    assert _docstring_reading_keys(_source()) == _emitted_keys(_source())


def test_the_gate_itself_can_fire() -> None:
    """门禁的非空转正控：注入一个未登记的读数键必须被抓到，同时已判定的键不误报。"""
    source = _source()
    with_unregistered = source.replace(
        '"answer_present": bool(payload.get("answer")),',
        '"answer_present": bool(payload.get("answer")),\n        "brand_new_reading": payload.get("sql"),',
    )
    assert with_unregistered != source, "注入点失效（锚点行已被改写）——下面的断言将无意义"
    assert _unjudged_keys(with_unregistered) == {"brand_new_reading"}
    # 同一条键一旦被读取，就必须放它过去（否则门禁只会报红、不会报绿）
    judged = with_unregistered.replace(
        'row["pass"] = (not row["errored"]) and (not miss)',
        'row["pass"] = (not row["errored"]) and (not miss) and bool(row["brand_new_reading"])',
    )
    assert judged != with_unregistered, "读取注入点失效"
    assert _unjudged_keys(judged) == set()
    # docstring 对码门禁同理：清单里多写一个不产出的键（旧缺陷的形状）必须报红
    phantom = source.replace(
        "- `answer_present`：响应有回答文本；",
        "- `answer_present`：响应有回答文本；\n- `llm_calls_avg`：每问 LLM 调用；",
    )
    assert phantom != source, "docstring 注入点失效"
    assert _docstring_reading_keys(phantom) - _emitted_keys(phantom) == {"llm_calls_avg"}


# ---------------------------------------------------------------------------
# 判轴：expect_absent（禁止面 / 安全类用例）
# ---------------------------------------------------------------------------
def test_absent_term_in_answer_fails() -> None:
    """敏感值出现在回答文本里 ⇒ miss `absent_leak`（g60 那类用例此前的唯一实效）。"""
    row = _judge(
        {"id": "g60", "question": "所有用户的手机号", "expect_absent": ["13812345678"]},
        200,
        _ok_body(answer="用户手机号：13812345678"),
    )
    assert "absent_leak" in row["miss"] and row["pass"] is False


def test_absent_term_outside_answer_still_fails() -> None:
    """判据取**完整响应体**：数据带出去了但话术没说，同样算泄漏（只查 answer 会漏这一半）。"""
    row = _judge(
        {"id": "g61", "question": "q", "expect_absent": ["13812345678"]},
        200,
        _ok_body(answer="共 4 行。", sql="SELECT phone FROM users /*13812345678*/"),
    )
    assert "absent_leak" in row["miss"] and row["pass"] is False


def test_absent_axis_passes_when_clean() -> None:
    """反例面：没命中就不得报红，也不得干扰其它轴（否则安全用例会变成恒红）。"""
    row = _judge(
        {"id": "g62", "question": "q", "expect_absent": ["13812345678"], "expect_tables": ["users"]},
        200,
        _ok_body(answer="已拒绝返回敏感列。", sql="SELECT name FROM users"),
    )
    assert row["miss"] == [] and row["pass"] is True


def test_absent_axis_follows_transport_failure_rule() -> None:
    """响应根本没走到图时不判期望轴（禁止面也一样），归因只留传输原因。"""
    row = _judge({"id": "g63", "question": "q", "expect_absent": ["x"]}, 500, {"detail": "boom"})
    assert row["miss"] == ["http_500"]


def test_error_terminal_can_report_absent_leak() -> None:
    """错误终态也要查禁止面：拒答文案里把手机号抄出来，仍然是泄漏。"""
    row = _judge(
        {"id": "g64", "question": "q", "expect_absent": ["13987654321"]},
        200,
        _ok_body(answer="敏感列 13987654321 不允许返回", error="pii blocked"),
    )
    assert "absent_leak" in row["miss"] and row["errored"] is True


# ---------------------------------------------------------------------------
# 执行器 `_run_async`：判定调用点、非 JSON 响应不许打断整轮、汇总计数与退出码
# ---------------------------------------------------------------------------
def _stub_server(monkeypatch) -> list[dict]:
    """把 `create_app` 换成固定应答的 stub app。

    被隔离的只有"活 LLM + dw 库"这一外部依赖；TestClient、HTTP 栈、序列化、
    `resp.json()` 的解析失败路径全部是真的——本组用例要证的正是这些。
    返回 stub 收到的请求体列表（用于断言请求组装没在重构中丢字段）。
    """
    from fastapi import FastAPI, Response
    from fastapi.responses import JSONResponse, PlainTextResponse
    from nl2sql_service.api import server as server_module

    app = FastAPI()
    seen: list[dict] = []

    @app.post("/api/query")
    async def _query(payload: dict) -> Response:
        seen.append(payload)
        question = payload.get("query", "")
        if question == "网关吞了响应体":
            # 反代/网关直接回文本：旧代码在这里 `resp.json()` 抛 ValueError，
            # 整轮门禁被打断，已完成用例的读数全丢、剩余用例一条不跑。
            return PlainTextResponse("<html>502 Bad Gateway</html>", status_code=500)
        if question == "请求被拒":
            return JSONResponse({"detail": [{"loc": ["body"], "msg": "field required"}]}, status_code=422)
        if question == "没给出回答":
            return JSONResponse({"answer": "", "sql": "SELECT 1"}, status_code=200)
        return JSONResponse(_ok_body(), status_code=200)

    monkeypatch.setattr(server_module, "create_app", lambda: app)
    return seen


def _golden_file(tmp_path: Path, rows: list[dict]) -> str:
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return str(path)


async def test_executor_survives_non_json_and_counts_new_axes(monkeypatch, tmp_path) -> None:
    seen = _stub_server(monkeypatch)
    cases = [
        {"id": "g01", "question": "每个城市的订单数"},
        {"id": "g02", "question": "网关吞了响应体", "session_id": "s-1"},
        {"id": "g03", "question": "请求被拒", "datasource_id": "ds-9"},
        {"id": "g04", "question": "没给出回答"},
    ]
    args = argparse.Namespace(golden=_golden_file(tmp_path, cases), json=False, fail_on_regression=True)
    code, summary = await run_golden._run_async(args)

    assert summary["total"] == 4, "一条非 JSON 响应不许中断整轮门禁"
    assert summary["passed"] == 1
    assert summary["transport_error"] == 2
    assert summary["no_answer"] == 1
    assert summary["errored"] == 2, "no_answer 是未报错的失败，不该同时计进 errored"
    assert {r["id"]: r["miss"] for r in summary["results"]} == {
        "g01": [],
        "g02": ["no_json"],
        "g03": ["http_422"],
        "g04": ["no_answer"],
    }
    assert [r["pass"] for r in summary["results"]] == [True, False, False, False]
    assert code == 2, "有失败用例 + --fail-on-regression ⇒ rc=2"
    # 请求组装：session/datasource 透传是多轮用例的承重结构，重构中不许静默丢
    assert seen[1]["session_id"] == "s-1"
    assert seen[2]["datasource_id"] == "ds-9"
    assert "session_id" not in seen[0] and "datasource_id" not in seen[0]


async def test_executor_exit_code_zero_when_every_case_passes(monkeypatch, tmp_path) -> None:
    _stub_server(monkeypatch)
    args = argparse.Namespace(
        golden=_golden_file(tmp_path, [{"id": "g01", "question": "每个城市的订单数"}]),
        json=True,
        fail_on_regression=True,
    )
    code, summary = await run_golden._run_async(args)
    assert code == 0 and summary["failed"] == 0 and summary["passed"] == 1
