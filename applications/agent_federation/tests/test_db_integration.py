"""真 PostgreSQL 回归：#146 的 DSN 接线必须真的建池并跑通 typed memory 一次写/召回。

缺 ``AGENT_PLATFORM_PG_URL`` 即 skip（与 tests/ha 同语义：本地无 PG 跳过，CI 提供
PG 后必须真跑；CI 里 init 失败直接 fail，不以 skip 掩盖故障）。

用同步测试包 ``asyncio.run`` 而非 ``async def``：Windows 下 psycopg 异步需要
SelectorEventLoop，pytest-asyncio 的循环在测试体之前创建，进来再换策略已太晚；
这里临时换策略、跑完恢复，避免污染同 session 的其他用例。
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

_PG_URL = os.environ.get("AGENT_PLATFORM_PG_URL")
_IN_CI = any(os.environ.get(k, "").strip().lower() in {"true", "1"} for k in ("CI", "GITHUB_ACTIONS"))


class _PgUnavailable(RuntimeError):
    """只有「连不上 PG」才降级为 skip；DSN 接线回归必须红。"""


async def _roundtrip() -> None:
    from agent.db import close_pool, get_pool, init_pool
    from agent.memory.semantic_memory import recall_typed, remember_fact

    try:
        pool = await init_pool()
    except Exception as exc:  # noqa: BLE001 - 连接不可达与接线回归必须区分
        raise _PgUnavailable(f"{type(exc).__name__}: {exc}") from exc
    assert pool is not None, "DSN 已注入却退回内存模式（#146 接线回归）"
    try:
        assert get_pool() is pool

        user_id = f"issue146-{uuid.uuid4().hex[:12]}"
        fact = "issue146 回归事实：联邦 DSN 接线后 typed memory 可写可召回"
        await remember_fact(pool, user_id, fact, memory_type="semantic", importance=0.9, tenant_id="default")
        hits = await recall_typed(pool, user_id, "DSN 接线 typed memory", k=3, tenant_id="default")
        assert any(fact in m.content for m in hits), f"召回未命中刚写入的事实：{hits!r}"

        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM memories WHERE tenant_id = %s AND user_id = %s",
                ("default", user_id),
            )
    finally:
        await close_pool()


def test_env_dsn_builds_pool_and_typed_memory_roundtrip(monkeypatch):
    if not _PG_URL:
        pytest.skip("未设置 AGENT_PLATFORM_PG_URL（真 PG 用例按设计 skip）")

    monkeypatch.setenv("AGENT_PLATFORM_DATABASE_URL", _PG_URL)
    monkeypatch.delenv("DEEPAGENTS_DATABASE_URL", raising=False)
    monkeypatch.setenv("EMBEDDING_MODE", "mock")
    monkeypatch.setenv("EMBEDDING_DIM", "512")
    monkeypatch.setenv("SEMANTIC_MEMORY_TYPED", "true")

    import agent_core.memory.embedder as embedder_mod

    previous_embedder = embedder_mod._EMBEDDER  # 直接取单例，避免按环境先加载一次真模型
    embedder_mod.get_embedder(force=True)  # 按本用例的 mock/dim 重建

    previous_policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(_roundtrip())
    except _PgUnavailable as exc:
        if _IN_CI:
            pytest.fail(f"CI 必须提供可用 PostgreSQL：{exc}")
        pytest.skip(f"AGENT_PLATFORM_PG_URL 不可用：{exc}")
    finally:
        asyncio.set_event_loop_policy(previous_policy)
        embedder_mod._EMBEDDER = previous_embedder
