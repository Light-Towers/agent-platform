# -*- coding: utf-8 -*-
"""WS-5：KernelConfig 与类型化 env 解析单测。"""

from __future__ import annotations

import warnings

from agent_core.config import (
    KernelConfig,
    env_bool,
    env_database_url,
    env_float,
    env_int,
)


def test_env_bool_parses_truthy_falsy(monkeypatch):
    for raw, expected in [
        ("1", True), ("true", True), ("YES", True), ("on", True),
        ("0", False), ("false", False), ("off", False), ("", False),
    ]:
        monkeypatch.setenv("T_BOOL", raw)
        assert env_bool("T_BOOL", False) is expected


def test_env_bool_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("T_BOOL", "maybe")
    assert env_bool("T_BOOL", True) is True
    assert env_bool("T_BOOL", False) is False
    monkeypatch.delenv("T_BOOL")
    assert env_bool("T_BOOL", True) is True  # 未设置取默认


def test_env_int_float_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("T_INT", "abc")
    assert env_int("T_INT", 30) == 30
    monkeypatch.setenv("T_FLOAT", "x.y")
    assert env_float("T_FLOAT", 0.1) == 0.1
    monkeypatch.setenv("T_INT", "7")
    assert env_int("T_INT", 30) == 7
    monkeypatch.setenv("T_FLOAT", "0.25")
    assert env_float("T_FLOAT", 0.1) == 0.25


def test_env_database_url_new_name_priority(monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_DATABASE_URL", "postgresql://new")
    monkeypatch.setenv("DEEPAGENTS_DATABASE_URL", "postgresql://legacy")
    monkeypatch.setenv("DATABASE_URL", "postgresql://generic")
    assert env_database_url() == "postgresql://new"


def test_env_database_url_legacy_warns(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_DATABASE_URL", raising=False)
    monkeypatch.setenv("DEEPAGENTS_DATABASE_URL", "postgresql://legacy")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert env_database_url() == "postgresql://legacy"
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_env_database_url_generic_fallback(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_DATABASE_URL", raising=False)
    monkeypatch.delenv("DEEPAGENTS_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://generic")
    assert env_database_url() == "postgresql://generic"
    monkeypatch.delenv("DATABASE_URL")
    assert env_database_url() == ""


def test_kernel_config_from_env(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_MEMORY_TYPED", "on")
    monkeypatch.setenv("VECTOR_BACKEND", "PG")
    monkeypatch.setenv("MEMORY_FORGET_THRESHOLD", "0.2")
    monkeypatch.setenv("MEMORY_FORGET_AGE_DAYS", "7")
    cfg = KernelConfig.from_env()
    assert cfg.semantic_memory_enabled is True
    assert cfg.semantic_memory_typed is True
    assert cfg.vector_backend == "pg"
    assert cfg.memory_forget_threshold == 0.2
    assert cfg.memory_forget_age_days == 7


def test_kernel_config_defaults():
    cfg = KernelConfig()
    assert cfg.semantic_memory_enabled is False
    assert cfg.memory_forget_threshold == 0.1
    assert cfg.memory_forget_age_days == 30
