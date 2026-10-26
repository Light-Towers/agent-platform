"""联邦 PG 池 DSN 注入（issue #146）。

lifespan 调用 ``agent.db.init_pool()`` 时必须按文档约定解析 env：
``AGENT_PLATFORM_DATABASE_URL`` → ``DEEPAGENTS_DATABASE_URL``（弃用警告）→
``DATABASE_URL``；空 DSN 保持内核内存模式。这里只钉参数形状，不建连。
"""

from __future__ import annotations

import pytest

from agent.db import init_pool

_ENV_NAMES = (
    "AGENT_PLATFORM_DATABASE_URL",
    "DEEPAGENTS_DATABASE_URL",
    "DATABASE_URL",
)


@pytest.fixture
def runtime_init(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake(database_url: str = "", **kwargs):
        calls.append((database_url, kwargs))
        return None if not database_url else object()

    monkeypatch.setattr("agent.db._runtime_init_pool", fake)
    return calls


def _clear_env(monkeypatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


async def test_prefers_agent_platform_url(monkeypatch, runtime_init):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AGENT_PLATFORM_DATABASE_URL", "postgresql://new")
    monkeypatch.setenv("DEEPAGENTS_DATABASE_URL", "postgresql://legacy")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fallback")

    await init_pool()

    assert runtime_init[0][0] == "postgresql://new"


async def test_legacy_name_warns_and_is_used(monkeypatch, runtime_init):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DEEPAGENTS_DATABASE_URL", "postgresql://legacy")

    with pytest.deprecated_call():
        await init_pool()

    assert runtime_init[0][0] == "postgresql://legacy"


async def test_database_url_fallback(monkeypatch, runtime_init):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fallback")

    await init_pool()

    assert runtime_init[0][0] == "postgresql://fallback"


async def test_empty_dsn_keeps_memory_mode(monkeypatch, runtime_init):
    _clear_env(monkeypatch)

    assert await init_pool() is None
    assert runtime_init[0][0] == ""


async def test_explicit_url_wins_over_env_and_kwargs_pass_through(monkeypatch, runtime_init):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AGENT_PLATFORM_DATABASE_URL", "postgresql://env")

    await init_pool("postgresql://explicit", db_pool_max_size=5)

    assert runtime_init[0] == ("postgresql://explicit", {"db_pool_max_size": 5})
