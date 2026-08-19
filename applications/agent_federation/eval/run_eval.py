#!/usr/bin/env python3
"""
agent_federation 多智能体评测驱动器（MVP）。
按 eval/PROPOSAL.md §8 步骤 2-3 落地：路由准确率集合匹配 + rubric judge。
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1].resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from api.monitor import monitor


async def run_one(item: dict, timestamp: str) -> dict:
    from agent.main_agent import run_deep_agent  # lazy import，避免 --help 触发完整依赖链
    routed = []
    answer = []
    outcomes = []
    sid = f"eval_{timestamp}_{item['id']}"
    cb_route = lambda e: routed.append(e)
    cb_answer = lambda e: answer.append(e)
    cb_outcome = lambda e: outcomes.append(e)
    monitor.on("assistant_call", cb_route)
    monitor.on("task_result", cb_answer)
    monitor.on("tool_outcome", cb_outcome)
    try:
        await run_deep_agent(item["query"], workspace_id=sid)
    finally:
        monitor.off("assistant_call", cb_route)
        monitor.off("task_result", cb_answer)
        monitor.off("tool_outcome", cb_outcome)
    return {
        "id": item["id"],
        "query": item["query"],
        "expected_agents": item["expected_agents"],
        "acceptance_points": item.get("acceptance_points", []),
        "routed_agents": [e["data"]["assistant_name"] for e in routed],
        "descriptions": [e["data"]["args"]["description"] for e in routed],
        "answer": answer[-1]["data"]["result"] if answer else None,
        "tool_outcomes": [
            {"tool": e["data"]["tool_name"], "outcome": e["data"]["outcome"],
             "error_class": e["data"].get("error_class")}
            for e in outcomes
        ],
        "workspace_id": sid,
    }


def score_routing(pred: list, gold: list) -> dict:
    pred_set, gold_set = set(pred), set(gold)
    exact = pred_set == gold_set
    union = pred_set | gold_set
    jaccard = len(pred_set & gold_set) / len(union) if union else 0.0
    return {"exact": exact, "jaccard": round(jaccard, 4)}


def save_baseline(results: list[dict], path: Path) -> None:
    """把本次评测结果快照为行为基线（Plan-F R1 漂移门禁参照点）。

    baseline 只保留可复现对比的字段（id / routed_agents / routing_score /
    rubric_rate），不存 answer 全文（避免基线文件随语料噪声膨胀）。
    """
    snap = []
    for r in results:
        if "routing_score" not in r:
            continue
        entry = {
            "id": r["id"],
            "routed_agents": r.get("routed_agents", []),
            "routing_score": r["routing_score"],
        }
        if r.get("rubric_score"):
            entry["rubric_rate"] = r["rubric_score"]["rate"]
        snap.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in snap:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def compare_baseline(results: list[dict], baseline_path: Path, fail_below: float = 0.0) -> float:
    """与基线逐项对比漂移（Plan-F R1）：检测 exact 退化 / jaccard 退化 / 缺失题。

    返回漂移题占比（退化或缺失的题 / 基线题数）；fail_below>0 时由调用方决定是否非零退出。
    纯数据结构对比，无 LLM 依赖，可作为 CI 可守的 R1 漂移门禁。
    """
    base = {}
    with baseline_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                base[row["id"]] = row

    cur = {r["id"]: r for r in results if "routing_score" in r}

    drifted = 0
    for bid, brow in base.items():
        c = cur.get(bid)
        if c is None:
            drifted += 1  # 缺失题 = 行为漂移
            print(f"  [漂移] {bid}: 缺失（基线有该题）")
            continue
        b_score = brow["routing_score"]
        c_score = c["routing_score"]
        if c_score["exact"] != b_score["exact"]:
            drifted += 1
            print(f"  [漂移] {bid}: exact {b_score['exact']} -> {c_score['exact']}")
        elif c_score["jaccard"] < b_score["jaccard"]:
            drifted += 1
            print(f"  [漂移] {bid}: jaccard {b_score['jaccard']} -> {c_score['jaccard']}")
        # rubric 退化（若有基线）
        if "rubric_rate" in brow and "rubric_score" in c and c["rubric_score"]:
            if c["rubric_score"]["rate"] < brow["rubric_rate"]:
                drifted += 1
                print(f"  [漂移] {bid}: rubric {brow['rubric_rate']:.0%} -> {c['rubric_score']['rate']:.0%}")

    n = len(base)
    drift_rate = drifted / n if n else 0.0
    print(f"\nR1 漂移检测：{drifted}/{n} 题漂移，漂移率 {drift_rate:.1%}"
          + (f"（门禁 {fail_below:.0%}）" if fail_below else ""))
    return drift_rate


async def run_eval(golden_path: Path, limit: int, cleanup: bool, judge: bool):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    items = []
    with open(golden_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if limit:
        items = items[:limit]

    judge_model = None
    if judge:
        from eval.judge import build_judge_model, judge_record
        judge_model, is_fallback = build_judge_model()
        if is_fallback:
            print("警告: judge 降级同主模型（未配 EVAL_JUDGE_*，self-bias 风险）")

    print(f"评测启动：{len(items)} 题，串行执行，judge={'on' if judge else 'off'}")
    results = []
    for i, item in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] {item['id']}: {item['query'][:40]}...")
        try:
            record = await run_one(item, timestamp)
            record["routing_score"] = score_routing(
                record["routed_agents"], record["expected_agents"]
            )
            if judge and record.get("acceptance_points"):
                record.update(await judge_record(record, judge_model))
            results.append(record)
            score = record["routing_score"]
            line = f"    路由: {record['routed_agents']} -> exact={score['exact']}, jaccard={score['jaccard']}"
            if "rubric_score" in record and record["rubric_score"]:
                rs = record["rubric_score"]
                line += f" | rubric: {rs['hit']}/{rs['total']} ({rs['rate']:.0%})"
            print(line)
        except Exception as e:
            print(f"    异常: {type(e).__name__}: {e}")
            results.append({"id": item["id"], "error": str(e)})

    valid = [r for r in results if "routing_score" in r]
    if valid:
        exact_rate = sum(r["routing_score"]["exact"] for r in valid) / len(valid)
        jaccard_avg = sum(r["routing_score"]["jaccard"] for r in valid) / len(valid)
        print(f"\n汇总：精确匹配率 {exact_rate:.1%}，Jaccard 均值 {jaccard_avg:.4f}（{len(valid)} 题）")
        rubric_scores = [r["rubric_score"] for r in valid if r.get("rubric_score")]
        if rubric_scores:
            rubric_avg = sum(r["rate"] for r in rubric_scores) / len(rubric_scores)
            print(f"  rubric 均值 {rubric_avg:.1%}（{len(rubric_scores)} 题有验收点）")
        all_outcomes = []
        for r in valid:
            all_outcomes.extend(r.get("tool_outcomes", []))
        if all_outcomes:
            from collections import Counter
            counts = Counter(o["outcome"] for o in all_outcomes)
            print(f"  工具四分类：{dict(counts)}（共 {len(all_outcomes)} 次工具调用）")

    results_dir = PROJECT_ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{timestamp}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"结果落盘：{out_path}")

    if cleanup:
        output_dir = PROJECT_ROOT / "output"
        cleaned = 0
        for d in output_dir.glob("session_eval_*"):
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
        if cleaned:
            print(f"已清理 {cleaned} 个评测 session 目录")

    return results


async def run_evaluation(records: list[dict], no_judge: bool = False, cleanup: bool = True) -> list[dict]:
    """供 run-all.py 调用：对已加载的 records 跑评测，返回结果列表。

    与 run_eval() 区别：不接受 golden_path，不写结果文件，不打印汇总。
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    judge_model = None
    if not no_judge:
        from eval.judge import build_judge_model, judge_record
        judge_model, is_fallback = build_judge_model()
        if is_fallback:
            print("警告: judge 降级同主模型（未配 EVAL_JUDGE_*，self-bias 风险）")

    results = []
    for i, item in enumerate(records, 1):
        print(f"  [{i}/{len(records)}] {item['id']}: {item['query'][:40]}...")
        try:
            record = await run_one(item, timestamp)
            record["routing_score"] = score_routing(
                record["routed_agents"], record["expected_agents"]
            )
            if not no_judge and record.get("acceptance_points"):
                record.update(await judge_record(record, judge_model))
            results.append(record)
        except Exception as e:
            print(f"    异常: {type(e).__name__}: {e}")
            results.append({"id": item["id"], "error": str(e)})

    if cleanup:
        output_dir = PROJECT_ROOT / "output"
        cleaned = 0
        for d in output_dir.glob("session_eval_*"):
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
        if cleaned:
            print(f"已清理 {cleaned} 个评测 session 目录")

    return results


def _require_real_llm_key_for_baseline() -> None:
    """基线生成依赖真实 LLM 实跑；无可用通道会产出垃圾基线，提前拦截。

    真实通道判定（满足任一即放行）：
    - ``LLM_BASE_URL`` 指向可达端点（http/https 开头）且 ``LLM_API_KEY`` 非空
      —— 覆盖本地 ``opencode-gateway``（scripts/opencode_gateway.py @:8799）等
      经 CLI 自带鉴权绕开公开端点 Cloudflare 403 的真实通道；
    - 或 ``OPENAI_API_KEY`` 非占位值。

    纯测试/占位环境（两者皆无）才拦截，避免产出无意义基线。
    """
    # 已知测试/占位桩值（tests 用 setdefault 注入，避免误判为真实 key）
    _PLACEHOLDER_KEYS = {"", "test-key", "x", "sk-test", "dummy", "none"}

    llm_base = (os.getenv("LLM_BASE_URL") or "").strip()
    llm_key = (os.getenv("LLM_API_KEY") or "").strip()
    # 本地 gateway 通道：base 是 http(s) 端点且 key 非空（opencode-local-gateway 即真实可用）
    gateway_channel = bool(llm_base) and llm_base.lower().startswith(("http://", "https://")) and llm_key != ""

    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip().lower()
    openai_channel = openai_key not in _PLACEHOLDER_KEYS

    if gateway_channel or openai_channel:
        return

    print(
        "错误: --baseline 需要真实 LLM 实跑，但当前环境无可用的 LLM 通道。\n"
        "请满足以下任一条件后重试：\n"
        "  - 配置 LLM_BASE_URL( http(s) 端点 ) + LLM_API_KEY（如本地 opencode-gateway）\n"
        "  - 配置 OPENAI_API_KEY（非 test-key/x 等占位值）\n"
        "例如（本地 gateway）：\n"
        "    uv run python -m agent_federation.eval.run_eval --baseline eval/fed_latest.jsonl\n"
        "（R1 漂移门禁的比对逻辑本身无 LLM 依赖，已通过 eval/test_eval_baseline.py 覆盖。）"
    )
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="agent_federation 评测驱动器")
    parser.add_argument("--golden", default=str(PROJECT_ROOT / "eval" / "golden.jsonl"),
                        help="golden 集路径")
    parser.add_argument("--limit", type=int, default=0, help="限制题数（0=全部）")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理评测 session 目录")
    parser.add_argument("--no-judge", action="store_true", help="跳过 rubric judge（只跑路由）")
    parser.add_argument("--baseline", default=None,
                        help="把本次结果快照为行为基线（Plan-F R1 漂移门禁用），写入该路径")
    parser.add_argument("--compare", default=None,
                        help="与指定基线逐项对比漂移（exact/jaccard 退化 + 缺失题），需配合 --baseline 之外的实跑")
    parser.add_argument("--fail-below", type=float, default=0.0,
                        help="compare 模式下，漂移题占比或 exact 均值低于该值时退出码非零（默认 0=仅报告）")
    args = parser.parse_args()

    if args.baseline:
        _require_real_llm_key_for_baseline()

    results = asyncio.run(run_eval(
        golden_path=Path(args.golden),
        limit=args.limit,
        cleanup=not args.no_cleanup,
        judge=not args.no_judge,
    ))

    if args.baseline:
        save_baseline(results, Path(args.baseline))

    if args.compare:
        drift_rate = compare_baseline(results, Path(args.compare), args.fail_below)
        if args.fail_below and drift_rate > args.fail_below:
            sys.exit(1)


if __name__ == "__main__":
    main()
