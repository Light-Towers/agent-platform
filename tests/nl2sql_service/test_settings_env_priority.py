"""配置优先级用例（#105）：env/.env > YAML > Field 默认。

修复前的形状：`get_settings()` 把 YAML 值作 init kwargs 传给 `Settings(**overrides)`，
而 pydantic-settings 的 init kwargs 优先级**高于** env/.env ⇒ app_config.yaml 写死的
键（如 pool.meta.max_size=20）会把 `META_DB_POOL_MAX_SIZE` 环境变量静默压掉
（实测 env=7 得 20，无报错无提示）。本文件钉死修复后的三级优先级。
"""

from __future__ import annotations

from nl2sql_service.conf.settings import get_settings


def _fresh_settings():
    """绕开 lru_cache 取一次全新构造（env 改动只在缓存清零后生效）。"""
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_env_beats_yaml_pool_key(monkeypatch):
    """app_config.yaml 写死 meta.max_size=20 ⇒ env 显式设置必须胜出（#105 核心）。"""
    monkeypatch.setenv("META_DB_POOL_MAX_SIZE", "7")
    s = _fresh_settings()
    assert s.meta_db_pool_max_size == 7


def test_env_beats_yaml_non_pool_key(monkeypatch):
    """压制不限于 pool 段——检索段同样修复（rrf_k YAML=60）。"""
    monkeypatch.setenv("RRF_K", "99")
    s = _fresh_settings()
    assert s.rrf_k == 99


def test_yaml_applies_when_env_absent():
    """env 缺位时 YAML 显式键仍生效（"配置面统一"功能不倒退）。"""
    s = _fresh_settings()
    assert s.meta_db_pool_max_size == 20, "env 未设置时应取 app_config.yaml 的显式值"
    assert s.rrf_k == 60


def test_env_applies_for_yaml_absent_field(monkeypatch):
    """YAML 未声明的字段（llm_api_key）：env 照常生效，探针机制不误伤。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    s = _fresh_settings()
    assert s.llm_api_key == "sk-test"
