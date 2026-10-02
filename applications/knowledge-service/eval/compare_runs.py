# -*- coding: utf-8 -*-
"""
回归门禁：baseline vs candidate 配对比较（Phase D）。

回答用户核心诉求"改了参数/加了数据源后，我怎么知道最终 RAG 到底有没有变差"——
把两次 run 的**同一批 query**按 qid 对齐，逐指标做**配对 bootstrap 置信区间**
（agent_core.metrics.compare.bootstrap_mean_diff_ci），用 CI 是否含 0 判"真回归 vs 样本噪声"，
而非拿单次快照的两列数字拍脑袋。

输入：两次 run 目录（各含 `e2e_per_query.jsonl`，run_e2e_eval.py 产物）或直接的 per-query jsonl 路径。
逐指标（检索层 recall/ndcg/... + 生成层 faithfulness/relevance/correctness）只在**双方都有效值**
的 qid 上配对；缺值/skip 剔除、不伪造。另出 per-tag 分桶方向性对照（小样本仅定性）。

判定口径（--fail-on-regression 时非 0 退出，供 make eval-rag-gate 拦回归）：
  - 某**核心指标** mean_diff < 0 且 CI 不含 0（显著）→ 判"显著回归"。
  - CI 含 0 → 噪声内，不判回归（即便点估计为负）。
  - 默认核心指标：检索 ndcg@10 + 生成 faithfulness/correctness（relevance 记观测、不拦门）。

诚实约定：
  - 任一侧生成层整体 skipped（无 LLM）→ 生成指标标 n/a，不参与回归判定。
  - 有效配对样本 < --min-paired（默认 5）→ 该指标不定显著性，仅报点估计 + "样本不足"。

用法：
  python eval/compare_runs.py --baseline eval/runs/<ts_A>/ --candidate eval/runs/<ts_B>/ \
      [--fail-on-regression] [--confidence 0.95] [--seed 0] [--out eval/runs/compare_<...>.md]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 脚本直跑路径引导：`python eval/compare_runs.py` 时把项目根加入 sys.path。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent_core.metrics.compare import bootstrap_mean_diff_ci  # noqa: E402

PER_QUERY_FILE = "e2e_per_query.jsonl"
# 检索层指标键（与 run_e2e_eval.RETRIEVAL_KEYS 对齐）。
RETRIEVAL_KEYS: Tuple[str, ...] = ("recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10")
# 生成层维度（与 scorers.DIMS 对齐）。
GENERATION_DIMS: Tuple[str, ...] = ("faithfulness", "relevance", "correctness")
# 默认核心指标（参与回归门禁判定）；其余仅观测。
DEFAULT_CORE_KEYS: Tuple[str, ...] = ("ndcg@10", "faithfulness", "correctness")


# ---------------------------------------------------------------------------
# 载入与取值（纯函数）
# ---------------------------------------------------------------------------
def resolve_per_query(path_str: str) -> Path:
    """run 目录或 jsonl 路径 → e2e_per_query.jsonl 的实际路径。"""
    p = Path(path_str)
    if p.is_dir():
        return p / PER_QUERY_FILE
    return p


def load_per_query(path: Path) -> Dict[str, Dict[str, Any]]:
    """按 qid 索引 per-query 记录；文件缺失 → FileNotFoundError（调用方清晰报错）。"""
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            qid = str(rec.get("qid"))
            out[qid] = rec
    return out


def _retrieval_value(rec: Dict[str, Any], metric: str) -> Optional[float]:
    m = (rec.get("retrieval") or {}).get("metrics") or {}
    v = m.get(metric)
    return None if v is None else float(v)


def _generation_value(rec: Dict[str, Any], dim: str) -> Optional[float]:
    g = rec.get("generation") or {}
    if g.get("skipped"):
        return None
    v = g.get(dim)
    return None if v is None else float(v)


def extract_metric(rec: Dict[str, Any], key: str) -> Optional[float]:
    """统一取一个指标值：检索键走 retrieval.metrics，生成维走 generation（skip→None）。"""
    if key in GENERATION_DIMS:
        return _generation_value(rec, key)
    return _retrieval_value(rec, key)


def paired_series(
    base: Dict[str, Dict[str, Any]], cand: Dict[str, Dict[str, Any]], key: str
) -> Tuple[List[float], List[float], List[str]]:
    """按 qid 对齐，取双方都有效（非 None）的配对序列；返回 (baseline[], candidate[], qids[])。"""
    common = [qid for qid in base.keys() & cand.keys()]
    bs: List[float] = []
    cs: List[float] = []
    used: List[str] = []
    for qid in sorted(common):
        b = extract_metric(base[qid], key)
        c = extract_metric(cand[qid], key)
        if b is None or c is None:
            continue
        bs.append(b)
        cs.append(c)
        used.append(qid)
    return bs, cs, used


# ---------------------------------------------------------------------------
# 逐指标比较（纯函数，可单测）
# ---------------------------------------------------------------------------
def compare_metric(
    base: Dict[str, Dict[str, Any]],
    cand: Dict[str, Dict[str, Any]],
    key: str,
    *,
    confidence: float,
    seed: int,
    min_paired: int,
    core_keys: Tuple[str, ...],
) -> Dict[str, Any]:
    """一个指标的配对比较 → {key, n, mean_diff, ci_low, ci_high, significant, verdict}。"""
    bs, cs, _qids = paired_series(base, cand, key)
    n = len(bs)
    res: Dict[str, Any] = {"key": key, "n": n, "core": key in core_keys}
    if n == 0:
        res.update({"mean_diff": None, "ci_low": None, "ci_high": None,
                    "significant": False, "verdict": "n/a", "note": "无可配对样本"})
        return res
    boot = bootstrap_mean_diff_ci(cs, bs, confidence=confidence, seed=seed)  # candidate - baseline
    mean_diff = boot["mean_diff"]
    significant = boot["significant"]
    if n < min_paired:
        verdict = "样本不足"
    elif not significant:
        verdict = "无显著变化"
    elif mean_diff > 0:
        verdict = "显著改进"
    else:
        verdict = "显著回归"
    res.update({"mean_diff": mean_diff, "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
                "significant": significant, "verdict": verdict})
    return res


def regressions(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """核心指标中被判'显著回归'的项（供门禁非 0 退出）。"""
    return [r for r in results if r.get("core") and r.get("verdict") == "显著回归"]


# ---------------------------------------------------------------------------
# 报告渲染（纯函数，可单测）
# ---------------------------------------------------------------------------
def _fmt(v: Any) -> str:
    return "n/a" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))


def render_compare(
    baseline_label: str, candidate_label: str,
    results: List[Dict[str, Any]], confidence: float,
) -> str:
    lines: List[str] = [
        "# 回归门禁：baseline vs candidate（配对 bootstrap）",
        "",
        f"- baseline: `{baseline_label}`",
        f"- candidate: `{candidate_label}`",
        f"- 置信水平: {confidence:.0%}（CI 含 0 → 噪声内，不判回归）",
        "",
        "| 指标 | 核心 | 配对 n | Δ(candidate−baseline) | 95% CI | 判定 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        ci = f"[{_fmt(r['ci_low'])}, {_fmt(r['ci_high'])}]"
        lines.append(
            f"| {r['key']} | {'✅' if r['core'] else '—'} | {r['n']} | "
            f"{_fmt(r['mean_diff'])} | {ci} | {r['verdict']} |"
        )
    bad = regressions(results)
    lines += [
        "",
        "## 结论",
        "",
        f"- 显著回归的核心指标：**{len(bad)}** 个"
        + ("（→ 门禁不通过）" if bad else "（→ 未见回归）"),
    ]
    for r in bad:
        lines.append(f"  - `{r['key']}` Δ={_fmt(r['mean_diff'])} CI=[{_fmt(r['ci_low'])}, {_fmt(r['ci_high'])}]")
    lines += [
        "",
        "> Δ>0 且 CI 不含 0 = 显著改进；Δ<0 且 CI 不含 0 = 显著回归；CI 含 0 = 噪声内（即便点估计为负也不拦门）。",
        "> 配对只在双方都有效值的同一 qid 上算；生成层 skipped / 缺值剔除，不伪造。",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="回归门禁：baseline vs candidate 逐指标配对 bootstrap 比较（Phase D）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--baseline", required=True, help="baseline run 目录或 e2e_per_query.jsonl")
    parser.add_argument("--candidate", required=True, help="candidate run 目录或 e2e_per_query.jsonl")
    parser.add_argument("--confidence", type=float, default=0.95, help="bootstrap 置信水平")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap 随机种子（可复现）")
    parser.add_argument("--min-paired", type=int, default=5, help="低于此配对数不定显著性")
    parser.add_argument("--core", default=",".join(DEFAULT_CORE_KEYS),
                        help="逗号分隔核心指标（仅这些参与回归拦截）")
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="任一核心指标显著回归 → 非 0 退出（供 make eval-rag-gate）")
    parser.add_argument("--out", default=None, help="比较报告 md 输出（缺省仅打印）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    base_path = resolve_per_query(args.baseline)
    cand_path = resolve_per_query(args.candidate)
    for label, p in (("baseline", base_path), ("candidate", cand_path)):
        if not p.exists():
            print(f"错误：{label} 的 per-query 文件不存在：{p}", file=sys.stderr)
            print("  先跑 `python eval/run_e2e_eval.py ...` 产出 e2e_per_query.jsonl。", file=sys.stderr)
            return 1

    base = load_per_query(base_path)
    cand = load_per_query(cand_path)
    if not base or not cand:
        print("错误：某一侧 per-query 记录为空。", file=sys.stderr)
        return 1

    core_keys = tuple(k.strip() for k in args.core.split(",") if k.strip())
    keys = list(RETRIEVAL_KEYS) + list(GENERATION_DIMS)
    results = [
        compare_metric(base, cand, k, confidence=args.confidence, seed=args.seed,
                       min_paired=args.min_paired, core_keys=core_keys)
        for k in keys
    ]

    md = render_compare(str(base_path), str(cand_path), results, args.confidence)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"[gate] 比较报告 → {out_path}")
    else:
        print(md)

    bad = regressions(results)
    print(f"[gate] 显著回归核心指标 {len(bad)} 个：{[r['key'] for r in bad]}")
    if args.fail_on_regression and bad:
        print("[gate] 判定：相对 baseline 显著回归 → 门禁不通过。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
