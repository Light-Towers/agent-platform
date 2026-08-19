"""Planner 双跑 eval 基线（Plan-F Phase 2 P5）：同 golden 双跑 deterministic/agentic，各自记录基线。

用法（勿用 ``python -m eval.run_planner_eval``：agent_federation/eval 与根 eval 构成
namespace 合并冲突，``python -m`` 解析失败，须用直接路径运行）：
    python eval/run_planner_eval.py                    # both（默认）
    python eval/run_planner_eval.py --planner deterministic
    python eval/run_planner_eval.py --planner both --llm   # deterministic 轨启用 LLM 路由

输出：``eval/baselines/planner_<kind>_latest.jsonl``（默认 latest 覆盖，--stamp 加时间戳留痕）+ 终端汇总。
- deterministic 轨：``plan()`` 决策 route 与 ``expected_capability`` 比对（与 ``eval/run_eval.py`` 同口径），
  证明 Planner 协议下的决策与 graph/run_eval 基线一致（Phase 3 切换护栏）。
- agentic 轨：协议结构基线（route=agentic 占位 + sub_query 透传正确）；不评能力匹配
  （agentic 决策在 LLM 侧，端到端质量归 eval-llm 雷达）。

退出码：0=通过，1=deterministic 准确率未达门禁，2=环境缺失 SKIP。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 2


def load_golden() -> list[dict]:
    path = Path(__file__).parent / "golden.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_planner(kind: str):
    """按 kind 构造 Planner（走 PLANNER env 切换路径，验证 get_planner 工厂）。

    get_settings() 为 lru_cache：双跑不同 kind 前必须清缓存，否则二次调用仍命中首次 Settings。
    """
    os.environ["PLANNER"] = kind
    from agent_server.config import get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    from agent_server.planners import get_planner  # noqa: PLC0415

    return get_planner()


async def run_kind(kind: str, golden: list[dict], use_llm: bool):
    from agent_runtime.planner.protocol import PlannerContext  # noqa: PLC0415

    planner = build_planner(kind)
    llm = None
    if kind == "deterministic" and use_llm:
        if not os.getenv("LLM_API_KEY"):
            print("WARN: LLM_API_KEY 未配置，deterministic 轨回退启发式路由")
        else:
            from agent_server.agent.llm import build_chat_model  # noqa: PLC0415

            llm = build_chat_model()

    rows = []
    for item in golden:
        plan = await planner.plan(PlannerContext(question=item["question"], llm=llm))
        if kind == "deterministic":
            rows.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "expected": item["expected_capability"],
                    "route": plan.route,
                    "ok": plan.route == item["expected_capability"],
                    "reason": plan.reason,
                }
            )
        else:
            rows.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "expected": item["expected_capability"],
                    "route": plan.route,
                    "protocol_ok": plan.route == "agentic" and plan.sub_query == item["question"],
                    "reason": plan.reason,
                }
            )
    return rows


def persist(kind: str, rows: list[dict], stamp: bool) -> Path:
    out_dir = Path(__file__).parent / "baselines"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"planner_{kind}_latest.jsonl"
    if stamp:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"planner_{kind}_{ts}.jsonl"
    path = out_dir / name
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planner", choices=["deterministic", "agentic", "both"], default="both")
    parser.add_argument("--llm", action="store_true", help="deterministic 轨启用 LLM 路由（key 缺失回退启发式）")
    parser.add_argument("--stamp", action="store_true", help="基线文件加时间戳留痕（默认 latest 覆盖）")
    parser.add_argument("--fail-below", type=float, default=0.8, help="deterministic 准确率低于该值时退出码非零")
    args = parser.parse_args()

    golden = load_golden()
    kinds = ["deterministic", "agentic"] if args.planner == "both" else [args.planner]

    overall_exit = EXIT_OK
    for kind in kinds:
        rows = await run_kind(kind, golden, args.llm)
        path = persist(kind, rows, args.stamp)
        if kind == "deterministic":
            n = len(rows)
            ok = sum(1 for r in rows if r["ok"])
            acc = ok / n if n else 0.0
            print(f"[deterministic] 路由准确率 {acc:.2%} ({ok}/{n}) -> {path.name}")
            if acc < args.fail_below:
                overall_exit = EXIT_FAIL
        else:
            n = len(rows)
            ok = sum(1 for r in rows if r["protocol_ok"])
            print(f"[agentic] 协议结构基线 {ok}/{n} 通过 -> {path.name}")
    return overall_exit


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
