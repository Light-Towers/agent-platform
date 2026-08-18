#!/usr/bin/env python
"""全项目评测驱动器：跑 4 项目评测集 + 汇总报告。

用法：
  python eval/run-all.py                    # 跑全量（所有项目）
  python eval/run-all.py --project deepagents  # 只跑 deepagents
  python eval/run-all.py --project wenda    # 只跑 wenda（通过 adapter）
  python eval/run-all.py --limit 10         # 每项目限制 10 题
  python eval/run-all.py --no-judge         # 跳过 rubric judge
  python eval/run-all.py --cleanup          # 清理评测 session 目录

输出：
  eval/results/<timestamp>/all-results.jsonl   # 全量结果
  eval/results/<timestamp>/summary.json        # 汇总报告
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

eval_dir = Path(__file__).resolve().parent
project_root = eval_dir.parent
sys.path.insert(0, str(project_root))

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())


def load_golden(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def group_by_project(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        project = r.get("project", "deepagents")
        groups.setdefault(project, []).append(r)
    return groups


async def eval_deepagents(records: list[dict], no_judge: bool, cleanup: bool) -> list[dict]:
    """跑 deepagents 评测（复用 run-eval.py 逻辑）。"""
    from eval.run_eval import run_evaluation
    return await run_evaluation(records, no_judge=no_judge, cleanup=cleanup)


async def eval_subservice(records: list[dict], adapter_url: str) -> list[dict]:
    """跑子服务评测（通过 adapter /query 端点）。"""
    import httpx

    results = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for r in records:
            query = r["query"]
            start = time.perf_counter()
            try:
                resp = await client.post(
                    f"{adapter_url}/query",
                    json={"query": query},
                )
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    results.append({
                        "id": r.get("id", ""),
                        "query": query,
                        "answer": data.get("answer", ""),
                        "latency_ms": latency,
                        "fallback": data.get("fallback", False),
                        "expected_agents": r.get("expected_agents", []),
                    })
                else:
                    results.append({
                        "id": r.get("id", ""),
                        "query": query,
                        "answer": f"HTTP {resp.status_code}",
                        "latency_ms": latency,
                        "fallback": True,
                        "error": f"adapter 返回 {resp.status_code}",
                    })
            except Exception as e:
                results.append({
                    "id": r.get("id", ""),
                    "query": query,
                    "answer": f"error: {e}",
                    "latency_ms": (time.perf_counter() - start) * 1000,
                    "fallback": True,
                    "error": str(e),
                })
    return results


def write_report(results: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "all-results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    by_project: dict[str, list[dict]] = {}
    for r in results:
        by_project.setdefault(r.get("project", "unknown"), []).append(r)

    summary = {
        "total": len(results),
        "by_project": {
            proj: {
                "count": len(items),
                "fallback_count": sum(1 for r in items if r.get("fallback")),
                "avg_latency_ms": sum(r.get("latency_ms", 0) for r in items) / len(items) if items else 0,
            }
            for proj, items in by_project.items()
        },
    }
    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"评测完成：{len(results)} 题")
    for proj, stats in summary["by_project"].items():
        print(f"  {proj}: {stats['count']} 题, fallback {stats['fallback_count']}, avg {stats['avg_latency_ms']:.0f}ms")
    print(f"报告：{output_dir}")
    print(f"{'='*60}")


async def main_async(args: argparse.Namespace) -> None:
    golden_path = eval_dir / args.golden
    if not golden_path.exists():
        print(f"评测集不存在: {golden_path}")
        sys.exit(1)

    records = load_golden(golden_path)
    if args.limit > 0:
        records = records[:args.limit]

    groups = group_by_project(records)
    print(f"加载 {len(records)} 题，{len(groups)} 个项目: {list(groups.keys())}")

    all_results: list[dict] = []

    for project, items in groups.items():
        if args.project and project != args.project:
            continue

        print(f"\n--- {project} ({len(items)} 题) ---")

        if project == "deepagents":
            results = await eval_deepagents(items, no_judge=args.no_judge, cleanup=not args.no_cleanup)
        elif project == "wenda":
            adapter_url = os.getenv("WENDA_DATA_AGENT_URL", "http://localhost:8001")
            results = await eval_subservice(items, adapter_url)
        elif project == "kefu":
            # kefu-adapter 已弃用并移除；默认直连 kefu-service(:8003) 的 /invoke。
            # 仍支持 KEFU_ADAPTER_URL 显式覆盖（若外部 legacy + adapter 仍在运行）。
            adapter_url = os.getenv("KEFU_ADAPTER_URL") or os.getenv(
                "KEFU_SERVICE_URL", "http://localhost:8003"
            )
            results = await eval_subservice(items, adapter_url)
        elif project == "zhiku":
            adapter_url = os.getenv("ZHIKU_API_URL", "http://localhost:8900")
            results = await eval_subservice(items, adapter_url)
        else:
            print(f"  未知项目: {project}，跳过")
            continue

        for r in results:
            r["project"] = project
        all_results.extend(results)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = eval_dir / "results" / timestamp
    write_report(all_results, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="全项目评测驱动器")
    parser.add_argument("--golden", default="golden.jsonl", help="评测集文件名")
    parser.add_argument("--project", default="", help="只跑指定项目（deepagents/wenda/zhiku/kefu）")
    parser.add_argument("--limit", type=int, default=0, help="每项目限制题数（0=全部）")
    parser.add_argument("--no-judge", action="store_true", help="跳过 rubric judge")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理评测 session 目录")
    args = parser.parse_args()

    import asyncio
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
