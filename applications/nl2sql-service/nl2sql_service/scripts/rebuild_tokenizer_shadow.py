"""ADR-0017/T9：把 nl2sql 取值行按共享分词器重建到影子列，并原子切换。

用法：
    python -m nl2sql_service.scripts.rebuild_tokenizer_shadow --dsn "$META_DB_DSN" --dry-run
    python -m nl2sql_service.scripts.rebuild_tokenizer_shadow --dsn "$META_DB_DSN" --apply

- 默认 dry-run：只统计待重建行数，不写库。
- --apply：在一个事务内先写影子列，再 `UPDATE ... SET search_text = search_text_shadow`，
  保证对外不存在"新旧分词混读"的中间态。重建期间旧正式列始终可服务。
- 需要 008_tokenizer_shadow 迁移先执行（init_meta_schema 会自动加载）。
"""

from __future__ import annotations

import argparse
from typing import Any

from agent_runtime.retrieval_tokenizer import DICT_VERSION, get_tokenizer


def build_shadow_text(column_name: str, value: str, value_desc: str) -> str:
    """与 MetaKnowledgeService 写入侧同源（共享单例），避免第二套分词。"""
    tokens = get_tokenizer().tokenize(f"{column_name} {value} {value_desc}")
    return " ".join(tokens)


def _rows(cur: Any) -> list[tuple[Any, ...]]:
    cur.execute(
        "SELECT id, column_name, value, COALESCE(value_desc, '') "
        "FROM nl2sql_value_info WHERE tokenizer IS DISTINCT FROM %s",
        (DICT_VERSION,),
    )
    return cur.fetchall()


def _apply(cur: Any, rows: list[tuple[Any, ...]], batch_size: int) -> int:
    updated = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = [(build_shadow_text(col, val, desc), DICT_VERSION, row_id) for row_id, col, val, desc in batch]
        cur.executemany(
            "UPDATE nl2sql_value_info SET search_text_shadow = %s, tokenizer_shadow = %s WHERE id = %s",
            payload,
        )
        updated += len(batch)
    # 原子切换：影子列 -> 正式列（同一事务，提交前对外仍是旧值）。
    cur.execute(
        "UPDATE nl2sql_value_info SET search_text = search_text_shadow, tokenizer = tokenizer_shadow "
        "WHERE tokenizer_shadow = %s",
        (DICT_VERSION,),
    )
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="元知识库 DSN（与 META_DB_DSN 同源）")
    parser.add_argument("--apply", action="store_true", help="真正写入；缺省为 dry-run")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)

    try:
        import psycopg
    except ImportError as exc:
        print(f"前置不可用：psycopg 未安装：{exc}")
        return 2

    try:
        with psycopg.connect(args.dsn) as conn:
            with conn.cursor() as cur:
                rows = _rows(cur)
                if not args.apply:
                    print(f"DRY-RUN: 待重建 {len(rows)} 行（未写库）；字典版本={DICT_VERSION}")
                    return 0
                updated = _apply(cur, rows, args.batch_size)
            conn.commit()
        print(f"APPLIED: 影子重建 {updated} 行，原子切换完成；字典版本={DICT_VERSION}")
        return 0
    except psycopg.Error as exc:
        print(f"重建失败（事务已回滚）：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
