#!/usr/bin/env python3
"""
deepagents 多智能体评测驱动器（MVP）。
按 eval/PROPOSAL.md §8 步骤 2-3 落地：路由准确率集合匹配 + rubric judge。
"""
import argparse
import asyncio
import json
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
        "session_id": sid,
    }


def score_routing(pred: list, gold: list) -> dict:
    pred_set, gold_set = set(pred), set(gold)
    exact = pred_set == gold_set
    union = pred_set | gold_set
    jaccard = len(pred_set & gold_set) / len(union) if union else 0.0
    return {"exact": exact, "jaccard": round(jaccard, 4)}


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


def main():
    parser = argparse.ArgumentParser(description="deepagents 评测驱动器")
    parser.add_argument("--golden", default=str(PROJECT_ROOT / "eval" / "golden.jsonl"),
                        help="golden 集路径")
    parser.add_argument("--limit", type=int, default=0, help="限制题数（0=全部）")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理评测 session 目录")
    parser.add_argument("--no-judge", action="store_true", help="跳过 rubric judge（只跑路由）")
    args = parser.parse_args()

    asyncio.run(run_eval(
        golden_path=Path(args.golden),
        limit=args.limit,
        cleanup=not args.no_cleanup,
        judge=not args.no_judge,
    ))


if __name__ == "__main__":
    main()
