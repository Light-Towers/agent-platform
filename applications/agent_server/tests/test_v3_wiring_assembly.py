"""V3「未接线半成品转正」批的**装配面**与 HTTP 面断言。

对应方案 `docs/plans/plan-v3-unwired-landing-2026-10-15.md` §4 验收 4（项 1）与验收 5。

为什么单独钉装配：本仓反复出现的失效形态是「能力实现存在、单测全绿，但生产装配点没接」
（`state_migration` 就是——迁移链与 `load()` 分支早就写好了，两个调用点都没传 migrator）。
所以这里的判据是**装配产物本身**，不是「模块能 import」。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from agent_runtime.control_plane import ControlPlane
from agent_runtime.execution_recovery import ReaperConfig, RecoveryOrchestrator
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
    QueueStatus,
)
from agent_runtime.payload_externalization import PayloadExternalizer
from agent_runtime.state_migration import StateSchemaMigrator, get_default_migrator
from agent_server.api.control import router
from agent_server.config import Settings
from agent_server.main import _build_pg_stores
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _DummyPool:
    """只作构造参数：这些 store 的 __init__ 不触碰 pool（连接只在读写时取）。"""


def _req(execution_id: str = "e1") -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        tenant_id="t1",
        session_id="s1",
        user_id="u1",
        priority=ExecutionPriority.NORMAL,
    )


# ===== 项 1：state_migration 装配 =====


def test_pg_checkpoint_store_is_constructed_with_default_migrator():
    """不传 migrator 时 load() 的迁移分支恒不执行 ⇒ 钉住「传了且是全局默认那一份」。"""
    checkpoint_store, idempotency, ownership, trajectory = _build_pg_stores(_DummyPool())
    assert checkpoint_store is not None
    assert (idempotency, ownership, trajectory) != (None, None, None)
    assert isinstance(checkpoint_store._migrator, StateSchemaMigrator)
    assert checkpoint_store._migrator is get_default_migrator()


def test_build_pg_stores_without_pool_degrades_to_all_none():
    assert _build_pg_stores(None) == (None, None, None, None)


def test_current_schema_version_has_no_pending_migration():
    """现值登记：默认 migrator 无注册步骤 ⇒ 接线后行为零变更（不是「迁移已在跑」）。"""
    migrator = get_default_migrator()
    assert migrator.registered_steps == []
    assert migrator.needs_migration(migrator.target_version) is False


# ===== 项 2：恢复开关默认值 =====


def test_scheduler_recovery_defaults_to_off():
    """默认关：开启后 retry 会新入队消耗队列容量，属需运维显式打开的行为变更。"""
    settings = Settings()
    assert settings.scheduler_recovery_enabled is False
    assert settings.scheduler_recovery_max_retries == 3


# ===== 项 3：requeue / recover 的 HTTP 面 =====


def _client(control_plane) -> TestClient:
    # tests/ 被 lint 的「裸 FastAPI(」门禁排除（scripts/lint_architecture.py 的 tests/ 作用域），
    # 这里只需要 router + app.state，不需要 build_api_app 的中间件栈。
    app = FastAPI()
    app.include_router(router)
    app.state.control_plane = control_plane
    return TestClient(app)


def _cp(recovery=None) -> tuple[ControlPlane, ExecutionScheduler]:
    scheduler = ExecutionScheduler(InMemorySchedulerStore())
    return ControlPlane(scheduler, recovery=recovery), scheduler


async def _park(scheduler, execution_id: str, status: QueueStatus) -> None:
    await scheduler.submit(_req(execution_id))
    await scheduler.complete(execution_id, status)


def test_requeue_endpoint_returns_queued():
    cp, scheduler = _cp()
    asyncio.run(_park(scheduler, "e1", QueueStatus.FAILED))
    resp = _client(cp).post("/api/executions/e1/requeue")
    assert resp.status_code == 200
    assert resp.json() == {"execution_id": "e1", "status": "queued"}


def test_requeue_endpoint_rejects_completed_with_409():
    cp, scheduler = _cp()
    asyncio.run(_park(scheduler, "e1", QueueStatus.COMPLETED))
    resp = _client(cp).post("/api/executions/e1/requeue")
    assert resp.status_code == 409
    assert "completed" in resp.json()["detail"]


def test_requeue_endpoint_404_for_unknown_execution():
    cp, _ = _cp()
    assert _client(cp).post("/api/executions/nope/requeue").status_code == 404


def test_recover_endpoint_returns_action():
    scheduler = ExecutionScheduler(InMemorySchedulerStore())
    cp = ControlPlane(
        scheduler,
        recovery=RecoveryOrchestrator(scheduler, ReaperConfig(max_retries=3)),
    )
    asyncio.run(_park(scheduler, "e1", QueueStatus.FAILED))
    resp = _client(cp).post("/api/executions/e1/recover")
    assert resp.status_code == 200
    assert resp.json() == {"execution_id": "e1", "action": "retry"}


def test_recover_endpoint_409_when_recovery_disabled():
    cp, scheduler = _cp()
    asyncio.run(_park(scheduler, "e1", QueueStatus.FAILED))
    resp = _client(cp).post("/api/executions/e1/recover")
    assert resp.status_code == 409
    assert "SCHEDULER_RECOVERY_ENABLED" in resp.json()["detail"]


def test_endpoints_503_when_control_plane_absent():
    app = FastAPI()
    app.include_router(router)
    app.state.control_plane = None
    client = TestClient(app)
    assert client.post("/api/executions/e1/requeue").status_code == 503
    assert client.post("/api/executions/e1/recover").status_code == 503


# ===== 缺口 7：payload_externalization 的装配面 =====


@pytest.fixture
def _settings_env(monkeypatch):
    """get_settings 是 lru_cache：改 env 前后都必须清缓存，否则快照会漏到别的用例。"""
    import agent_server.config as cfg

    cfg.get_settings.cache_clear()
    yield monkeypatch
    cfg.get_settings.cache_clear()


def test_payload_externalization_defaults_to_off():
    """默认关 ⇒ checkpoint 路径逐字不变（externalizer 为 None，不是"配了个空壳"）。"""
    from agent_server.main import _build_payload_externalizer

    assert _build_payload_externalizer() is None
    checkpoint_store, *_ = _build_pg_stores(_DummyPool())
    assert checkpoint_store._externalizer is None
    # 同批接线的 migrator 不受影响，仍在位
    assert checkpoint_store._migrator is get_default_migrator()


def test_payload_externalization_enabled_builds_externalizer(_settings_env, tmp_path):
    from agent_server.main import _build_payload_externalizer

    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_ENABLED", "true")
    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_DIR", str(tmp_path / "blobs"))

    ext = _build_payload_externalizer()
    assert ext is not None
    # _build_pg_stores 自己再建一个（不是同一个对象），故只断言"装配上了"而非同一性
    checkpoint_store, *_ = _build_pg_stores(_DummyPool())
    assert isinstance(checkpoint_store._externalizer, PayloadExternalizer)


def test_payload_externalization_gc_min_age_hours_env_passthrough(_settings_env, tmp_path):
    """#121：GC 年龄下限 env 化——调大要改代码的时代结束。"""
    from agent_server.main import _build_payload_externalizer

    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_ENABLED", "true")
    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_DIR", str(tmp_path / "blobs"))
    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_GC_MIN_AGE_HOURS", "720")

    ext = _build_payload_externalizer()
    assert ext._config.gc_min_age_hours == 720


# ===== #121：GC 两段式回调（先候选后引用扫描） =====


class _FakeExternalizer:
    def __init__(self, candidates: list[str]):
        self._candidates = candidates
        self.sweep_calls: list[dict] = []

    async def list_gc_candidates(self):
        return list(self._candidates)

    async def sweep(self, min_age_seconds=None, *, referenced_keys=None):
        self.sweep_calls.append({"referenced_keys": set(referenced_keys or ())})
        return {"deleted": len(self._candidates) - len(referenced_keys or ())}


class _FakeCheckpointStore:
    def __init__(self, referenced: set[str]):
        self._referenced = referenced
        self.collect_calls = 0

    async def collect_externalized_keys(self) -> set[str]:
        self.collect_calls += 1
        return set(self._referenced)


async def test_gc_sweep_skips_reference_scan_when_no_candidates():
    """无删除候选 ⇒ 不查 PG（全表 jsonb_each 有成本，稳态不该每 30s 扫一次）。"""
    from agent_server.main import _make_gc_sweep

    ext = _FakeExternalizer(candidates=[])
    store = _FakeCheckpointStore(referenced=set())
    sweep = _make_gc_sweep(ext, store)

    assert await sweep() is None
    assert store.collect_calls == 0
    assert ext.sweep_calls == []


async def test_gc_sweep_consults_references_before_deleting():
    """有候选 ⇒ 先查引用再删；仍在途的引用不被误删（awaitable resume 场景）。"""
    from agent_server.main import _make_gc_sweep

    ext = _FakeExternalizer(candidates=["payload/a", "payload/b"])
    store = _FakeCheckpointStore(referenced={"payload/b"})
    sweep = _make_gc_sweep(ext, store)

    report = await sweep()
    assert store.collect_calls == 1
    assert ext.sweep_calls == [{"referenced_keys": {"payload/b"}}]
    assert report["deleted"] == 1  # 只删不在引用集里的 payload/a


def test_payload_externalization_enabled_without_dir_fails_fast(_settings_env):
    """开了开关却没给目录 ⇒ 启动即报错，不静默退回"没开"（那会让 JSONB 继续膨胀而无人知）。"""
    from agent_server.main import _build_payload_externalizer

    _settings_env.setenv("PAYLOAD_EXTERNALIZATION_ENABLED", "true")
    _settings_env.delenv("PAYLOAD_EXTERNALIZATION_DIR", raising=False)

    with pytest.raises(RuntimeError, match="PAYLOAD_EXTERNALIZATION_DIR"):
        _build_payload_externalizer()


# ===== 护栏：4 个已转正模块不得再退化为孤岛（roadmap 阶段1 #5 判据的后半句）=====

_WIRED_MODULES = (
    "state_migration",
    "execution_recovery",
    "payload_externalization",
    "human_task",
)


@pytest.mark.parametrize("module_name", _WIRED_MODULES)
def test_wired_module_keeps_a_real_assembly_point_in_main(module_name):
    """main.py 必须仍然引用 `agent_runtime.<module>`，否则该模块的「未接线」立刻复活。

    本文件通篇的判据是装配产物而非「能 import」；但 lifespan 尚未拆成可单测的
    builder（拆它属高风险大函数重构，另见 tech-debt T2.2 items1-4），所以这条
    只能钉装配点的源码锚。它的价值不在证明接线正确，而在**证明接线没有消失**——
    正是 `state_migration` 当年「实现+单测全绿、调用点没传 migrator」那一类失效。
    """
    import inspect

    from agent_server import main

    src = inspect.getsource(main)
    assert f"agent_runtime.{module_name}" in src, (
        f"agent_server/main.py 不再引用 agent_runtime.{module_name}："
        f"该模块已退化为孤岛（能力仍在、装配点没了），请恢复接线而不是改本用例"
    )


def test_no_wired_module_still_claims_itself_unwired():
    """文档护栏：已接线模块的源码不得再声称「仍未接线」。

    实踩过：`execution_recovery.py` 的 docstring 在 payload_externalization /
    human_task 接线后仍写着「仍未接线」，会误导下一个读代码的人（含 agent）
    把已完成项重新列为缺口。
    """
    offenders = [
        name
        for name in _WIRED_MODULES
        if "仍未接线" in (importlib.import_module(f"agent_runtime.{name}").__doc__ or "")
    ]
    assert not offenders, f"以下模块已接线但 docstring 仍声称未接线：{offenders}"
