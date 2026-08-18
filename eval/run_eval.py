"""评测入口：路由准确率 + 关键词命中率。

默认只跑确定性启发式路由（无外部依赖，可进 CI 门禁）；
配置 LLM_API_KEY 后加 --llm 可评测 LLM 结构化路由。

CI / 门禁分层约定（见 docs/architecture-improvement-plan.md §6 TB-8）：
- 确定性门禁（agent-platform-ci.yml → `make ci`）：默认（无 --llm）跑启发式评测，
  无 LLM 依赖、永远可达，--fail-below 默认 0.8。CI 只守这一层，不评 LLM 质量分。
- LLM 质量雷达（eval-llm.yml，定时+手动，非阻塞）：用 --require-llm 跑真 LLM 评测，
  验证端到端答案质量 / 路由决策 / 护栏拦截 / 跨模型回归；LLM_API_KEY 缺失则显式
  SKIP（退出码 2），不假装通过，也不阻塞 push。结果存 artifact 供趋势查看。
- --llm：本地调试用，启用 LLM 结构化路由评测；key 缺失回退启发式并 WARN。

用法：
    python -m eval.run_eval
    python -m eval.run_eval --llm --fail-below 0.8
    python -m eval.run_eval --require-llm   # CI 要求 LLM 但未配 key 时 SKIP(2)
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.router import decide_route, heuristic_route

# 退出码约定：0=通过，1=未达门禁阈值，2=环境缺失导致 SKIP（LLM 评测被要求但 key 不可用）
EXIT_SKIP = 2


def load_golden() -> list[dict]:
    path = Path(__file__).parent / "golden.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def run(use_llm: bool, require_llm: bool) -> tuple[list[dict], bool]:
    """返回 (results, ran_llm)。ran_llm 为 False 时表示回退/跳过了 LLM 评测。"""
    llm = None
    ran_llm = False
    if use_llm or require_llm:
        if not os.getenv("LLM_API_KEY"):
            if require_llm:
                print("SKIP: --require-llm 已指定但 LLM_API_KEY 未配置，评测环境不可达")
                return [], False
            print("WARN: LLM_API_KEY 未配置，回退启发式评测（非完整 LLM 评测）")
        else:
            from app.agent.llm import build_chat_model

            llm = build_chat_model()
            if llm is None and require_llm:
                print("SKIP: --require-llm 已指定但 build_chat_model() 返回 None，评测环境不可达")
                return [], False
            ran_llm = llm is not None
            if not ran_llm:
                print("WARN: LLM_API_KEY 未配置，回退启发式评测（非完整 LLM 评测）")

    results = []
    for item in load_golden():
        decision = (
            await decide_route(llm, item["question"]) if llm is not None else heuristic_route(item["question"])
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
    return results, ran_llm


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="启用 LLM 结构化路由评测（key 缺失则回退启发式）")
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="要求必须跑 LLM 评测；key 缺失时显式 SKIP(退出码2)，避免 CI 假装通过",
    )
    parser.add_argument("--fail-below", type=float, default=0.8, help="准确率低于该值时退出码非零（默认 0.8）")
    args = parser.parse_args()

    if args.require_llm and not os.getenv("LLM_API_KEY"):
        # 提前短路，避免 asyncio.run 空跑
        print("SKIP: --require-llm 已指定但 LLM_API_KEY 未配置，评测环境不可达")
        return EXIT_SKIP

    results, ran_llm = asyncio.run(run(args.llm, args.require_llm))

    if not results and (args.require_llm or (args.llm and not os.getenv("LLM_API_KEY"))):
        # run() 内部已打印 SKIP 原因，这里仅返回约定退出码
        return EXIT_SKIP

    correct = sum(r["capability_ok"] for r in results)
    total = len(results)
    accuracy = correct / total if total else 0.0

    mode = "LLM 路由" if ran_llm else "启发式路由"
    print(f"{'ID':>3} {'期望':<8} {'预测':<8} {'结果':<4} 问题")
    for r in results:
        mark = "OK" if r["capability_ok"] else "MISS"
        print(f"{r['id']:>3} {r['expected']:<8} {r['predicted']:<8} {mark:<4} {r['question']}")
    print(f"\n{mode}准确率: {correct}/{total} = {accuracy:.2%}")

    if accuracy < args.fail_below:
        # 规避 ruff 对 {args.fail_below:.0%} 中文 f-string 的解析误报（F821），改用 .format
        print("未达门禁阈值 {:.0%}".format(args.fail_below))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
