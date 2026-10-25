# -*- coding: utf-8 -*-
"""DwRepository.execute_readonly 的只读语义用例（#119 回归）。

**背景**：原实现用**会话级** `SET default_transaction_read_only = on`——
psycopg3 autocommit=False 下它与后续 SQL 同处 T1，该 GUC 只作用于其后开启的
事务（对当次查询无效），且残留污染池连接、可被连接重置（DISCARD ALL 一类）
打穿，而依赖方注释仍宣称"两道都在"给出第三道防线的错觉。#119 改为与
`execute_probe` 同构的**事务内 SET LOCAL**。本文件钉住四件事：
1. SET LOCAL 在事务内、内联字面量（PG 工具命令不接受绑定参数）；
2. 用户 SQL 全参数化，且执行在 SET LOCAL 之后；
3. 会话级 SET（无 LOCAL）不得再出现——防退回到旧形态；
4. 事务包裹：退出即撤，池连接不残留只读 GUC。
"""

from __future__ import annotations

from typing import Any

from nl2sql_service.repositories.postgres.dw.dw_repository import DwRepository


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict]:
        return self._rows


class _FakeTx:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self) -> "_FakeTx":
        self._conn.tx_entered = True
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self._conn.tx_exited = True
        return False


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.tx_entered = False
        self.tx_exited = False

    def transaction(self) -> _FakeTx:
        return _FakeTx(self)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, sql: str, params: tuple | None = None) -> _FakeCursor:
        self.calls.append((sql, tuple(params or ())))
        if "SELECT" in sql:
            return _FakeCursor([{"table_name": "orders"}])
        return _FakeCursor([])


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connection(self, **_kwargs: Any) -> _FakeConn:
        return self.conn


async def test_readonly_set_local_inside_transaction():
    """SET LOCAL 必须在事务内、内联、且先于用户 SQL 执行。"""
    pool = _FakePool()
    repo = DwRepository(pool=pool)
    rows = await repo.execute_readonly(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        ("public",),
    )

    set_local = next((sql, p) for sql, p in pool.conn.calls if "default_transaction_read_only" in sql)
    assert set_local[0] == "SET LOCAL default_transaction_read_only = on", (
        f"必须事务级 SET LOCAL: {set_local[0]}"
    )
    assert set_local[1] == (), "SET LOCAL 是 PG 工具命令，不接受绑定参数"
    # 用户 SQL 全参数化，且在 SET LOCAL 之后执行
    user = next((sql, p) for sql, p in pool.conn.calls if "SELECT" in sql)
    assert "%s" in user[0] and user[1] == ("public",)
    assert pool.conn.calls.index(set_local) < pool.conn.calls.index(user)
    # 事务包裹（退出即撤，不污染池连接）
    assert pool.conn.tx_entered and pool.conn.tx_exited
    assert rows == [{"table_name": "orders"}]


async def test_readonly_has_no_session_level_set():
    """会话级 SET（无 LOCAL）不得出现——#119 修的就是它无效+残留+注释误导。"""
    pool = _FakePool()
    await DwRepository(pool=pool).execute_readonly("SELECT 1")
    session_sets = [sql for sql, _ in pool.conn.calls if "SET default_transaction_read_only" in sql]
    assert session_sets == [], f"不得再发会话级 SET: {session_sets}"


async def test_readonly_helpers_go_through_same_guard():
    """get_table_schema / list_tables 走同一道只读闸（参数化 + SET LOCAL + 事务）。"""
    pool = _FakePool()
    await DwRepository(pool=pool).get_table_schema("orders")
    assert "SET LOCAL default_transaction_read_only = on" in [sql for sql, _ in pool.conn.calls]
    schema = next((sql, p) for sql, p in pool.conn.calls if "information_schema.columns" in sql)
    assert "%s" in schema[0] and schema[1] == ("orders",)

    pool2 = _FakePool()
    await DwRepository(pool=pool2).list_tables("analytics")
    tables = next((sql, p) for sql, p in pool2.conn.calls if "information_schema.tables" in sql)
    assert "%s" in tables[0] and tables[1] == ("analytics",)
    assert pool2.conn.tx_entered and pool2.conn.tx_exited
