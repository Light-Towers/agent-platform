"""健康检查字段的真值契约（演示版 A.1 #1/#2，第 2 天）。

刻意**不断言写死值**：每个字段都与"运行态/配置的实际来源"比对，拨开关必须跟着变。
判据来源：A.1 #2 的验收条（切 SCHEDULER_ENABLED 返回值必须变；API_KEY 未配时
auth_enabled 必须 false；/health 耗时不得因预热上涨）。

注意 get_settings 是 @lru_cache，且 lifespan 每次进入 TestClient 都会重跑——
所以每次改 env 后必须清缓存再进 with，否则读到的是上一次的 settings 快照。
"""

from __future__ import annotations

import time

import pytest
from agent_server.main import app
from agent_server.schemas import HealthResponse
from fastapi.testclient import TestClient

NEW_FIELDS = (
    "scheduler", "control_plane", "cost_governance", "forensic",
    "embedding_backend", "embedding_real", "planner",
    "guard_enabled", "auth_enabled", "identity_mode",
)

_SWITCHES = (
    "SCHEDULER_ENABLED", "API_KEY", "SINGLE_TENANT", "GUARD_ENABLED",
    "DEPLOY_ENFORCE_IDENTITY", "LLM_PUBLIC_KEY",
)


@pytest.fixture(autouse=True)
def _clean_switch_env():
    """用例前后都清 env + 清 settings 缓存，避免 lru_cache 与 env 跨用例泄漏。"""
    import os

    for key in _SWITCHES:
        os.environ.pop(key, None)
    _clear_cache()
    yield
    for key in _SWITCHES:
        os.environ.pop(key, None)
    _clear_cache()


def _clear_cache() -> None:
    import agent_server.config as cfg

    cfg.get_settings.cache_clear()


def _health_with(monkeypatch, **env) -> dict:
    """设 env → 清缓存 → 起一遍 lifespan → 取 /health。"""
    for key in _SWITCHES:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _clear_cache()
    with TestClient(app) as client:
        return client.get("/health").json()


class TestHealthFieldShape:
    def test_new_fields_are_declared_on_app_subclass_not_shared_base(self):
        """字段必须加在本 app 的子类上：共享基类被另外三个服务直接返回，
        加在基类等于让它们报出一堆自己并没有的部件。"""
        from shared_schemas.health import HealthResponse as BaseHealthResponse

        own = set(HealthResponse.model_fields) - set(BaseHealthResponse.model_fields)
        assert own == set(NEW_FIELDS), own

    def test_response_carries_all_new_fields(self):
        with TestClient(app) as client:
            data = client.get("/health").json()
        for key in NEW_FIELDS:
            assert key in data, f"/health 缺字段 {key}"


class TestHealthReflectsRuntimeState:
    def test_scheduler_and_control_plane_follow_assembly(self, monkeypatch):
        """值取自"是否已装配"，不是 settings 复述意愿值。"""
        off = _health_with(monkeypatch)
        on = _health_with(monkeypatch, SCHEDULER_ENABLED="true")

        assert (off["scheduler"], on["scheduler"]) == (False, True)
        assert (off["control_plane"], on["control_plane"]) == (False, True)

    def test_auth_enabled_tracks_api_key_and_never_echoes_it(self, monkeypatch):
        off = _health_with(monkeypatch)
        probe_value = "probe-secret-must-not-appear"
        monkeypatch.setenv("API_KEY", probe_value)
        _clear_cache()
        with TestClient(app) as client:
            resp = client.get("/health")

        assert (off["auth_enabled"], resp.json()["auth_enabled"]) == (False, True)
        # /health 是免鉴权探针路径：只报布尔，密钥本体不得出现在响应里
        assert probe_value not in resp.text

    def test_identity_mode_uses_the_same_judgement_as_startup_guard(self, monkeypatch):
        """与 lifespan 的 require_identity_startup_guard 同一函数，不另建一套判定。"""
        from agent_runtime.identity import resolve_startup_tenant_mode

        off = _health_with(monkeypatch)
        assert off["identity_mode"] == resolve_startup_tenant_mode()[0]

        on = _health_with(monkeypatch, SINGLE_TENANT="demo-tenant")
        assert on["identity_mode"] == "single"
        assert on["identity_mode"] != off["identity_mode"]

    def test_guard_enabled_tracks_switch(self, monkeypatch):
        off = _health_with(monkeypatch)
        on = _health_with(monkeypatch, GUARD_ENABLED="true")
        assert (off["guard_enabled"], on["guard_enabled"]) == (False, True)


class TestEmbedBackendIsNotComputedInProbePath:
    def test_probe_path_does_not_resolve_embedder(self):
        """/health 只读 lifespan 预热好的已存值。

        关键：预热**本就该**在 lifespan 调一次 resolve_provider（那是正确落点），
        所以替身必须在 app 起来之后再装，否则测到的是启动期那一次、而非探针路径。
        """
        import agent_server.rag.embed as embed_mod

        calls = {"n": 0}

        def _boom(*a, **k):
            calls["n"] += 1
            raise AssertionError("探针路径不得解析 embedder（等于在探针里装 torch）")

        orig = embed_mod.resolve_provider
        try:
            with TestClient(app) as client:  # 先起 lifespan（这里会正常预热一次）
                embed_mod.resolve_provider = _boom
                data = client.get("/health").json()
        finally:
            embed_mod.resolve_provider = orig

        assert calls["n"] == 0
        assert data["embedding_backend"], "预热值缺失时应报 unknown 而非空"

    def test_warmup_failure_degrades_to_honest_red_light(self, monkeypatch):
        """预热失败不得静默装绿：backend=unknown + real=false，且服务照常起。"""
        import agent_server.rag.embed as embed_mod

        orig = embed_mod.resolve_provider
        monkeypatch.setattr(embed_mod, "resolve_provider", _raise_runtime_error)
        try:
            _clear_cache()
            with TestClient(app) as client:
                data = client.get("/health").json()
        finally:
            monkeypatch.setattr(embed_mod, "resolve_provider", orig)

        assert data["embedding_backend"] == "unknown"
        assert data["embedding_real"] is False

    def test_health_stays_millisecond_scale_after_warmup(self):
        """预热完的 /health 必须仍在毫秒级（防止把模型加载隐式拖回探针路径）。"""
        with TestClient(app) as client:
            client.get("/health")  # 排除首请求噪声
            samples = []
            for _ in range(20):
                t0 = time.perf_counter()
                client.get("/health")
                samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        assert samples[10] < 100, f"/health median={samples[10]:.1f}ms，疑似把模型加载放进了探针路径"


def _raise_runtime_error(*a, **k):
    raise RuntimeError("模拟：EMBEDDING_REQUIRE_REAL=true 且后端退化为 Mock")
