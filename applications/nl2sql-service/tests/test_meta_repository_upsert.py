"""MetaRepository 幂等 upsert 用例（#107）：ON CONFLICT 目标与 DDL 唯一约束一致。

裸 INSERT 会让同输入重跑第二次撞 UniqueViolation 中途回滚——M0-2"连跑两次
完全一致"因此半交付。这里用假连接捕获 SQL，钉死三个表的冲突目标与 DO UPDATE
列集（不连真 PG；约束存在性由 DDL 单测与真库 init 负责）。
"""

from __future__ import annotations

from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository


class _FakeConn:
    def __init__(self) -> None:
        self.captured: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        self.captured.append((sql, params or ()))


class _NullAsyncCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connection(self) -> _NullAsyncCtx:
        return _NullAsyncCtx(self.conn)


_SCOPE = {
    "tenant_id": "t-1",
    "workspace_id": "w-1",
    "datasource_id": "dw",
}


async def test_save_column_upserts_on_natural_key():
    pool = _FakePool()
    repo = MetaRepository(pool=pool)
    await repo.save_column({**_SCOPE, "table_name": "orders", "column_name": "id", "column_comment": "主键"})
    sql, params = pool.conn.captured[0]
    assert "INSERT INTO nl2sql_column_info" in sql
    assert "ON CONFLICT (tenant_id, workspace_id, datasource_id, table_name, column_name)" in sql
    assert "DO UPDATE SET column_comment = EXCLUDED.column_comment" in sql
    assert "tenant_id = EXCLUDED.tenant_id" not in sql, "冲突目标列不得进 DO UPDATE"
    assert len(params) == 6


async def test_save_metric_upserts_on_natural_key():
    pool = _FakePool()
    repo = MetaRepository(pool=pool)
    await repo.save_metric({**_SCOPE, "metric_name": "gmv", "metric_desc": "成交额"})
    sql, _ = pool.conn.captured[0]
    assert "ON CONFLICT (tenant_id, workspace_id, datasource_id, metric_name)" in sql
    assert "DO UPDATE SET metric_desc = EXCLUDED.metric_desc" in sql


async def test_save_value_upserts_on_natural_key():
    pool = _FakePool()
    repo = MetaRepository(pool=pool)
    await repo.save_value({**_SCOPE, "column_name": "status", "value": "已支付", "value_desc": ""})
    sql, _ = pool.conn.captured[0]
    assert "ON CONFLICT (tenant_id, workspace_id, datasource_id, column_name, value)" in sql
    assert "DO UPDATE SET value_desc = EXCLUDED.value_desc" in sql


async def test_all_keys_in_conflict_target_degrades_to_do_nothing():
    """入参键全部落在冲突目标上（无其余列可更新）⇒ DO NOTHING，不生成空 SET。"""
    pool = _FakePool()
    repo = MetaRepository(pool=pool)
    await repo.save_value(
        {
            "tenant_id": "t",
            "workspace_id": "w",
            "datasource_id": "d",
            "column_name": "status",
            "value": "x",
        }
    )
    sql, _ = pool.conn.captured[0]
    assert "DO NOTHING" in sql
    assert "DO UPDATE SET" not in sql


async def test_custom_table_prefix_respected():
    pool = _FakePool()
    repo = MetaRepository(pool=pool, table_prefix="custom_")
    await repo.save_column({**_SCOPE, "table_name": "orders", "column_name": "id"})
    sql, _ = pool.conn.captured[0]
    assert "INSERT INTO custom_column_info" in sql
