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


class TestHealthReportsItsOwnDataPlane:
    """`sql_backend` 自 2026-10-28（批次 5）由本服务上报。

    本组的成因：那一位原先住在 agent_server，而它读的 DSN 指**平台库**——报出来的
    postgres 只证明“平台能连自己的库”，与问数能不能答无关（ADR-0011 后续修订）。
    本服务的 dw DSN 才是这个位的真读点，所以灯跟数据面住在一起。
    """

    @staticmethod
    def _health(settings) -> dict:
        from unittest.mock import patch

        from nl2sql_service.api import server

        with patch("nl2sql_service.conf.settings.get_settings", return_value=settings):
            return TestClient(server.create_app()).get("/health").json()

    def test_scheme_decides_the_dialect(self):
        from unittest.mock import MagicMock

        s = MagicMock(dw_db_enabled=True, dw_db_dsn="mysql://u:p@dw:3306/reporting", datasource_dialect="")
        assert self._health(s)["sql_backend"] == "mysql"

    def test_explicit_dialect_wins_over_scheme(self):
        """与建默认源时同一口径（dependencies.py 的 `datasource_dialect or detect_dialect`）。"""
        from unittest.mock import MagicMock

        s = MagicMock(dw_db_enabled=True, dw_db_dsn="mysql://u:p@dw:3306/reporting", datasource_dialect="doris")
        assert self._health(s)["sql_backend"] == "doris"

    def test_null_when_no_data_plane_configured(self):
        """没配 dw 必须报 null，不能报回落值：`detect_dialect("")` 给的是 postgres，
        把它当读数就是把“没有数据面”说成“有个 pg 可问”。"""
        from unittest.mock import MagicMock

        for settings in (
            MagicMock(dw_db_enabled=False, dw_db_dsn="", datasource_dialect=""),
            MagicMock(dw_db_enabled=True, dw_db_dsn="", datasource_dialect=""),
        ):
            assert self._health(settings)["sql_backend"] is None, settings.dw_db_dsn
