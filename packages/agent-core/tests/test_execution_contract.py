# -*- coding: utf-8 -*-
"""执行记忆内核协议契约测试（ADR-0005 T0）。

验证：
1. ``agent_core.memory.execution`` 仅依赖 stdlib + 内核内部（零第三方、零反向依赖），
   遵守 agent-core 零依赖铁律；
2. ``EpisodicStoreProtocol`` / ``ProceduralStoreProtocol`` 为可满足的 runtime_checkable 协议。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODULE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent-core" / "agent_core" / "memory" / "execution.py"
)


def _collect_imports(tree: ast.Module) -> list[tuple[str, str]]:
    """返回 [(kind, name), ...]：kind=from 时 name=module；kind=import 时 name=top_level。"""
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            out.append(("from", node.module or ""))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append(("import", alias.name.split(".")[0]))
    return out


def test_execution_module_zero_third_party_imports():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    imports = _collect_imports(tree)
    for kind, name in imports:
        # 允许 stdlib（不点号或已知标准库）与内核内部 agent_core.*
        assert not name.startswith("agent_runtime"), (
            f"execution.py 反向依赖了 agent_runtime: {kind} {name}"
        )
        assert not name.startswith("applications"), (
            f"execution.py 依赖了应用层: {kind} {name}"
        )
        # 第三方常见包黑名单（agent-core 零依赖铁律：不得直接 import）
        assert name not in {
            "requests",
            "pydantic",
            "psycopg",
            "langgraph",
            "numpy",
        }, f"execution.py 引入了第三方包: {kind} {name}"


def test_protocols_are_runtime_checkable_and_satisfiable():
    from agent_core.memory.execution import (
        EpisodicStoreProtocol,
        ProceduralStoreProtocol,
    )

    assert getattr(EpisodicStoreProtocol, "_is_runtime_protocol", False) is True
    assert getattr(ProceduralStoreProtocol, "_is_runtime_protocol", False) is True

    class DummyEpisodic:
        async def save(self, episode, *, tenant_id="default"):
            return None

        async def recall(self, query, top_k=10, *, tenant_id="default"):
            return []

        async def get(self, episode_id, *, tenant_id="default"):
            return None

        async def list_by_execution(self, execution_id, *, tenant_id="default"):
            return []

        async def list_all(self, limit=10000, *, tenant_id="default"):
            return []

        async def delete(self, episode_id, *, tenant_id="default"):
            return False

    class DummyProcedural:
        async def save(self, entry, *, tenant_id="default"):
            return None

        async def load(self, name, version=None, *, tenant_id="default"):
            return None

        async def list_all(self, *, tenant_id="default"):
            return []

        async def list_by_name(self, name, *, tenant_id="default"):
            return []

        async def delete(self, name, version, *, tenant_id="default"):
            return False

    assert isinstance(DummyEpisodic(), EpisodicStoreProtocol)
    assert isinstance(DummyProcedural(), ProceduralStoreProtocol)


def test_incomplete_episodic_fails_protocol():
    from agent_core.memory.execution import EpisodicStoreProtocol

    class Partial:
        async def save(self, episode, *, tenant_id="default"):
            return None

    assert not isinstance(Partial(), EpisodicStoreProtocol)
