"""V3「未接线半成品转正」批的**装配面**与 HTTP 面断言。

对应方案 `docs/plans/plan-v3-unwired-landing-2026-10-15.md` §4 验收 4（项 1）与验收 5。

为什么单独钉装配：本仓反复出现的失效形态是「能力实现存在、单测全绿，但生产装配点没接」
（`state_migration` 就是——迁移链与 `load()` 分支早就写好了，两个调用点都没传 migrator）。
所以这里的判据是**装配产物本身**，不是「模块能 import」。
"""

from __future__ import annotations

import asyncio

from agent_runtime.control_plane import ControlPlane
from agent_runtime.execution_recovery import ReaperConfig, RecoveryOrchestrator
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
    QueueStatus,
)
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
