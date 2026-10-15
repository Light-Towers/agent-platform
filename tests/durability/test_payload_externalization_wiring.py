"""V3 缺口 7：`payload_externalization` 接线到 `PgCheckpointStore` 的行为断言。

方案 `docs/plans/plan-v3-unwired-landing-2026-10-15.md` §6。

判据看的是**真正落库的那份 JSON**（而不是"调用没报错"）：大 payload 必须变成 reference、
小 payload 必须原样、blob 丢了必须告警、`version` 不得因外部化而改变（否则 fencing 语义
被悄悄改掉）、且 internalize 必须发生在 schema migrate **之前**。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pytest
from agent_runtime.payload_externalization import (
    ExternalizationConfig,
    InMemoryPayloadStore,
    PayloadExternalizer,
    is_reference,
)
from agent_runtime.planner.durability import Checkpoint
from agent_runtime.planner.durability_pg import PgCheckpointStore

# ===== 替身：只模拟 execution_checkpoints 一张表，镜像 psycopg 的调用形状 =====


class _Cursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, pool: "_FakeCheckpointPool") -> None:
        self._pool = pool

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._pool.sqls.append(sql)
        low = sql.lower()
        if "select completed" in low:
            row = self._pool.rows.get(params[0])
            return _Cursor([row] if row else [])
        if "insert into" in low:
            eid, completed_json, resumable, version, generation, schema_ver = params
            self._pool.rows[eid] = (
                completed_json, time.time(), resumable, version, generation, schema_ver,
            )
            self._pool.last_persisted = completed_json
            return _Cursor([(eid,)])  # RETURNING execution_id
        raise AssertionError(f"替身未预期的 SQL: {sql[:80]}")


class _Ctx:
    def __init__(self, pool: "_FakeCheckpointPool") -> None:
        self._pool = pool

    async def __aenter__(self) -> _Conn:
        return _Conn(self._pool)

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeCheckpointPool:
    def __init__(self) -> None:
        self.rows: dict[str, tuple] = {}
        self.sqls: list[str] = []
        self.last_persisted: str | None = None

    def connection(self) -> _Ctx:
        return _Ctx(self)

    def persisted(self) -> dict:
        """最近一次落库的 completed（解析后），即"真正写进 JSONB 的东西"。"""
        assert self.last_persisted is not None
        return json.loads(self.last_persisted)


class _RecordingMigrator:
    """记录 migrate() 实际拿到的 completed，用于验证 internalize 与 migrate 的先后。"""

    def __init__(self) -> None:
        self.seen: list[dict] = []

    def needs_migration(self, from_version: int) -> bool:
        return True

    def migrate(self, completed, from_version, to_version=None):
        self.seen.append(completed)
        return completed, []


def _externalizer(store=None, threshold=64) -> tuple[PayloadExternalizer, InMemoryPayloadStore]:
    blob = store or InMemoryPayloadStore()
    return (
        PayloadExternalizer(blob, config=ExternalizationConfig(threshold_bytes=threshold)),
        blob,
    )


def _cp(completed: dict, execution_id: str = "e1") -> Checkpoint:
    return Checkpoint(
        execution_id=execution_id,
        completed=completed,
        updated_at=time.time(),
        resumable=True,
        generation=1,
        state_schema_version=1,
    )


_BIG = {"blob": "x" * 500, "kind": "tool_result"}


async def test_large_payload_is_replaced_by_reference_in_the_persisted_row():
    pool = _FakeCheckpointPool()
    ext, blob = _externalizer()
    store = PgCheckpointStore(pool, externalizer=ext)

    await store.save(_cp({"n1": _BIG}))

    persisted = pool.persisted()
    assert is_reference(persisted["n1"]), persisted
    # 原值不得出现在落库 JSON 里（这正是缺口 7 要解决的"50MB 塞 JSONB"）
    assert "x" * 500 not in pool.last_persisted
    assert persisted["n1"]["size"] > 64
    assert persisted["n1"]["checksum"].startswith("sha256:")
    # blob 里确实是原值
    assert json.loads((await blob.get(persisted["n1"]["key"])).decode()) == _BIG


async def test_round_trip_restores_the_original_payload():
    pool = _FakeCheckpointPool()
    ext, _ = _externalizer()
    store = PgCheckpointStore(pool, externalizer=ext)

    await store.save(_cp({"n1": _BIG, "n2": {"small": True}}))
    loaded = await store.load("e1")

    assert loaded is not None
    assert loaded.completed == {"n1": _BIG, "n2": {"small": True}}


async def test_payload_below_threshold_is_not_externalized():
    pool = _FakeCheckpointPool()
    ext, blob = _externalizer()
    store = PgCheckpointStore(pool, externalizer=ext)

    await store.save(_cp({"n1": {"small": True}}))

    assert not is_reference(pool.persisted()["n1"])
    assert blob._store == {}  # 没往 blob 写任何东西


async def test_version_fencing_value_is_unchanged_by_externalization():
    """version = 已完成节点数；外部化只换 value 的存放位置，不得改变 fencing 输入。"""
    pool = _FakeCheckpointPool()
    ext, _ = _externalizer()
    store = PgCheckpointStore(pool, externalizer=ext)

    completed = {"n1": _BIG, "n2": _BIG, "n3": {"small": 1}}
    await store.save(_cp(completed))

    row = pool.rows["e1"]
    assert row[3] == len(completed) == 3  # version 位


async def test_missing_blob_returns_reference_and_warns(caplog):
    """blob 丢了不算"读成功"：必须留下指名 execution 与 node 的告警，不静默降级。"""
    pool = _FakeCheckpointPool()
    ext, blob = _externalizer()
    store = PgCheckpointStore(pool, externalizer=ext)

    await store.save(_cp({"n1": _BIG, "n2": {"small": True}}))
    key = pool.persisted()["n1"]["key"]
    assert await blob.delete(key) is True

    with caplog.at_level(logging.WARNING, logger="agent_runtime.planner.durability_pg"):
        loaded = await store.load("e1")

    assert is_reference(loaded.completed["n1"])  # 原值确实拿不回来了
    assert loaded.completed["n2"] == {"small": True}  # 未外部化的节点不受影响
    text = caplog.text
    assert "blob 缺失" in text
    assert "e1" in text and "n1" in text


async def test_internalize_happens_before_schema_migration():
    """顺序硬约束：迁移函数按真实 payload 形状改写 completed，拿到 reference 会改错东西。"""
    pool = _FakeCheckpointPool()
    ext, _ = _externalizer()
    migrator = _RecordingMigrator()
    store = PgCheckpointStore(pool, migrator=migrator, externalizer=ext)

    await store.save(_cp({"n1": _BIG}))
    await store.load("e1")

    assert len(migrator.seen) == 1
    assert migrator.seen[0]["n1"] == _BIG  # 迁移看到的是原值，不是 reference
    assert not is_reference(migrator.seen[0]["n1"])


async def test_without_externalizer_the_persisted_row_is_byte_identical_to_before():
    """默认关（externalizer=None）⇒ 落库内容就是 completed 本身，行为与接线前一致。"""
    pool = _FakeCheckpointPool()
    store = PgCheckpointStore(pool)

    await store.save(_cp({"n1": _BIG}))

    assert pool.persisted() == {"n1": _BIG}
    assert store._externalizer is None


@pytest.mark.parametrize("threshold", [1, 10_000])
async def test_threshold_is_honoured_from_config(threshold):
    pool = _FakeCheckpointPool()
    ext, _ = _externalizer(threshold=threshold)
    store = PgCheckpointStore(pool, externalizer=ext)

    await store.save(_cp({"n1": _BIG}))

    assert is_reference(pool.persisted()["n1"]) is (threshold == 1)
