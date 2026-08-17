# -*- coding: utf-8 -*-
"""get_checkpointer 工厂：统一 checkpointer 选型与降级（类比 get_embedder）。"""

from __future__ import annotations

import importlib

import pytest


def test_get_checkpointer_falls_back_to_inmemory_without_mongo(monkeypatch):
    """无 MONGO_URL 时返回 langgraph InMemorySaver（开发/无持久化环境）。"""
    monkeypatch.delenv("MONGO_URL", raising=False)
    from langgraph.checkpoint.memory import InMemorySaver

    from agent_core.memory import get_checkpointer

    cp = get_checkpointer()
    assert isinstance(cp, InMemorySaver)


def test_get_checkpointer_uses_mongo_when_configured(monkeypatch):
    """配置 MONGO_URL 时：有 pymongo 返回 MongoCheckpointer；否则优雅降级。

    降级路径本身也是正确行为（CI 常无 pymongo），故两种情形都断言通过。
    """
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB", "deepagents_test")
    monkeypatch.setenv("MONGO_CHECKPOINT_COLLECTION", "langgraph_checkpoints")
    monkeypatch.setenv("TENANT_ID", "unit")

    from langgraph.checkpoint.memory import InMemorySaver

    from agent_core.memory import MongoCheckpointer, get_checkpointer

    cp = get_checkpointer()
    if _pymongo_available():
        assert isinstance(cp, MongoCheckpointer)
        assert cp._tenant_id == "unit"
        assert cp._db.name == "deepagents_test"
    else:
        # 无 pymongo 依赖时，工厂必须降级而非抛错
        assert isinstance(cp, InMemorySaver)


def _pymongo_available() -> bool:
    try:
        import pymongo  # noqa: F401

        return True
    except ImportError:
        return False


def test_get_checkpointer_degrades_on_mongo_failure(monkeypatch):
    """MONGO_URL 配置但连接/依赖失败时，降级为 InMemorySaver 而非抛错。"""
    monkeypatch.setenv("MONGO_URL", "mongodb://unreachable:27017")

    from langgraph.checkpoint.memory import InMemorySaver

    from agent_core.memory import get_checkpointer

    # 隔离 pymongo 以模拟依赖缺失/连接失败 -> 工厂必须优雅降级
    import builtins

    real_import = builtins.__import__

    def _block_pymongo(name, *args, **kwargs):
        if name == "pymongo" or name.startswith("pymongo."):
            raise ImportError("pymongo blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_pymongo)
    try:
        cp = get_checkpointer()
    finally:
        monkeypatch.setattr(builtins, "__import__", real_import)

    assert isinstance(cp, InMemorySaver)


def test_get_checkpointer_is_exported():
    """工厂在 agent_core.memory 公共命名空间中可见。"""
    mem = importlib.import_module("agent_core.memory")
    assert hasattr(mem, "get_checkpointer")
