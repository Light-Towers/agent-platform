"""评测入口：路由准确率 + 关键词命中率。

默认只跑确定性启发式路由（无外部依赖，可进 CI 门禁）；
配置 LLM_API_KEY 后加 --llm 可评测 LLM 结构化路由。

用法（从本目录执行）：
    python eval/run_eval.py
    python eval/run_eval.py --llm --fail-below 0.8
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.router import decide_route, heuristic_route  # noqa: E402


def load_golden() -> list[dict]:
    path = Path(__file__).parent / "golden.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def run(use_llm: bool) -> list[dict]:
    llm = None
    if use_llm:
        from app.agent.llm import build_chat_model

        llm = build_chat_model()
        if llm is None:
            print("LLM_API_KEY 未配置，回退启发式评测")
    results = []
    for item in load_golden():
        decision = (
            await decide_route(llm, item["question"]) if use_llm else heuristic_route(item["question"])
        )
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "expected": item["expected_capability"],
                "predicted": decision.capability,
                "capability_ok": decision.capability == item["expected_capability"],
                "reason": decision.reason,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="启用 LLM 结构化路由评测")
    parser.add_argument("--fail-below", type=float, default=0.0, help="准确率低于该值时退出码非零")
    args = parser.parse_args()

    results = asyncio.run(run(args.llm))
    correct = sum(r["capability_ok"] for r in results)
    total = len(results)
    accuracy = correct / total if total else 0.0

    print(f"{'ID':>3} {'期望':<8} {'预测':<8} {'结果':<4} 问题")
    for r in results:
        mark = "OK" if r["capability_ok"] else "MISS"
        print(f"{r['id']:>3} {r['expected']:<8} {r['predicted']:<8} {mark:<4} {r['question']}")
    print(f"\n路由准确率: {correct}/{total} = {accuracy:.2%}")

    if accuracy < args.fail_below:
        print(f"未达门禁阈值 {args.fail_below:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
