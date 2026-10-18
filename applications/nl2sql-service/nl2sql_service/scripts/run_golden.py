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

**读数口径**（与 nl2sql_query_trace 同源，H4）：
- `executed`：跑完没进 error 终态（含空结果——空结果是合法答案，另算）；
- `errored`：进 error 终态（fatal/达上限/内部错）；
- `literal_unmatched`：字面量确定性未命中（P0-8②，答对率的口径债）；
- `empty`：执行成功但 0 行；
- `table_miss` / `value_miss`：期望表/期望取值未命中（配了才判）；
- `llm_calls_total` / `llm_calls_avg`：每问 LLM 调用（S-6 成本读数）。

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
            resp = client.post("/api/query", json=payload)
            body = resp.json()
            row = {
                "id": case.get("id", case["question"][:20]),
                "status": resp.status_code,
                "errored": bool(body.get("error")),
                "empty": body.get("empty_result_reason") == "genuinely_empty",
                "literal_unmatched": bool(body.get("unmatched_terms")),
                "answer_present": bool(body.get("answer")),
                "matched_values": body.get("matched_values", []),
            }
            # 期望校验（配了才判）
            miss: list[str] = []
            if case.get("expect_tables"):
                sql = (body.get("sql") or "").lower()
                if not any(t.lower() in sql for t in case["expect_tables"]):
                    miss.append("tables")
            if case.get("expect_values"):
                matched = {m.lower() for m in body.get("matched_values", [])}
                if not all(str(v).lower() in matched for v in case["expect_values"]):
                    miss.append("values")
            if case.get("expect_nonempty") and row["empty"]:
                miss.append("nonempty")
            row["miss"] = miss
            row["pass"] = (not row["errored"]) and (not miss)
            results.append(row)

    passed = sum(1 for r in results if r["pass"])
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "errored": sum(1 for r in results if r["errored"]),
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
            f"errored={summary['errored']} empty={summary['empty']} "
            f"literal_unmatched={summary['literal_unmatched']}"
        )
        for r in summary["results"]:
            flag = "PASS" if r["pass"] else "FAIL"
            extra = f" miss={r['miss']}" if r["miss"] else ""
            print(f"  [{flag}] {r['id']}{extra}")
    return code


if __name__ == "__main__":
    sys.exit(main())
