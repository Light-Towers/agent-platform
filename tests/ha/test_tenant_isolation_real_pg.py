"""行为级租户隔离回归（C-1 修复，2026-09-25）：真实 PostgreSQL 上验证 legacy 边界。

背景：v5 迁移把多租户上线前历史语料全量归并进 ``tenant_id='default'`` 桶，
7e442c4 将召回读谓词从过渡期 ``ANY(%s)`` 收紧为精确 ``tenant_id = %s``。
本文件补上此前全仓缺失的**行为级**覆盖（治理测试此前只断言 SQL 字符串形状，
fake 还兼容旧泄漏契约）：

1. 写入 legacy ``default`` 桶记忆 → 以真实租户 ``tenant-a`` 召回 → **断言读不到**
   （跨租户泄漏回归，若读谓词退回作用域列表此用例必红）；
2. ``default`` 租户自身仍可读到 legacy 行（数据未丢，只是收窄作用域）；
3. tenant-a 与 tenant-b 在同 workspace 下互不可见（正向隔离）。

挂 ``requires_pg``：归属 agent-platform-ha workflow（真实 PG 门禁）。
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.requires_pg

_DIM = 512  # CI 环境 embedder 为 Mock（dim=512），与 memories.embedding 列维度一致
_EMBEDDING = [0.1] * _DIM


def _iso_user() -> str:
    """隔离的 workspace（user_id）标识，避免污染/命中其他测试数据。"""
    return f"ws-tenant-iso-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
async def seeded_memories(pg_pool):
    """写入三条记忆：legacy default 桶 1 条 + tenant-a/tenant-b 各 1 条（同 workspace）。

    清理置于 try/finally：即使断言失败也按隔离 user_id 精确删除造数。
    """
    ws = _iso_user()
    rows = [
        ("default", ws, "LEGACY-DEFAULT-SECRET-历史记忆", "semantic", 0.9),
        ("tenant-a", ws, "TENANT-A-PRIVATE-事实", "semantic", 0.9),
        ("tenant-b", ws, "TENANT-B-PRIVATE-事实", "semantic", 0.9),
    ]
    async with pg_pool.connection() as conn:
        for tenant, user_id, content, mtype, importance in rows:
            await conn.execute(
                "INSERT INTO memories (tenant_id, user_id, content, memory_type, "
                "importance, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant, user_id, content, mtype, importance, _EMBEDDING),
            )
    try:
        yield {"ws": ws, "contents": [r[2] for r in rows]}
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute("DELETE FROM memories WHERE user_id = %s", (ws,))


async def test_legacy_default_bucket_not_readable_by_real_tenant(pg_pool, seeded_memories):
    """核心回归：真实租户召回**绝不含** legacy default 桶内容。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    memories = await recall_typed(
        pg_pool, ws, "历史记忆", k=10, embedding=_EMBEDDING, tenant_id="tenant-a"
    )
    contents = [m.content for m in memories]
    assert "TENANT-A-PRIVATE-事实" in contents, "本租户记忆应可召回"
    assert "LEGACY-DEFAULT-SECRET-历史记忆" not in contents, (
        "legacy default 桶记忆对真实租户不可见（读谓词若退回 ANY 作用域列表此断言必红）"
    )


async def test_default_tenant_still_reads_legacy_bucket(pg_pool, seeded_memories):
    """default 租户自身仍可读 legacy 行——收窄作用域 ≠ 数据丢失。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    memories = await recall_typed(
        pg_pool, ws, "历史记忆", k=10, embedding=_EMBEDDING, tenant_id="default"
    )
    assert any("LEGACY-DEFAULT-SECRET-历史记忆" in m.content for m in memories)


async def test_cross_tenant_same_workspace_isolated_real_pg(pg_pool, seeded_memories):
    """正向隔离：tenant-a 与 tenant-b 同 workspace 下互不可见（真实 PG 行为级）。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    mem_a = await recall_typed(
        pg_pool, ws, "事实", k=10, embedding=_EMBEDDING, tenant_id="tenant-a"
    )
    mem_b = await recall_typed(
        pg_pool, ws, "事实", k=10, embedding=_EMBEDDING, tenant_id="tenant-b"
    )
    contents_a = [m.content for m in mem_a]
    contents_b = [m.content for m in mem_b]
    assert "TENANT-B-PRIVATE-事实" not in contents_a
    assert "TENANT-A-PRIVATE-事实" not in contents_b
