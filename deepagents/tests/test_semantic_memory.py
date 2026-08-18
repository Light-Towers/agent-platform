"""语义长期记忆接线地基测试（TB-10 方向1）。

验证 deepagents 接入的语义记忆门面（内核 agent_core.memory.semantic）行为：
- SEMANTIC_MEMORY_ENABLED 开关正确反映
- 开关关闭 / 无向量后端时，recall/remember 安全降级（不抛、不写）
这是 run_deep_agent 内接线的"地基"；run_deep_agent 本身为重型集成函数，
其调用点由代码审阅 + lint 保证，不在此单测（避免拉起 LLM）。
"""

import importlib

import agent_core.memory.semantic as sem
import pytest


@pytest.fixture
def semantic_env(monkeypatch):
    def _set(enabled: bool):
        monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "true" if enabled else "false")
        importlib.reload(sem)
        return sem

    yield _set
    monkeypatch.delenv("SEMANTIC_MEMORY_ENABLED", raising=False)
    importlib.reload(sem)


def test_enabled_reflects_env(semantic_env):
    assert semantic_env(True).semantic_memory_enabled() is True
    assert semantic_env(False).semantic_memory_enabled() is False


@pytest.mark.asyncio
async def test_recall_safe_when_disabled(semantic_env):
    semantic_env(False)
    # 关闭时不走向量库，直接返回空列表，不抛
    result = await sem.recall_memories("u1", "任意问题", k=3)
    assert result == []


@pytest.mark.asyncio
async def test_remember_noop_when_disabled(semantic_env):
    semantic_env(False)
    # 关闭时不写库，不抛
    sem.remember_memory("u1", "Q: x\nA: y")  # 不应抛


@pytest.mark.asyncio
async def test_recall_degrades_without_backend(semantic_env):
    # 开启但无向量后端（无 MILVUS/PG 连接）时，应安全降级不崩
    semantic_env(True)
    result = await sem.recall_memories("u1", "问题", k=3)
    assert isinstance(result, list)
