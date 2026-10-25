"""kefu-service 身份门卫装配用例（roadmap 阶段2 #11）。

装配的**行为**由 `packages/agent-runtime/tests/test_identity_assembly.py` 覆盖（单一实现只测一次）；
本文件只钉两件事：① 本服务的 app 上真的挂着共享中间件（防装配点被删/漏接）；
② 挂了之后健康检查的形状没变（`/health` 在 skip 面内，且本服务此前零门卫 ⇒ 无历史凭据语义可破坏）。
"""

from __future__ import annotations

from agent_runtime.identity_middleware import IdentityMiddleware
from fastapi.testclient import TestClient
from kefu_agent.__main__ import app


def _middleware_classes() -> list:
    return [m.cls for m in app.user_middleware]


def test_service_app_carries_the_shared_identity_middleware():
    """必须是 agent-runtime 的共享实现，不是本服务自己另写一套（#11 的"单一实现"层）。"""
    assert IdentityMiddleware in _middleware_classes(), (
        f"kefu-service 的 app 上没有 IdentityMiddleware，实际中间件栈={_middleware_classes()}。"
        "装配入口：agent_runtime.identity_assembly.mount_identity_gate(app, \"kefu-service\")"
    )


def test_health_route_shape_unchanged_by_the_gate():
    client = TestClient(app)
    body = client.get("/health").json()
    assert body == {"status": "ok", "service": "kefu-service", "phase": "7"}, (
        f"/health 形状被门卫改动：{body}（本服务属遗留约定，见 tests/test_health_contract_consistency.py）"
    )


def test_health_route_ignores_unverifiable_credential():
    """/health 属于 skip 面：带个 JWT 形的怪凭据也必须 200（就绪探针不能被打断）。"""
    client = TestClient(app)
    r = client.get("/health", headers={"Authorization": "***"})
    assert r.status_code == 200, r.text


def test_documented_launch_target_resolves():
    """文档里的启动目标必须真能解析（README / `.env.example` / 本模块 docstring 三处同写法）。

    2026-10-16 实测：三处原本都写 `uvicorn kefu_agent:app`，而 `kefu_agent/__init__.py`
    不导出 `app` ⇒ uvicorn 报 `Attribute "app" not found in module "kefu_agent"`，
    照文档命令根本起不来服务。本用例把"文档命令可执行"钉成事实，防止再次漂移。
    """
    from uvicorn.importer import import_from_string

    assert import_from_string("kefu_agent.__main__:app") is app

class TestTenantAssertionT22:
    """T2.2/G6：租户来源收口到 server_tenant_id()——body 自报值仅作比对（软模式）。"""

    def test_body_tenant_mismatch_warns_and_uses_asserted(self, caplog):
        """body 自报 spoofed 租户 ⇒ WARNING（含 body/asserted 双值），数据落断言租户。"""
        import logging

        client = TestClient(app)
        with caplog.at_level(logging.WARNING):
            r = client.post(
                "/invoke",
                json={"query": "你好", "tenant_id": "spoofed", "session_id": "s1"},
            )
        assert r.status_code == 200, r.text
        warned = [rec for rec in caplog.records if "与服务端断言不一致" in rec.message]
        assert warned, "body 与断言不一致必须留 WARNING（软模式观测面）"
        assert "spoofed" in warned[0].getMessage()
        assert "default" in warned[0].getMessage()

    def test_body_tenant_absent_no_warning(self, caplog):
        """body 未自报租户（正常情况）不刷 WARNING。"""
        import logging

        client = TestClient(app)
        with caplog.at_level(logging.WARNING):
            r = client.post(
                "/invoke",
                json={"query": "你好", "session_id": "s2"},
            )
        assert r.status_code == 200, r.text
        assert not any("与服务端断言不一致" in rec.message for rec in caplog.records)
