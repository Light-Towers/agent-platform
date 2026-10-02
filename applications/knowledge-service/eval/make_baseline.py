# -*- coding: utf-8 -*-
"""
把一次 e2e run 冻结为「脱敏回归基准锚点」（Phase D 实验台账的 baseline 侧）。

动机：`compare_runs.py`（回归门禁）做配对 bootstrap 时**只消费三样**——
  - `qid`（按 query 对齐的键）
  - `retrieval.metrics`（recall@5/recall@10/mrr/hit_rate@5/ndcg@10 这些**数值**）
  - `generation`（faithfulness/relevance/correctness 分数，或 `skipped` 标志）
`context` / `answer` / `reference` / `query` 正文只是当时喂 judge + 给人看的中间产物，
对回归对比多余，且内嵌真实语料明文——不宜进 git。

本脚本读一次 run 的 `e2e_per_query.jsonl`，逐条**剥掉全部正文**，只保留门禁所需的
`qid` + `tags`（枚举分类标签，非语料）+ 指标数值，写入 `eval/baselines/<label>/`，
与源文件**同名** `e2e_per_query.jsonl`（这样 compare_runs 可直接把该目录当 --baseline）。
另写 `baseline_meta.json` 记非敏感溯源（来源 run、条数、口径备注）。

诚实约定：只搬运 run 里已存在的数值，**不重算、不伪造**；缺指标的记录按原样缺省
（compare_runs 侧对缺值/ skip 自然剔除，不配对）。

用法：
  python eval/make_baseline.py --run eval/runs/<ts_hash>/ \\
      --label e2e_post_sparse_fix_2026-09-29 [--note "..."]
  # --run 也可直指 e2e_per_query.jsonl；--out-root 默认 eval/baselines
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 脚本直跑路径引导：`python eval/make_baseline.py` 时把项目根加入 sys.path。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

PER_QUERY_FILE = "e2e_per_query.jsonl"
META_FILE = "baseline_meta.json"
# 与 compare_runs.RETRIEVAL_KEYS / GENERATION_DIMS 严格对齐（门禁实际读取的键）。
RETRIEVAL_KEYS = ("recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10")
GENERATION_DIMS = ("faithfulness", "relevance", "correctness")


def resolve_per_query(path_str: str) -> Path:
    """run 目录或 jsonl 路径 → e2e_per_query.jsonl 的实际路径（同 compare_runs 语义）。"""
    p = Path(path_str)
    return p / PER_QUERY_FILE if p.is_dir() else p


def sanitize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """一条完整 per-query 记录 → 脱敏记录（仅 qid + tags + 门禁所需数值）。

    纯函数：只挑选、不计算。context/answer/reference/query/reasons 一律不落。
    """
    out: Dict[str, Any] = {"qid": rec.get("qid")}
    tags = rec.get("tags")
    if tags is not None:
        out["tags"] = tags

    metrics = (rec.get("retrieval") or {}).get("metrics") or {}
    retr: Dict[str, Any] = {k: metrics[k] for k in RETRIEVAL_KEYS if k in metrics}
    out["retrieval"] = {"metrics": retr}

    gen_in = rec.get("generation") or {}
    gen_out: Dict[str, Any] = {}
    if gen_in.get("skipped"):
        gen_out["skipped"] = True
    else:
        for dim in GENERATION_DIMS:
            if dim in gen_in:
                gen_out[dim] = gen_in[dim]
    out["generation"] = gen_out
    return out


def sanitize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [sanitize_record(r) for r in records]


def load_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_meta(run_src: str, label: str, n: int, note: Optional[str]) -> Dict[str, Any]:
    return {
        "label": label,
        "source_run": str(run_src),
        "n_records": n,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sanitized": True,
        "note": note or "脱敏锚点：仅含 qid/tags/指标数值，无 context/answer/query 正文。",
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把一次 e2e run 冻结为脱敏回归基准锚点（供 compare_runs --baseline 使用）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run", required=True, help="run 目录或 e2e_per_query.jsonl 路径")
    parser.add_argument("--label", required=True, help="基准目录名（eval/baselines/<label>/）")
    parser.add_argument("--out-root", default=str(_PROJECT_ROOT / "eval" / "baselines"),
                        help="基准输出根目录")
    parser.add_argument("--note", default=None, help="写入 baseline_meta.json 的口径备注")
    parser.add_argument("--overwrite", action="store_true", help="目标已存在时覆盖（默认拒绝，防误覆盖既有锚点）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    src = resolve_per_query(args.run)
    if not src.exists():
        print(f"错误：源 per-query 文件不存在：{src}", file=sys.stderr)
        print("  先跑 `python eval/run_e2e_eval.py ...` 产出 e2e_per_query.jsonl。", file=sys.stderr)
        return 1

    out_dir = Path(args.out_root) / args.label
    out_path = out_dir / PER_QUERY_FILE
    if out_path.exists() and not args.overwrite:
        print(f"错误：基准锚点已存在：{out_path}（要覆盖加 --overwrite）", file=sys.stderr)
        return 1

    records = load_records(src)
    if not records:
        print("错误：源 per-query 记录为空。", file=sys.stderr)
        return 1

    sanitized = sanitize_records(records)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in sanitized:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    meta = build_meta(args.run, args.label, len(sanitized), args.note)
    (out_dir / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[baseline] {len(sanitized)} 条脱敏锚点 → {out_path}")
    print(f"[baseline] 溯源 → {out_dir / META_FILE}")
    print(f"[baseline] 用法：python eval/compare_runs.py --baseline {out_dir} --candidate <runB> --fail-on-regression")
    return 0


if __name__ == "__main__":
    sys.exit(main())
