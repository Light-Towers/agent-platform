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
    # Langfuse 两盏灯（方案 plan-langfuse-wiring §2.2）：enabled=配置意愿，ready=真装配。
    "langfuse_enabled", "langfuse_ready",
    # 语义缓存（ADR-0013 C）：backend=实际后端，ready=连得上，reason=降级原因（已脱敏）。
    # stats=命中率与分账计数（Stage 4 判据「命中率可在 health 读到」；契约模型固定形状，
    # 取数是纯内存读，不在探针路径发命令）。
    "cache_backend", "cache_ready", "cache_degraded_reason", "cache_stats",
    # 问数子代理注册位（2026-10-28 批次 5）：它替掉的不是 sql_backend（那位在共享基类上
    # 归“拥有业务库数据面的服务”所有），而是平台侧“问数到底走不走子代理”这个真问题。
    "nl2sql",
)

_SWITCHES = (
    "SCHEDULER_ENABLED", "API_KEY", "SINGLE_TENANT", "GUARD_ENABLED",
    "DEPLOY_ENFORCE_IDENTITY", "LLM_PUBLIC_KEY",
    "LLM_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
    "COST_GOVERNANCE_ENABLED",
    # 不列进来会有一个假阴：上一条用例给它 setenv 后泄到下一条，“未配置”用例读到 true。
    "NL2SQL_SERVICE_URL", "SQL_DSN",
)
_CACHE_ENV = ("CACHE_ENABLED", "CACHE_BACKEND", "VALKEY_URL",
              "CACHE_CONNECT_TIMEOUT_MS", "CACHE_COMMAND_TIMEOUT_MS")


@pytest.fixture(autouse=True)
def _clean_switch_env():
    """用例前后都清 env + 清 settings/缓存配置单例，避免跨用例泄漏。

    缓存默认 ``disabled``：这些用例验的是装配态，不应依赖本机有没有 Valkey。
    需要真后端行为的用例自行覆盖 ``CACHE_BACKEND``/``VALKEY_URL``。
    """
    import os

    for key in (*_SWITCHES, *_CACHE_ENV):
        os.environ.pop(key, None)
    os.environ["CACHE_BACKEND"] = "disabled"
    _clear_cache()
    _reset_cache()
    yield
    for key in (*_SWITCHES, *_CACHE_ENV):
        os.environ.pop(key, None)
    _clear_cache()
    _reset_cache()


def _reset_cache() -> None:
    from agent_runtime.cache import reset_cache_config, reset_cache_for_tests

    reset_cache_config()
    reset_cache_for_tests()


def _clear_cache() -> None:
    import agent_server.config as cfg

    cfg.get_settings.cache_clear()


def _health_with(monkeypatch, **env) -> dict:
    """设 env → 清缓存 → 起一遍 lifespan → 取 /health。

    本文件的缓存用例默认以 ``CACHE_BACKEND=disabled`` 运行（不依赖本机 Valkey）；
    要验 valkey 形态就在 ``env`` 里显式传 ``CACHE_BACKEND="valkey"`` 与不可达的
    ``VALKEY_URL``。
    """
    for key in _SWITCHES:
        monkeypatch.delenv(key, raising=False)
    env.setdefault("CACHE_BACKEND", "disabled")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _clear_cache()
    _reset_cache()
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


class TestCacheHealth:
    """ADR-0013 C：/health 必须如实报缓存后端与降级原因，且不泄漏凭据。"""

    def test_disabled_backend_is_ready_without_reason(self, monkeypatch):
        data = _health_with(monkeypatch, CACHE_BACKEND="disabled")
        assert data["cache_backend"] == "disabled"
        assert data["cache_ready"] is True
        assert data["cache_degraded_reason"] is None

    def test_enabled_false_wins_over_valkey(self, monkeypatch):
        data = _health_with(
            monkeypatch, CACHE_ENABLED="false", CACHE_BACKEND="valkey"
        )
        assert data["cache_backend"] == "disabled"
        assert data["cache_ready"] is True

    def test_unreachable_valkey_reports_degraded_without_password(self, monkeypatch):
        password = "probe-cache-password-must-not-appear"
        data = _health_with(
            monkeypatch,
            CACHE_BACKEND="valkey",
            VALKEY_URL=f"redis://:{password}@127.0.0.1:1/0",
            CACHE_CONNECT_TIMEOUT_MS="20",
            CACHE_COMMAND_TIMEOUT_MS="20",
        )
        assert data["cache_backend"] == "valkey"
        assert data["cache_ready"] is False
        assert data["cache_degraded_reason"], "降级必须有原因"
        assert password not in data["cache_degraded_reason"]


class TestHealthReflectsRuntimeState:
    def test_scheduler_and_control_plane_follow_assembly(self, monkeypatch):
        """值取自"是否已装配"，不是 settings 复述意愿值。"""
        off = _health_with(monkeypatch)
        on = _health_with(monkeypatch, SCHEDULER_ENABLED="true")

        assert (off["scheduler"], on["scheduler"]) == (False, True)
        assert (off["control_plane"], on["control_plane"]) == (False, True)

    def test_cost_governance_follows_assembly(self, monkeypatch):
        """补 TODO §3 残差①：cost_governance 此前只有"字段存在"的断言，没有"拨开关必须变"。"""
        off = _health_with(monkeypatch)
        on = _health_with(monkeypatch, COST_GOVERNANCE_ENABLED="true")

        assert (off["cost_governance"], on["cost_governance"]) == (False, True)

    def test_forensic_tracks_trajectory_store_in_both_directions(self, monkeypatch):
        """补 TODO §3 残差①：forensic 同样缺"输入变则值变"的断言。

        forensic 的真相源是 ``planner_runtime.trajectory_store``（`schemas.py` 的字段
        description 已如此声明，控制台也按"过程档案 已装配/未装配"渲染），**不是**某个
        ForensicContext 单例——agent_server 侧压根没有这样一个装配体（`ForensicContext`
        是 agent_runtime 里逐步取证的数据载体，不是服务）。所以这里直接翻该字段的输入。

        刻意不拨 DATABASE_URL：那会让 lifespan 真去连库（本机无 PG），测到的会是连接失败
        而不是装配态。
        """
        for key in _SWITCHES:
            monkeypatch.delenv(key, raising=False)
        _clear_cache()
        with TestClient(app) as client:
            runtime = app.state.planner_runtime
            original = runtime.trajectory_store
            try:
                # 无 DB 的默认形态：trajectory_store 未装配 ⇒ 灯必须是红的
                assert original is None
                assert client.get("/health").json()["forensic"] is False

                runtime.trajectory_store = object()
                assert client.get("/health").json()["forensic"] is True

                runtime.trajectory_store = None
                assert client.get("/health").json()["forensic"] is False
            finally:
                runtime.trajectory_store = original

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


class TestLangfuseLights:
    """两盏灯必须能区分"没配"与"配了但没接上"——合成一盏就是重蹈 llm 位的覆辙。"""

    _CREDS = {
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        "LANGFUSE_SECRET_KEY": "sk-lf-test",
        "LANGFUSE_HOST": "http://127.0.0.1:3000",
    }

    def test_enabled_only_means_three_keys_nonempty(self, monkeypatch):
        """没有 LLM 就没有可挂载的模型：enabled 可以为 true，ready 必须 false。"""
        off = _health_with(monkeypatch)
        on = _health_with(monkeypatch, **self._CREDS)

        assert (off["langfuse_enabled"], on["langfuse_enabled"]) == (False, True)
        # 这一对 (true, false) 正是"配了但没接上"的唯一现场信号
        assert (on["langfuse_enabled"], on["langfuse_ready"]) == (True, False)

    def test_ready_tracks_actual_callback_assembly_not_config(self, monkeypatch):
        """ready 取自构造期真挂上的 callbacks（装配点唯一：agent/llm.py:build_chat_model）。

        替身必须与真实协作者同接口：get_langfuse_callbacks 返回 **BaseCallbackHandler
        实例的 list**。第一版这里塞的是字符串哨兵，被 ChatOpenAI 的 pydantic 校验
        （callbacks.is-instance[BaseCallbackManager]）当场拒绝——那测的是我的替身，
        不是被测代码。
        """
        import agent_runtime.tracing as tracing_mod
        from langchain_core.callbacks import BaseCallbackHandler

        class _SentinelHandler(BaseCallbackHandler):
            """真实 handler 的最小同接口替身（只要求是 BaseCallbackHandler 实例）。"""

        env = {"LLM_API_KEY": "sk-test-must-not-appear", **self._CREDS}

        orig = tracing_mod.get_langfuse_callbacks
        tracing_mod.get_langfuse_callbacks = lambda **kw: [_SentinelHandler()]
        try:
            data = _health_with(monkeypatch, **env)
        finally:
            tracing_mod.get_langfuse_callbacks = orig

        assert (data["langfuse_enabled"], data["langfuse_ready"]) == (True, True)

    def test_import_failure_keeps_ready_red(self, monkeypatch):
        """包没装/初始化失败时（tracing 返回空列表）ready 必须 false，服务照常起。"""
        import agent_runtime.tracing as tracing_mod

        orig = tracing_mod.get_langfuse_callbacks
        tracing_mod.get_langfuse_callbacks = lambda **kw: []
        try:
            data = _health_with(monkeypatch, LLM_API_KEY="sk-test", **self._CREDS)
        finally:
            tracing_mod.get_langfuse_callbacks = orig

        assert (data["langfuse_enabled"], data["langfuse_ready"]) == (True, False)

    def test_probe_path_does_not_build_a_langfuse_client(self, monkeypatch):
        """灯在启动期算一次；/health 里绝不再调 get_langfuse_callbacks。

        与 embedder 预热同一条红线：那会让每次探针构造一个 Langfuse 客户端，
        而集群探针 timeoutSeconds=1、liveness 连错 3 次即杀容器。
        """
        import agent_runtime.tracing as tracing_mod

        calls = {"n": 0}

        def _boom(**kw):
            calls["n"] += 1
            raise AssertionError("探针路径不得构造 Langfuse 客户端")

        orig = tracing_mod.get_langfuse_callbacks
        try:
            with TestClient(app) as client:  # lifespan 正常跑一次（那一次是允许的）
                tracing_mod.get_langfuse_callbacks = _boom
                client.get("/health").json()
        finally:
            tracing_mod.get_langfuse_callbacks = orig

        assert calls["n"] == 0

    def test_health_never_echoes_langfuse_credentials(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "llm-secret-must-not-appear")
        for key, value in self._CREDS.items():
            monkeypatch.setenv(key, value + "-must-not-appear")
        _clear_cache()
        with TestClient(app) as client:
            resp = client.get("/health")

        for value in list(self._CREDS.values()) + ["llm-secret-must-not-appear"]:
            assert value not in resp.text


class TestNl2sqlBit:
    """问数位（2026-10-28 批次 5）：只回答“子代理注册了没”，平台不再代报问数方言。"""

    def test_bit_follows_the_service_url_switch(self, monkeypatch):
        """拨 NL2SQL_SERVICE_URL 必须跟着变（本文件的总前提：不写死值）。"""
        assert _health_with(monkeypatch)["nl2sql"] is False
        data = _health_with(monkeypatch, NL2SQL_SERVICE_URL="http://nl2sql-service:8000")
        assert data["nl2sql"] is True

    def test_bit_does_not_echo_the_url(self, monkeypatch):
        """/health 是免鉴权探针路径：只报位、不回显服务地址（与 auth_enabled 同一口径）。"""
        data = _health_with(monkeypatch, NL2SQL_SERVICE_URL="http://nl2sql-service:8000")
        assert "nl2sql-service" not in str(data), f"/health 回显了服务地址：{data}"

    def test_platform_does_not_report_sql_backend(self, monkeypatch):
        """假灯本体回归：平台侧 sql_backend 必须永远为 null，即使有人还把 SQL_DSN 注进来。

        2026-10-28 之前这里是 `detect_dialect(settings.sql_dsn)`：而那份 DSN 指**平台库**，
        报出来的 postgres 只证明“平台能连自己的库”，与问数能不能答无关（部署清单已在
        批次 4 摘掉该注入，本轮把读它的字段与灯一并退役）。
        """
        data = _health_with(
            monkeypatch, SQL_DSN="postgresql://u:p@platform-db/app", NL2SQL_SERVICE_URL="http://nl2sql-service:8000"
        )
        assert data["sql_backend"] is None, (
            "平台又开始报 sql_backend：这个位的语义属于持有业务库连接的服务（现 nl2sql-service），"
            "平台把它报成非 null 就是把平台库的读数当成问数读数"
        )


def _raise_runtime_error(*a, **k):
    raise RuntimeError("模拟：EMBEDDING_REQUIRE_REAL=true 且后端退化为 Mock")
