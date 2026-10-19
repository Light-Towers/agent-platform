# -*- coding: utf-8 -*-
"""golden 种子集成校验（skipif：需真实 dw 库）。

2026-10-19 golden 扩集（issue #97）配套。DW 种子固化前，golden 的期望值没有
仓内真值依据（种子当初手工建于容器）；`golden/seed_dw.sql` 把种子入库后，本
文件把它**钉在仓内**——执行种子 + 断言 golden 注释里引用的全部聚合读数：

    * 已支付 4 笔、合计 388.50（g10/g20 与首跑基线 §5 的共同事实）
    * 已退款 1 行（g02/g03）
    * 每城订单 北京4/上海1/广州1（g13，与历史 E2E 读数一致）
    * 9 月 3 单 / 10 月 3 单 / 8 月 0 单（g40/g41/g42——8 月为 0 是
      genuinely_empty 判别用例的根基）

任一指证被破坏 ⇒ 种子与 golden 注释脱钩，红线（禁止拿脱钩数据自证）。

跑法（本机 docker PG，与 2026-10-18 首跑同参数）::

    docker run -d --name nl2sql-pg -e POSTGRES_PASSWORD=test \
        -p 55432:5432 pgvector/pgvector:0.8.0-pg16
    docker exec nl2sql-pg psql -U postgres -c "CREATE DATABASE nl2sql_dw"
    DW_DB_DSN=postgresql://postgres:test@127.0.0.1:55432/nl2sql_dw \
        uv run pytest applications/nl2sql-service/tests/test_golden_seed_real_pg.py -q
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg", reason="真库用例需要 psycopg")

_DW_DSN = os.environ.get("DW_DB_DSN", "")
_SEED = Path(__file__).resolve().parents[1] / "golden" / "seed_dw.sql"

pytestmark = pytest.mark.skipif(not _DW_DSN, reason="需真实 dw 库；手动设 DW_DB_DSN 跑本文件")


async def _fetch_all(sql: str, params=None) -> list[tuple]:
    async with await psycopg.AsyncConnection.connect(_DW_DSN) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


def test_seed_matches_golden_documented_facts():
    """执行 seed_dw.sql 后，golden 注释引用的聚合读数逐条成立。"""
    assert _SEED.exists(), f"种子文件不存在：{_SEED}"
    seed_sql = _SEED.read_text(encoding="utf-8")

    async def _run():
        async with await psycopg.AsyncConnection.connect(_DW_DSN, autocommit=True) as conn:
            async with conn.cursor() as cur:
                await cur.execute(seed_sql)

    asyncio.run(_run())

    rows = asyncio.run(_fetch_all("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM orders WHERE status='已支付'"))
    assert tuple(rows[0]) == (4, 388.50), f"已支付读数脱钩：{rows[0]}（golden g10/g20 期望 4 笔 / 388.50）"

    rows = asyncio.run(_fetch_all("SELECT COUNT(*) FROM orders WHERE status='已退款'"))
    assert rows[0][0] == 1, f"已退款读数脱钩：{rows[0]}（golden g02/g03 期望 1）"

    rows = asyncio.run(
        _fetch_all(
            "SELECT users.city, COUNT(*) FROM orders JOIN users ON orders.user_id=users.id "
            "GROUP BY users.city ORDER BY users.city"
        )
    )
    assert {r[0]: r[1] for r in rows} == {"上海": 1, "北京": 4, "广州": 1}, f"每城读数脱钩：{rows}（golden g13）"

    rows = asyncio.run(
        _fetch_all(
            "SELECT COUNT(*) FROM orders WHERE created_at BETWEEN '2026-09-01' AND '2026-09-30'"
        )
    )
    assert rows[0][0] == 3, f"9 月读数脱钩：{rows[0]}（golden g40）"

    rows = asyncio.run(
        _fetch_all(
            "SELECT COUNT(*) FROM orders WHERE created_at BETWEEN '2026-08-01' AND '2026-08-31'"
        )
    )
    assert rows[0][0] == 0, f"8 月读数脱钩：{rows[0]}（golden g42 的 empty 判别根基：种子必须无 8 月数据）"
