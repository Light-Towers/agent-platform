"""golden 回归门禁（H4 质量回路 + §11.6-② 基线读数）：一键跑出可复现的门禁数字。

**为什么需要它**：§6 要求"golden 一键跑出门禁读数"，但缺三样——golden 从哪来、
谁标、基线数字是多少。本脚本是"一键跑"的那一半；golden 来源/标注 owner/基线
口径见 `docs/plans/nl2sql-meta-baseline-and-ownership.md`。

**怎么跑**（需要活的 LLM + dw 库，属运维/发版前门禁，不是单测）::

    python -m nl2sql_service.scripts.run_golden \
        --golden path/to/golden.jsonl [--json] [--fail-on-regression]

**golden.jsonl 每行一个用例**（字段见下；期望值可部分缺省，缺省的维度不判）::

    {"id":"g01","question":"上个月每个城市的订单数","expect_tables":["orders"],
     "expect_values":[],"expect_nonempty":true,"notes":"口径：按收货城市"}

判轴（2026-10-27 起八轴）：`expect_tables` / `expect_values` / `expect_nonempty`
（true 才判）/ `expect_empty`（期望 genuinely_empty——空极断言，幻觉列/错时间窗
会给出非空错值，没这一轴时空结果无从断言）/ 隐式 `errored`（任何 error 终态即挂）/
隐式 `transport_error`（非 2xx 或响应体不是对象：根本没走到图，此时期望读数无意义，
只登记传输原因）/ 隐式 `no_answer`（未报错却没有回答文本——M0-4 判据"不许恒空"）/
`expect_absent`（禁止面：这些串不许出现在**完整响应体**里，命中即 miss `absent_leak`。
安全类用例靠它——2026-10-27 之前 g60 四类期望全为空，等于泄漏也算 PASS）。

**读数口径**（与 nl2sql_query_trace 同源，H4）：下列 10 个键 = `--json` 里 `results`
每行的全部字段，本清单与代码由 `applications/nl2sql-service/tests/test_golden_judge.py` 断言逐字相等。
2026-10-27 按代码实读订正本清单——旧版写的 `executed` / `table_miss` / `value_miss` /
`llm_calls_total` / `llm_calls_avg` 从未被产出过，照它消费 CI 只会读到空：
- `id`：用例标签（无 `id` 时回退问题前 20 字）；
- `status`：HTTP 状态码原值；
- `errored`：进 error 终态（fatal/达上限/内部错），或响应根本没走到图；
- `transport_error`：`""` / `no_json` / `http_<状态码>`；
- `empty`：执行成功但 0 行（`empty_result_reason == genuinely_empty`）；
- `literal_unmatched`：字面量确定性未命中（P0-8②，答对率的口径债）——刻意只读不判，
  未命中不必然答错；
- `answer_present`：响应有回答文本；
- `matched_values`：确定性命中的取值（`expect_values` 消费它）；
- `miss`：未命中的判轴名（空列表 = 各轴都过）；
- `pass`：终判，`not errored and not miss`。

一个键占一行是刻意的：`applications/nl2sql-service/tests/test_golden_judge.py` 按"冒号前第一个反引号名"抽取本清单
并与代码产出的行键集逐字对码，合并两条会让其中一个键逃出对码。

复用 app 的 lifespan 装配（TestClient 触发），与生产请求路径零偏差——不另造
一套 context 组装，避免"门禁跑的路"和"线上跑的路"是两条。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _load_golden(path: str) -> list[dict]:
    cases: list[dict] = []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"golden 第 {lineno} 行不是合法 JSON: {exc}") from exc
        if "question" not in obj:
            raise SystemExit(f"golden 第 {lineno} 行缺 question 字段")
        cases.append(obj)
    return cases


def _judge(case: dict, status_code: int, body: object) -> dict:
    """单用例判定（纯函数）：期望 + HTTP 状态 + 响应体 → 读数行。

    为什么从 `_run_async` 里抽出来：判定原先内嵌在那条需要活 LLM + dw 库的路径上，
    于是"记了不判"的读数（`answer_present`、HTTP 状态）没有任何用例能覆盖它——
    一条 500（handler 崩溃）或 422（请求被拒）的响应体没有 `error` 键，
    旧判定把它数成 PASS，门禁头条因此虚高。抽成纯函数后每条判轴都能单测。

    `body` 允许是任意形状：非对象（JSON 解析失败 / 返回数组）与非 2xx 都归为
    "响应根本没走到图"，此时期望轴不予判定（读数无意义），只登记传输原因。
    """
    transport = ""
    if not isinstance(body, dict):
        transport = "no_json"
    elif not 200 <= status_code < 300:
        transport = f"http_{status_code}"
    payload = body if isinstance(body, dict) else {}

    row = {
        "id": case.get("id", case["question"][:20]),
        "status": status_code,
        "transport_error": transport,
        "errored": bool(transport) or bool(payload.get("error")),
        "empty": payload.get("empty_result_reason") == "genuinely_empty",
        "literal_unmatched": bool(payload.get("unmatched_terms")),
        "answer_present": bool(payload.get("answer")),
        "matched_values": payload.get("matched_values", []),
    }
    miss: list[str] = []
    if row["transport_error"]:
        # 传输失败要同时进 miss：FAIL 行只打印 `miss=`，不进这里就只剩一个无归因的 [FAIL]。
        miss.append(row["transport_error"])
    else:
        if case.get("expect_tables"):
            sql = (payload.get("sql") or "").lower()
            if not any(t.lower() in sql for t in case["expect_tables"]):
                miss.append("tables")
        if case.get("expect_values"):
            matched = {str(m).lower() for m in row["matched_values"]}
            if not all(str(v).lower() in matched for v in case["expect_values"]):
                miss.append("values")
        if case.get("expect_nonempty") and row["empty"]:
            miss.append("nonempty")
        # expect_empty（2026-10-19 扩集新增轴）：期望 genuinely_empty 而结果非空 ⇒ miss。
        # 补上「空结果」这一极——幻觉列/错时间窗会给出非空错值，旧的
        # expect_nonempty=false 实为不判（仅 true 参与），空极无可断言轴。
        if case.get("expect_empty") and not row["empty"]:
            miss.append("empty")
        # expect_absent（2026-10-27 新增，安全类用例的禁止面）：这些串**不许**出现在
        # 整个响应里。判据取**序列化后的完整响应体**而不是只看 answer——敏感值可能出现在
        # data 行、sql 或任何回传字段里，只查 answer 会让"数据带出去了但话术没说"漏网。
        # 禁止值一律是 ASCII 数字/标识（见 golden/seed_dw.sql），序列化层级与 unicode
        # 转义都不影响命中；要禁非 ASCII 串，必须先摊平编码再比。
        for term in case.get("expect_absent") or []:
            if str(term) in json.dumps(payload, ensure_ascii=False):
                miss.append("absent_leak")
                break
        # M0-4 判轴（2026-10-27）：图只在 error 为空时才放行到 answer 节点，
        # 而该节点与 `query_service._build_response` 的成功/拒答路径都保证文本非空，
        # 所以"未报错却无回答"只能是链路坏了，不是合法形态。
        if not row["errored"] and not row["answer_present"]:
            miss.append("no_answer")
    row["miss"] = miss
    row["pass"] = (not row["errored"]) and (not miss)
    return row


async def _run_async(args: argparse.Namespace) -> tuple[int, dict]:
    from fastapi.testclient import TestClient

    from nl2sql_service.api.server import create_app

    cases = _load_golden(args.golden)
    app = create_app()
    # TestClient 作上下文管理器 = 触发 lifespan（装配 meta/dw 池、repos、llm、graph）
    with TestClient(app) as client:
        results: list[dict] = []
        for case in cases:
            payload = {"query": case["question"]}
            if case.get("datasource_id"):
                payload["datasource_id"] = case["datasource_id"]
            # 多轮用例（M3 时间/实体继承）：同 session_id 的用例按文件序串成一条
            # 会话链——g03「那上个月呢」这类改写必须接着前一轮的 session 才有意义。
            # 不带 session_id 的用例行为逐字节不变（单轮零变更分支）。
            if case.get("session_id"):
                payload["session_id"] = case["session_id"]
            resp = client.post("/api/query", json=payload)
            try:
                body = resp.json()
            except ValueError:
                # 非 JSON（反代错误页 / 纯文本 500）不许打断整轮门禁：打断会丢掉已完成
                # 用例的读数，且剩余用例一条都不跑——门禁自己比被测对象先失效。
                body = None
            results.append(_judge(case, resp.status_code, body))

    passed = sum(1 for r in results if r["pass"])
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "errored": sum(1 for r in results if r["errored"]),
        "transport_error": sum(1 for r in results if r["transport_error"]),
        "no_answer": sum(1 for r in results if "no_answer" in r["miss"]),
        "absent_leak": sum(1 for r in results if "absent_leak" in r["miss"]),
        "empty": sum(1 for r in results if r["empty"]),
        "literal_unmatched": sum(1 for r in results if r["literal_unmatched"]),
        "results": results,
    }
    code = 0
    if args.fail_on_regression and summary["failed"]:
        code = 2
    return code, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="nl2sql golden 回归门禁（H4/§11.6-②）")
    parser.add_argument("--golden", required=True, help="golden.jsonl 路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出（供 CI 消费）")
    parser.add_argument("--fail-on-regression", action="store_true", help="有失败用例返回 2（门禁用）")
    args = parser.parse_args(argv)

    code, summary = asyncio.run(_run_async(args))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"golden 门禁：{summary['passed']}/{summary['total']} 通过；"
            f"errored={summary['errored']} transport={summary['transport_error']} "
            f"no_answer={summary['no_answer']} absent_leak={summary['absent_leak']} "
            f"empty={summary['empty']} "
            f"literal_unmatched={summary['literal_unmatched']}"
        )
        for r in summary["results"]:
            flag = "PASS" if r["pass"] else "FAIL"
            extra = f" miss={r['miss']}" if r["miss"] else ""
            print(f"  [{flag}] {r['id']}{extra}")
    return code


if __name__ == "__main__":
    sys.exit(main())
