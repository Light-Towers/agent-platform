"""ADR-0017/T11：从现网 v4 集合生成人工标注候选集（不是最终 golden）。

每个候选来自真实文档，query 由该文档的标题/首段抽取，relevant_chunk_ids 暂填来源文档，
并强制带 `review_status: pending_human_review`。人工复核前**不得**用于判决。

用法：python eval/build_golden_candidates.py --uri http://milvus:19530 --limit 20 --out <path>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _clean(line: str) -> str:
    return re.sub(r"^[#\-\*>\s]+", "", line).strip()


def _query_from(row: dict) -> tuple[str, str]:
    content = row.get("content") or ""
    lines = [_clean(x) for x in content.splitlines()]
    for line in lines:
        if len(line) < 12 or len(line) > 120:
            continue
        if "……" in line or "<sup>" in line:
            continue
        if len(re.findall(r"[A-Za-zÀ-ÿ]", line)) / len(line) > 0.2:
            continue
        if re.match(r"^[\d\.]+", line) or re.match(r"^第\s*\d+\s*页", line):
            continue
        if re.match(r"^[a-z]\)", line) or line.startswith(("附录", "本文件")):
            continue
        if re.fullmatch(r"[A-Za-z0-9\.\-\s]+", line):
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", line)) < 12:
            continue
        text = line.rstrip("。；; ")
        query = text[:40] + ("？" if len(text) <= 40 else "")
        return query, line[:120]
    return "", ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--collection", default="product_manual_v4_bge_m3")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from pymilvus import MilvusClient

    c = MilvusClient(uri=args.uri)
    rows = c.query(
        collection_name=args.collection,
        filter="",
        limit=1000,
        output_fields=["chunk_id", "content", "source_doc", "item_name"],
    )
    candidates: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        query, evidence = _query_from(row)
        if not query or query in seen:
            continue
        seen.add(query)
        candidates.append(
            {
                "qid": f"cand_{len(candidates) + 1:03d}",
                "query": query,
                "item_name": row.get("item_name") or "",
                "relevant_chunk_ids": [str(row["chunk_id"])],
                "grade": {str(row["chunk_id"]): 2},
                "tags": ["real_corpus", "auto_candidate"],
                "source_doc": row.get("source_doc") or "",
                "evidence_excerpt": evidence,
                "review_status": "pending_human_review",
            }
        )
        if len(candidates) >= args.limit:
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in candidates) + "\n",
        encoding="utf-8",
    )
    print(f"CANDIDATES {len(candidates)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
