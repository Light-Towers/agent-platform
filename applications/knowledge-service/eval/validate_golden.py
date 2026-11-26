"""Golden 标注集门禁：防止 pending 候选被当成人工标注跑分。

规则：
- 文件不存在 / 无有效行 → rc=2（前置不可用）。
- 任一行带 `review_status` 且不等于 `approved` → rc=1（候选未复核）。
- `approved` 行必须带 `reviewer` 与 `reviewed_at`，且 `relevant_chunk_ids` 非空、`grade` 为 dict。
- `--require-approved` 时，所有行都必须是 approved（用于真实语料判决）。
- `--self-test` 注入一条 pending 行，验证门禁真的会红。

老 golden（无 `review_status` 字段）默认放行，仅作历史基线；正式判决须显式 `--require-approved`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], [f"golden 文件不存在：{path}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"L{lineno}: JSON 非法 {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"L{lineno}: 不是 JSON object")
            continue
        rows.append(row)
    return rows, errors


def validate(path: Path, require_approved: bool = False) -> list[str]:
    rows, errors = _load(path)
    if not rows and not errors:
        errors.append("golden 无有效行")
    for i, row in enumerate(rows, start=1):
        status = row.get("review_status")
        if status is not None and status != "approved":
            errors.append(f"L{i}: review_status={status!r}（未复核候选不得用于判决）")
            continue
        if status == "approved":
            for field in ("reviewer", "reviewed_at"):
                if not row.get(field):
                    errors.append(f"L{i}: approved 缺 {field}")
        if require_approved and status != "approved":
            errors.append(f"L{i}: --require-approved 下缺 approved")
        if not row.get("relevant_chunk_ids"):
            errors.append(f"L{i}: relevant_chunk_ids 为空")
        if not isinstance(row.get("grade"), dict) or not row["grade"]:
            errors.append(f"L{i}: grade 必须是非空 dict")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden")
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pending.jsonl"
            p.write_text(
                json.dumps(
                    {
                        "qid": "cand_001",
                        "query": "测试",
                        "relevant_chunk_ids": ["1"],
                        "grade": {"1": 2},
                        "review_status": "pending_human_review",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            if not validate(p, require_approved=False):
                print("SELF-TEST FAILED: pending 候选未被拦截", file=sys.stderr)
                return 1
        print("SELF-TEST PASS: pending 候选被拦截")
        return 0

    if not args.golden:
        print("必须提供 --golden（或用 --self-test）", file=sys.stderr)
        return 2
    errors = validate(Path(args.golden), require_approved=args.require_approved)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    print(f"PASS: {args.golden} golden 门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
