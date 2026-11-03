"""语义缓存配置/工厂/降级路径单元测试（不依赖真 Valkey）。

真 Valkey 的命中/失效/隔离契约在 ``test_cache_contract.py``（CI 服务容器）。
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

import pytest
from agent_core.memory.embedder import MockEmbedder

from agent_runtime.cache import config as config_module
from agent_runtime.cache.config import (
    CacheConfig,
    CacheConfigError,
    get_cache_config,
    redact_url,
    reset_cache_config,
    safe_token,
)
from agent_runtime.cache.factory import get_cache, reset_cache_for_tests

# 要清的环境变量名**从 config.py 源码里派生**，不手写清单：本仓三次栽在"手写被检清单必漏项"
# （门禁枚举 L-5/P14/L-4）。手写这份清单的失败方式是——CI 机器上恰好有 CACHE_WRITE_QUEUE_MAX
# 时，"默认值钉死"那条用例会以"别人设过配置"的理由红，然后被人加个 skip 掉。
# 引号两种形状都要认：`make mutation` 的往返对照控件（unparse 后套件仍须绿）实测抓到过
# 只认双引号的版本——`ast.unparse` 出来是单引号 ⇒ 派生清单变空 ⇒ 清理静默失效。
_CACHE_ENV_NAMES = tuple(
    sorted(
        set(
            re.findall(
                r'(?:env_(?:bool|int|float|str)|_env_timeout_ms)\(\s*["\']([A-Z][A-Z0-9_]*)["\']',
                pathlib.Path(config_module.__file__).read_text(encoding="utf-8"),
            )
        )
    )
)


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    for name in _CACHE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    reset_cache_config()
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_config()


class TestConfigValidation:
    def test_default_backend_is_valkey(self):
        cfg = CacheConfig()
        assert cfg.backend == "valkey"
        assert cfg.threshold == 0.05
        assert cfg.federation_threshold == 0.08

    def test_pg_backend_fails_fast(self, monkeypatch):
        monkeypatch.setenv("CACHE_BACKEND", "pg")
        with pytest.raises(CacheConfigError, match="已退役"):
            CacheConfig()

    def test_unknown_backend_fails_fast(self, monkeypatch):
        monkeypatch.setenv("CACHE_BACKEND", "redis")
        with pytest.raises(CacheConfigError, match="只接受 valkey / disabled"):
            CacheConfig()

    def test_valkey_url_required(self, monkeypatch):
        monkeypatch.setenv("VALKEY_URL", "")
        with pytest.raises(CacheConfigError, match="VALKEY_URL 为空"):
            CacheConfig()

    def test_bad_scheme_rejected(self, monkeypatch):
        monkeypatch.setenv("VALKEY_URL", "http://localhost:6379/0")
        with pytest.raises(CacheConfigError, match="协议"):
            CacheConfig()

    def test_valkey_scheme_normalized_to_redis(self, monkeypatch):
        monkeypatch.setenv("VALKEY_URL", "valkey://user:secret@localhost:6379/1")
        cfg = CacheConfig()
        assert cfg.valkey_url == "redis://user:secret@localhost:6379/1"
        assert "secret" not in cfg.redacted_url

    def test_non_positive_timeouts_rejected(self, monkeypatch):
        monkeypatch.setenv("CACHE_CONNECT_TIMEOUT_MS", "0")
        with pytest.raises(CacheConfigError, match="CACHE_CONNECT_TIMEOUT_MS"):
            CacheConfig()

    @pytest.mark.parametrize(
        "name,value,needle",
        [
            # 阈值 ≥ 余弦距离上界 = 任何向量都算命中 ⇒ L2 返回不相干答案
            ("CACHE_THRESHOLD", "2.0", "超出余弦距离上界"),
            ("CACHE_THRESHOLD", "10", "超出余弦距离上界"),
            ("CACHE_THRESHOLD_FEDERATION", "3", "超出余弦距离上界"),
            ("CACHE_THRESHOLD", "nan", "超出余弦距离上界"),
            # 排空超时非正 ⇒ 每次优雅关闭都丢队列里未完成的写入（只留一句 warning）
            ("CACHE_WRITE_FLUSH_TIMEOUT", "0", "CACHE_WRITE_FLUSH_TIMEOUT"),
            ("CACHE_WRITE_FLUSH_TIMEOUT", "-1", "CACHE_WRITE_FLUSH_TIMEOUT"),
            # 熔断阈值 0 = 启动即永久 open；恢复时间非正 = 熔断语义坏掉
            ("CACHE_BREAKER_FAILURES", "0", "CACHE_BREAKER_FAILURES"),
            ("CACHE_BREAKER_RECOVERY_SECONDS", "0", "CACHE_BREAKER_RECOVERY_SECONDS"),
            ("CACHE_BREAKER_RECOVERY_SECONDS", "-5", "CACHE_BREAKER_RECOVERY_SECONDS"),
        ],
    )
    def test_values_that_silently_disable_or_distort_the_cache_are_rejected(
        self, monkeypatch, name, value, needle
    ):
        """这些值不报错、只是把功能换成另一种语义——所以必须启动期 fail-fast。

        与 `CACHE_BACKEND=pg` 同一口径：本项目的既有教训是"装了但没接上"最难查
        （读数上什么都正常）。`nan` 那一条走的是同一个判据：`nan < 2.0` 恒假，
        所以写成 `not threshold < 上界` 而不是 `threshold >= 上界`（后者会放过 nan）。
        """
        monkeypatch.setenv(name, value)
        with pytest.raises(CacheConfigError, match=needle):
            CacheConfig()

    def test_loosest_legal_threshold_still_accepted(self, monkeypatch):
        """上界判定不许顺手把合法区间也关掉：1.99 仍应可配（虽然实际会几乎不命中）。"""
        monkeypatch.setenv("CACHE_THRESHOLD", "1.99")
        assert CacheConfig().threshold == pytest.approx(1.99)

    def test_thresholds_and_scope(self):
        cfg = CacheConfig()
        assert cfg.threshold_for("agent_server") == cfg.threshold
        assert cfg.threshold_for("federation") == cfg.federation_threshold

    def test_namespace_partitions_by_scope_model_dim(self):
        cfg = CacheConfig()
        a = cfg.namespace("agent_server", "bge-m3", 1024)
        b = cfg.namespace("agent_server", "bge-small", 512)
        assert a != b and a.endswith(":1024:")
        assert cfg.index_name("agent_server", "bge-m3", 1024) != cfg.index_name(
            "federation", "bge-m3", 1024
        )

    def test_index_name_carries_schema_version_and_cannot_be_overridden(self):
        """同名索引会被无条件复用（建索引前只判在不在、不比对字段），所以 schema 版本
        必须进索引名；而版本 token 必须是类常量——能从环境改回去 = 把部署指回 stale 索引。"""
        cfg = CacheConfig()
        name = cfg.index_name("agent_server", "bge-m3", 1024)
        assert name.endswith(f"_s{CacheConfig.index_schema_version}")
        assert "index_schema_version" not in {f.name for f in dataclasses.fields(CacheConfig)}

    def test_singleton_reads_env_once(self, monkeypatch):
        reset_cache_config()
        first = get_cache_config()
        monkeypatch.setenv("CACHE_BACKEND", "disabled")
        assert get_cache_config() is first
        reset_cache_config()
        assert get_cache_config().backend == "disabled"


class TestRedaction:
    def test_user_and_password(self):
        assert redact_url("redis://user:p%40ss@host:6379/0") == "redis://user:***@host:6379/0"

    def test_empty_user_password_only(self):
        assert redact_url("redis://:topsecret@host:6379/0") == "redis://:***@host:6379/0"

    def test_no_credentials_unchanged(self):
        url = "redis://host:6379/0"
        assert redact_url(url) == url

    def test_safe_token_stable_and_distinct(self):
        assert safe_token("agent_server") == safe_token("agent_server")
        assert safe_token("agent_server") != safe_token("agent-server")
        assert safe_token("Agent Server").startswith("agent_server_")


class TestFactory:
    def test_disabled_backend_selected_by_config(self, monkeypatch):
        monkeypatch.setenv("CACHE_BACKEND", "disabled")
        backend = get_cache("unit")
        assert backend.enabled is False
        assert get_cache("unit") is backend

    def test_enabled_flag_false_forces_disabled(self, monkeypatch):
        monkeypatch.setenv("CACHE_ENABLED", "false")
        monkeypatch.setenv("CACHE_BACKEND", "valkey")
        backend = get_cache("unit")
        assert backend.enabled is False

    @pytest.mark.asyncio
    async def test_disabled_backend_is_pure_noop(self, monkeypatch):
        monkeypatch.setenv("CACHE_BACKEND", "disabled")
        backend = get_cache("unit")
        await backend.startup()
        assert await backend.get(tenant_id="t", intent="i", rewritten_query="q") is None
        await backend.set(tenant_id="t", intent="i", rewritten_query="q", value={"answer": "a"})
        health = await backend.health()
        assert health.backend == "disabled" and health.ready is True
        assert backend.get_stats()["backend"] == "disabled"

    def test_scope_required(self):
        with pytest.raises(CacheConfigError):
            get_cache("")


class TestValkeyFailOpen:
    def _config(self):
        return CacheConfig()

    @pytest.mark.asyncio
    async def test_unreachable_valkey_fails_open(self, monkeypatch):
        """连接不可达：启动不抛错、请求按 miss、health 报 degraded（ADR-0013 C）。"""
        monkeypatch.setenv("VALKEY_URL", "redis://127.0.0.1:1/0")
        monkeypatch.setenv("CACHE_CONNECT_TIMEOUT_MS", "20")
        monkeypatch.setenv("CACHE_COMMAND_TIMEOUT_MS", "20")
        from agent_runtime.cache.valkey_backend import ValkeySemanticCache

        backend = ValkeySemanticCache(self._config(), "unit", embedder=MockEmbedder(dim=8))
        try:
            await backend.startup()
            assert (
                await backend.get(tenant_id="t1", intent="i", rewritten_query="q", embedding=[0.1] * 8)
                is None
            )
            await backend.set(
                tenant_id="t1",
                intent="i",
                rewritten_query="q",
                value={"answer": "a"},
                embedding=[0.1] * 8,
            )
            await backend.flush()
            health = await backend.health()
            assert health.backend == "valkey"
            assert health.ready is False
            assert health.degraded_reason
        finally:
            await backend.aclose()

    @pytest.mark.asyncio
    async def test_empty_tenant_fail_closed_before_any_network(self, monkeypatch):
        monkeypatch.setenv("VALKEY_URL", "redis://127.0.0.1:1/0")
        from agent_runtime.cache.valkey_backend import ValkeySemanticCache

        backend = ValkeySemanticCache(self._config(), "unit", embedder=MockEmbedder(dim=8))
        try:
            assert await backend.get(tenant_id="", intent="i", rewritten_query="q") is None
            await backend.set(tenant_id="", intent="i", rewritten_query="q", value={"answer": "a"})
            stats = backend.get_stats()
            assert stats["skipped_no_tenant"] == 2
        finally:
            await backend.aclose()

    def test_dim_mismatch_fails_fast(self, monkeypatch):
        monkeypatch.setenv("CACHE_VECTOR_DIM", "16")
        from agent_runtime.cache.valkey_backend import ValkeySemanticCache

        with pytest.raises(CacheConfigError, match="embedding 维度不一致"):
            ValkeySemanticCache(self._config(), "unit", embedder=MockEmbedder(dim=8))


class TestGuardsPinnedOnBothSides:
    """全量变异战役（`make mutation`，333 刀）在配置面上留下的存活体反证。

    共同形状：**边界值两侧各钉一次**。`<= 0` 变异成 `< 0` 或 `<= 1`，只有"0 必须报错"
    与"1 必须可用"同时存在才会红；战役前这里只测了"负数报错"那一侧，于是 config.py
    的 47 刀无人认领——包括"写队列上限 1 会被拒"这种把合法值关在门外的改法。
    """

    @pytest.mark.parametrize(
        ("name", "illegal", "needle", "legal"),
        [
            ("CACHE_L1_TTL", "0", "缓存 TTL 必须为正整数", "1"),
            ("CACHE_L2_TTL", "0", "缓存 TTL 必须为正整数", "1"),
            ("CACHE_NULL_TTL", "0", "缓存 TTL 必须为正整数", "1"),
            ("CACHE_CONNECT_TIMEOUT_MS", "0", "CACHE_CONNECT_TIMEOUT_MS", "1"),
            ("CACHE_COMMAND_TIMEOUT_MS", "0", "CACHE_COMMAND_TIMEOUT_MS", "1"),
            ("CACHE_WRITE_QUEUE_MAX", "0", "CACHE_WRITE_QUEUE_MAX", "1"),
            ("CACHE_WRITE_FLUSH_TIMEOUT", "0", "CACHE_WRITE_FLUSH_TIMEOUT", "1"),
            ("CACHE_BREAKER_FAILURES", "0", "CACHE_BREAKER_FAILURES", "1"),
            ("CACHE_BREAKER_RECOVERY_SECONDS", "0", "CACHE_BREAKER_RECOVERY_SECONDS", "1"),
            ("CACHE_VECTOR_DIM", "-1", "CACHE_VECTOR_DIM", "0"),
            ("CACHE_THRESHOLD", "-0.1", "缓存距离阈值不能为负", "0"),
            ("CACHE_THRESHOLD_FEDERATION", "-0.1", "缓存距离阈值不能为负", "0"),
            ("CACHE_THRESHOLD", "2", "超出余弦距离上界", "1.99"),
            ("CACHE_THRESHOLD_FEDERATION", "2", "超出余弦距离上界", "1.99"),
        ],
    )
    def test_guard_boundary_is_pinned_on_both_sides(self, monkeypatch, name, illegal, needle, legal):
        monkeypatch.setenv(name, illegal)
        with pytest.raises(CacheConfigError, match=needle):
            CacheConfig()
        monkeypatch.setenv(name, legal)
        CacheConfig()

    def test_default_values_are_pinned(self):
        """每个默认值都是一条现网口径，改动必须连着这条用例一起改（有意识地改）。

        战役里 18 刀 `3600→3601`、`50→49`、`enabled=True→False` 之类全部存活，原因是没人钉值。
        这类漂移不报错、只换语义（TTL 少 1 秒 = 命中率变化；`CACHE_ENABLED` 默认翻 False =
        整条缓存静默下线），正是本仓记过的"配置面不报错只换语义"同族。
        """
        cfg = CacheConfig()
        assert cfg.enabled is True
        assert cfg.backend == "valkey"
        assert cfg.valkey_url == "redis://localhost:6379/0"
        assert (cfg.l1_ttl_seconds, cfg.l2_ttl_seconds, cfg.null_ttl_seconds) == (3600, 1800, 60)
        assert cfg.negative_cache_enabled is True
        assert cfg.threshold == pytest.approx(0.05)
        assert cfg.federation_threshold == pytest.approx(0.08)
        assert cfg.vector_dim == 0
        assert cfg.embedding_model == ""
        assert (cfg.connect_timeout_ms, cfg.command_timeout_ms) == (50, 100)
        assert cfg.write_queue_max == 1000
        assert cfg.write_flush_timeout_seconds == pytest.approx(5.0)
        assert cfg.breaker_failure_threshold == 3
        assert cfg.breaker_recovery_seconds == pytest.approx(15.0)
        assert cfg.key_prefix == "cache:sc:v1"
        assert CacheConfig.index_schema_version == 2

    def test_env_cleanup_covers_every_env_reading_field(self):
        """派生清单的自检：读环境变量的字段若不在清理集合里，"默认值钉死"就会看机器脸色。"""
        src = pathlib.Path(config_module.__file__).read_text(encoding="utf-8").splitlines()
        factory_lines = [line for line in src if "field(default_factory=" in line]
        assert factory_lines, "config.py 已无 default_factory 字段？这条自检要跟着改形状"
        uncovered = [
            line.strip()
            for line in factory_lines
            if not any(name in line for name in _CACHE_ENV_NAMES)
        ]
        assert not uncovered, f"这些字段读环境变量但清理清单里没有它：{uncovered}"

    def test_safe_token_pins_slug_and_digest_lengths(self):
        """token = 可读 slug[:40] + 全串摘要[:8]。摘要是唯一防碰撞的那一段，长度不许漂。"""
        token = safe_token("x" * 100)
        slug, digest = token.rsplit("_", 1)
        assert len(slug) == 40 and len(digest) == 8
        assert int(digest, 16) >= 0
        # slug 只留前 40 字符，防碰撞全靠摘要取自**全串**：两个前 40 字符相同的 scope
        # 若摘要也相同，就会撞进同一个命名空间/索引（本文件另两条命名用例查的是同一族缺陷）。
        a = safe_token("y" * 100)
        b = safe_token("y" * 100 + "z")
        assert a.split("_")[0] == b.split("_")[0], "slug 截断后前缀应当相同（否则钉长度这条无意义）"
        assert a != b, "摘要取自全串：前 40 字符相同就撞名才是缺陷"
        assert safe_token("y" * 100) == a, "同一输入必须得到同一 token（命名空间可复现）"

    def test_config_is_frozen(self):
        """配置是不可变快照（进程级单例被多处持有）；去掉 frozen 会让一处改值全局生效。"""
        cfg = CacheConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.l1_ttl_seconds = 1


class TestClosePath:
    @pytest.mark.asyncio
    async def test_one_failing_backend_does_not_block_the_rest_and_logs_the_traceback(self, monkeypatch):
        """优雅关闭路径上的 `except Exception` 是退出期的兜底，必须有反证。

        战役里 factory.py 的 `exc_info=True → False` 存活：没有任何用例检查过"关闭失败
        到底留下什么读数"。这条同时钉三件事——异常被吞而不外抛、其余后端仍然被关闭、
        日志带 traceback（否则线上只有一句 warning，查不到原因）。
        """
        from agent_runtime.cache import factory

        closed: list[str] = []
        records: list[tuple] = []

        class _Ok:
            async def aclose(self) -> None:
                closed.append("ok")

        class _Boom:
            async def aclose(self) -> None:
                closed.append("boom")
                msg = "连接已断"
                raise RuntimeError(msg)

        def _capture(*args, **kwargs):
            records.append((args, kwargs))

        factory._BACKENDS.clear()
        factory._BACKENDS["a"] = _Ok()
        factory._BACKENDS["b"] = _Boom()
        monkeypatch.setattr(factory.logger, "warning", _capture)
        try:
            await factory.close_cache()
        finally:
            factory._BACKENDS.clear()

        assert closed == ["ok", "boom"], "单个后端失败必须继续清理其余后端"
        assert len(records) == 1, "关闭失败必须留下恰好一条 warning"
        args, kwargs = records[0]
        assert "关闭语义缓存后端失败" in args[0]
        assert kwargs.get("exc_info") is True, "退出期异常不许静默吞掉堆栈"
        assert not factory._BACKENDS, "关闭后要清空单例表，否则重启会复用已关闭的后端"

