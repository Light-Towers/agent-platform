"""nl2sql-service 身份门卫装配用例（roadmap 阶段2 #11）。

装配**行为**在 `packages/agent-runtime/tests/test_identity_assembly.py` 测一次；
本文件钉「本服务的 app 挂着共享中间件」+「`/health` 的共享契约形状没被改动」。

注意本服务的租户隔离还有一件没做的事：它的源码里**根本没有租户维度**（契约有
``tenant_id`` 字段但从不读），所以"接了门卫"只等于断言开始产生，不等于数据已按租户隔离
⇒ 见 docs/plans/plan-identity-gate-6of6-2026-10-16.md §5.2（待拍板）。
"""

from __future__ import annotations

from agent_runtime.identity_middleware import IdentityMiddleware
from fastapi.testclient import TestClient
from nl2sql_service.api.server import create_app


def test_create_app_carries_the_shared_identity_middleware():
    app = create_app()
    classes = [m.cls for m in app.user_middleware]
    assert IdentityMiddleware in classes, (
        f"nl2sql-service 的 app 上没有 IdentityMiddleware，实际中间件栈={classes}。"
        "装配入口：agent_runtime.identity_assembly.mount_identity_gate(app, \"nl2sql-service\")"
    )


def test_health_route_stays_on_shared_contract():
    """/health 仍是共享 ``HealthResponse`` 形状（本服务属于 CONFORMING 面）。

    只断言"必须是共享契约"的那几个键：`HealthResponse` 还带四个可选部件位
    （roadmap #6 的报数面），逐字相等会把契约的正常扩展当回归。
    """
    body = TestClient(create_app()).get("/health").json()
    assert body["status"] == "healthy", body
    assert body["version"] == "0.1.0", body
    assert body["dependencies"] == [], body
    assert "storage" in body and "llm" in body, f"共享契约的部件位缺失：{sorted(body)}"


def test_health_route_ignores_unverifiable_credential():
    client = TestClient(create_app())
    r = client.get("/health", headers={"Authorization": "***"})
    assert r.status_code == 200, r.text
