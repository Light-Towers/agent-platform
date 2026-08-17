# -*- coding: utf-8 -*-
"""get_checkpointer 工厂：统一 checkpointer 选型与降级（类比 get_embedder）。"""

from __future__ import annotations

import asyncio
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


def _pg_postgres_saver_available() -> bool:
    """探测 langgraph postgres aio 扩展是否可导入（CI 常缺，缺则跳过 PG 分支测试）。"""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401

        return True
    except Exception:
        return False


def test_get_checkpointer_uses_pg_pool_when_provided(monkeypatch):
    """传入 pg_pool 时返回 AsyncPostgresSaver（app 复用 PG 池分支，C8 收口）。

    AsyncPostgresSaver 构造需在运行中的事件循环内（内部绑定 loop），用 asyncio.run
    模拟 app 的 async 调用上下文。仅验证工厂正确选型与透传；连接池真伪无关。
    无 postgres 扩展时跳过。
    """
    if not _pg_postgres_saver_available():
        pytest.skip("langgraph[postgres] 未安装，跳过 PG 分支测试")

    monkeypatch.delenv("MONGO_URL", raising=False)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from agent_core.memory import get_checkpointer

    # 用普通对象模拟 AsyncConnectionPool（工厂仅透传，不调用其方法）
    fake_pool = object()

    async def _check():
        saver = get_checkpointer(pg_pool=fake_pool)
        assert isinstance(saver, AsyncPostgresSaver)
        # 透传的 pool 应保持同一实例（app 依赖此句柄做 setup）；
        # AsyncPostgresSaver 内部以 self.conn 持有连接池
        assert saver.conn is fake_pool

    asyncio.run(_check())


def test_get_checkpointer_pg_pool_takes_precedence_over_mongo(monkeypatch):
    """即使配置了 MONGO_URL，显式传入 pg_pool 也应优先走 PG 分支（app 语义）。"""
    if not _pg_postgres_saver_available():
        pytest.skip("langgraph[postgres] 未安装，跳过 PG 分支测试")

    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from agent_core.memory import get_checkpointer

    async def _check():
        saver = get_checkpointer(pg_pool=object())
        assert isinstance(saver, AsyncPostgresSaver)

    asyncio.run(_check())
