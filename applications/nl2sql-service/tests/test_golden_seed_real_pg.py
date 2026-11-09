# -*- coding: utf-8 -*-
"""golden 种子集成校验（skipif：需真实 dw 库）。

2026-10-19 golden 扩集（issue #97）配套；2026-10-27 批次 2 补建表前置。
DW 种子固化前，golden 的期望值没有仓内真值依据（种子当初手工建于容器）；
`golden/seed_dw.sql` 把种子入库后，本文件把它**钉在仓内**——执行 + 断言 golden
注释里引用的全部聚合读数：

    * 已支付 4 笔、合计 388.50（g10/g20 与首跑基线 §5 的共同事实）
    * 已退款 1 行（g02/g03）
    * 每城订单 北京4/上海1/广州1（g13，与历史 E2E 读数一致）
    * 9 月 3 单 / 10 月 3 单 / 8 月 0 单（g40/g41/g42——8 月为 0 是
      genuinely_empty 判别用例的根基）

任一指证被破坏 ⇒ 种子与 golden 注释脱钩，红线（禁止拿脱钩数据自证）。

**建表前置 = `deploy/data/nl2sql_dw_fixture.sql`**（仓根，批次 2 的数据面单一真相源）：
`seed_dw.sql` 只有 TRUNCATE + INSERT，不含 CREATE TABLE——它此前假设表已存在，
那是"手工建于容器"的遗留形状（重置有仓内依据、建表没有）。现在两个文件各有归属：
fixture 建结构并灌初始数据，seed 只把老库重置回基线。前两个用例分别跑在
"只有 fixture" 与 "fixture 之后再执行 seed" 两种状态上，断的是同一批读数——
两份数据的重复因此被门禁钉住，而不是靠人记得同步改两处。

后三个用例钉的是元知识配置（`deploy/data/nl2sql_meta_config.yaml`）的**库侧真值**：
data_type 要等于 information_schema 的原样拼写、values 每条要是库里真的存在的字面量、
每个 metric_expr 要能在本库跑通。不连库的那一半对齐纪律（注释逐字、引用完整性）在
`test_meta_deployment_config.py`，那个文件进常规 G1，本文件只在有真库时给读数。

跑法（本机 docker PG，与 2026-10-18 首跑同参数）::

    docker run -d --name nl2sql-pg -e POSTGRES_PASSWORD=test \
        -p 55432:5432 pgvector/pgvector:0.8.0-pg16
    docker exec nl2sql-pg psql -U postgres -c "CREATE DATABASE nl2sql_dw"
    DW_DB_DSN=postgresql://postgres:test@127.0.0.1:55432/nl2sql_dw \
        uv run pytest applications/nl2sql-service/tests/test_golden_seed_real_pg.py -q

（上线前靶面见 deploy/k8s/README.md：126 宿主的 ap-iso-pg 先跑一遍再进集群。
该容器只绑 127.0.0.1:5433，本机跑法 = `ssh -L 15433:127.0.0.1:5433 root@<126>`
后把 DW_DB_DSN 指向 127.0.0.1:15433。Windows 下 psycopg 异步需 SelectorEventLoop，
故本文件的用例是同步函数包协程（见 `_asyncio_run`），不是 `async def`。）
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg", reason="真库用例需要 psycopg")

from nl2sql_service.scripts.build_meta_knowledge import load_metric_config  # noqa: E402

_DW_DSN = os.environ.get("DW_DB_DSN", "")
_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_SEED = _GOLDEN_DIR / "seed_dw.sql"
#: 建表前置（仓根 deploy/data 是数据面单一真相源，不在 applications/ 下）
_FIXTURE = _GOLDEN_DIR.parents[2] / "deploy" / "data" / "nl2sql_dw_fixture.sql"
#: 元知识配置：与 fixture 是两份镜像声明，本文件的库侧三条纪律把它钉在真库读数上
_META_CONFIG = _FIXTURE.parent / "nl2sql_meta_config.yaml"

#: 允许进 SQL 标识符槽的形态（表/列名来自配置，但只插到经过 information_schema 对账的名字）
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

pytestmark = pytest.mark.skipif(not _DW_DSN, reason="需真实 dw 库；手动设 DW_DB_DSN 跑本文件")


def _asyncio_run(coro):
    """跑一个协程，Windows 下临时换 SelectorEventLoop 策略。

    方子与 applications/agent_federation/tests/test_db_integration.py 同一条：psycopg 异步在
    Windows 的 ProactorEventLoop 下直接拒连（InterfaceError），而 pytest-asyncio 的循环在测试体
    之前已创建，进来再换策略太晚。本文件因此是同步用例包协程——上线前靶面就在本机跑
    （经 SSH 隧道连 126 的 ap-iso-pg），不能只有 Linux 跑得通。
    """
    previous_policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(coro)
    finally:
        asyncio.set_event_loop_policy(previous_policy)


async def _fetch_all(sql: str, params=None) -> list[tuple]:
    async with await psycopg.AsyncConnection.connect(_DW_DSN) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def _run_script(path: Path) -> None:
    async with await psycopg.AsyncConnection.connect(_DW_DSN, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(path.read_text(encoding="utf-8"))


def _assert_documented_facts(stage: str) -> None:
    """golden 注释引用的聚合读数逐条成立；stage 只进断言消息，便于区分哪一步脱钩。"""

    rows = _asyncio_run(_fetch_all("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM orders WHERE status='已支付'"))
    assert tuple(rows[0]) == (4, 388.50), f"[{stage}] 已支付读数脱钩：{rows[0]}（golden g10/g20 期望 4 笔 / 388.50）"

    rows = _asyncio_run(_fetch_all("SELECT COUNT(*) FROM orders WHERE status='已退款'"))
    assert rows[0][0] == 1, f"[{stage}] 已退款读数脱钩：{rows[0]}（golden g02/g03 期望 1）"

    rows = _asyncio_run(
        _fetch_all(
            "SELECT users.city, COUNT(*) FROM orders JOIN users ON orders.user_id=users.id "
            "GROUP BY users.city ORDER BY users.city"
        )
    )
    assert {r[0]: r[1] for r in rows} == {"上海": 1, "北京": 4, "广州": 1}, (
        f"[{stage}] 每城读数脱钩：{rows}（golden g13）"
    )

    rows = _asyncio_run(
        _fetch_all(
            "SELECT COUNT(*) FROM orders WHERE created_at BETWEEN '2026-09-01' AND '2026-09-30'"
        )
    )
    assert rows[0][0] == 3, f"[{stage}] 9 月读数脱钩：{rows[0]}（golden g40）"

    rows = _asyncio_run(
        _fetch_all(
            "SELECT COUNT(*) FROM orders WHERE created_at BETWEEN '2026-08-01' AND '2026-08-31'"
        )
    )
    assert rows[0][0] == 0, (
        f"[{stage}] 8 月读数脱钩：{rows[0]}（golden g42 的 empty 判别根基：种子必须无 8 月数据）"
    )


def test_dw_fixture_creates_schema_and_matches_golden_facts():
    """建表前置本身自足：只跑 fixture（新库路径），基线读数就成立。"""
    assert _FIXTURE.exists(), f"fixture 不存在：{_FIXTURE}"
    _asyncio_run(_run_script(_FIXTURE))
    _assert_documented_facts("仅 fixture")


def test_seed_matches_golden_documented_facts():
    """fixture 建好结构后执行 seed_dw.sql，读数与 fixture 逐条一致（两侧不许分叉）。"""
    assert _SEED.exists(), f"种子文件不存在：{_SEED}"
    assert _FIXTURE.exists(), f"fixture 不存在：{_FIXTURE}"
    _asyncio_run(_run_script(_FIXTURE))
    _asyncio_run(_run_script(_SEED))
    _assert_documented_facts("fixture + seed")


async def _information_schema_columns() -> dict[tuple[str, str], str]:
    """dw 库 public 里每张普通表的 (表, 列) -> data_type 原样拼写。"""
    rows = await _fetch_all(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name IN "
        "(SELECT table_name FROM information_schema.tables "
        " WHERE table_schema = 'public' AND table_type = 'BASE TABLE')"
    )
    return {(r[0], r[1]): r[2] for r in rows}


def test_meta_config_types_match_dw_information_schema():
    """对齐纪律 1（库侧真值版）：data_type 必须等于 PG 的原样拼写。

    scripts/detect_drift.py 按字符串相等判 type_changed，写错一个拼写就是
    “每次漂移检测都报一批假类型变更”；而这类错不会让召回报错，只会让人
    逐渐把真报警当误报去掉。不连库的那一半（注释逐字、引用完整性）在
    test_meta_deployment_config.py。
    """
    assert _META_CONFIG.is_file(), f"元知识配置不存在：{_META_CONFIG}"
    _asyncio_run(_run_script(_FIXTURE))
    config = load_metric_config(str(_META_CONFIG))

    actual = _asyncio_run(_information_schema_columns())
    declared = {(c.table_name, c.column_name): c.data_type for c in config.columns}
    assert declared, "配置 columns 段为空（那本配置就没东西可对账）"
    type_diff = {k: (declared[k], actual.get(k)) for k in declared if actual.get(k) != declared[k]}
    assert not type_diff, (
        "元知识类型与库侧原样拼写不一致（库实际值在后）：" +
        "; ".join(f"{k[0]}.{k[1]}: {v[0]!r} != {v[1]!r}" for k, v in sorted(type_diff.items()))
    )
    unknown = sorted(k for k in declared if k not in actual)
    assert not unknown, f"元知识声明了库里不存在的列：{unknown}（生成期 prompt 会拿到假列名）"


def test_meta_config_values_exist_in_dw():
    """对齐纪律 2：values 段每条都必须是库里真实存在的字面量。

    写一个库里没有的值，recall_value 会把它当候选取值进 prompt ⇒
    诱导出一次必然被 validate_literals 判 missing 的 SQL。“看起来配好了”比“没配”坏。
    """
    _asyncio_run(_run_script(_FIXTURE))
    config = load_metric_config(str(_META_CONFIG))
    for value in config.values:
        table, column = value.table_name, value.column_name
        assert _IDENT_RE.match(table) and _IDENT_RE.match(column), (
            f"表/列名不是普通标识符，拒拼接：{table}.{column}"
        )
        rows = _asyncio_run(
            _fetch_all(
                # 列名只来自已经过 information_schema 对账的名字（上面两条 assert），
                # 值走参数绑定 ⇒ 本用例不拿配置文件当可直接拼接的输入信任
                f"SELECT 1 FROM {table} WHERE {column} = %s LIMIT 1",
                (value.value,),
            )
        )
        assert rows, (
            f"值在库里不存在：{table}.{column}={value.value!r}（应从 values 段删除或改 fixture）"
        )


def test_meta_config_metric_exprs_execute():
    """对齐纪律 3：每个 metric_expr 都要能在本库跑通。

    只验“能跑”不验“数值对不对”：数值口径归 golden（那里有逐条判据），
    本条拦的是另一类：表达式引了本库没有的列/函数，到了生成期才由模型原样拄进 SQL。
    """
    _asyncio_run(_run_script(_FIXTURE))
    config = load_metric_config(str(_META_CONFIG))
    known_tables = {t for t, _ in _asyncio_run(_information_schema_columns())}
    for metric in config.metrics:
        expr = metric.metric_expr
        assert expr, f"指标 {metric.metric_name} 的 metric_expr 为空"
        refs = {m.group(1) for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*\.\s*[a-z_]", expr)}
        unknown = sorted(refs - known_tables)
        assert not unknown, f"指标 {metric.metric_name} 引用了本库没有的表：{unknown}"
        from_clause = f" FROM {', '.join(sorted(refs))}" if refs else ""
        # 表名已经过 known_tables 对账 + 标识符正则收口，不是任意拼接
        sql = f"SELECT {expr}{from_clause}"
        rows = _asyncio_run(_fetch_all(sql))
        assert rows and rows[0][0] is not None, f"指标 {metric.metric_name} 读数异常：{sql} -> {rows}"

