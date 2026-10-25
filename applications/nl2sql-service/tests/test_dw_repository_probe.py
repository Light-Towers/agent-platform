# -*- coding: utf-8 -*-
"""DwRepository.execute_probe 的 SQL 形状用例（2026-10-18 真库实测抓出的 bug 回归）。

**背景**：`SET LOCAL statement_timeout = %s` 带绑定参数会被 PG 服务端直接拒
（工具命令不接受参数：`syntax error at or near "$1"`）——golden 首跑才暴露，
因为此前的用例全部桩掉 DwRepository（fake 池不校验 PG 的参数化规则）。
本文件钉住三件事：
1. SET LOCAL 的时长**内联**在 SQL 文本里（不带 params）；
2. 探针 SQL 本身仍全参数化（字面量不进 SQL 文本的纪律不放松）；
3. 负超时 fail-fast（不把非法值拼进 SQL）。
"""

from __future__ import annotations

from typing import Any

import pytest
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
            return _FakeCursor([{"value": "已支付"}])
        return _FakeCursor([])


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connection(self, **_kwargs: Any) -> _FakeConn:
        return self.conn


async def test_probe_set_local_is_inlined_not_parameterized():
    """SET LOCAL 必须内联时长——PG 工具命令不接受绑定参数（$1 语法错误）。"""
    pool = _FakePool()
    repo = DwRepository(pool=pool)
    rows = await repo.execute_probe("SELECT DISTINCT status FROM orders LIMIT %s", (10,), statement_timeout_ms=1500)

    set_local = next(sql for sql, _ in pool.conn.calls if "SET LOCAL" in sql)
    assert "SET LOCAL statement_timeout = 1500" in set_local, f"时长必须内联: {set_local}"
    assert "%s" not in set_local and "$1" not in set_local, "SET LOCAL 不允许绑定参数"
    set_call_params = next(p for sql, p in pool.conn.calls if "SET LOCAL" in sql)
    assert set_call_params == (), f"SET LOCAL 调用不应带参数: {set_call_params}"
    # 探针 SQL 本身仍全参数化（纪律不因修 bug 放松）
    probe_sql, probe_params = next((sql, p) for sql, p in pool.conn.calls if "SELECT" in sql)
    assert "%s" in probe_sql and probe_params == (10,)
    assert rows == [{"value": "已支付"}]
    # 事务包裹（退出即撤，不污染池连接）
    assert pool.conn.tx_entered and pool.conn.tx_exited


async def test_probe_negative_timeout_fails_fast():
    repo = DwRepository(pool=_FakePool())
    with pytest.raises(ValueError, match="非负"):
        await repo.execute_probe("SELECT 1", statement_timeout_ms=-1)


async def test_probe_zero_timeout_is_inlined():
    pool = _FakePool()
    await DwRepository(pool=pool).execute_probe("SELECT 1", statement_timeout_ms=0)
    set_local = next(sql for sql, _ in pool.conn.calls if "SET LOCAL" in sql)
    assert "SET LOCAL statement_timeout = 0" in set_local
