"""to_skill() 真实 entry_points 发现路径集成测试（T1.7）。

区别于 test_agentic_skill.py 的显式 register_agentic_executor_factory 注入：
本模块用 tmp_path 构造 fake dist-info（含 entry_points.txt）注入 sys.path，
验证 _discover_executor_factory 的 entry_points 分支真实生效。

隔离手段：monkeypatch _EXECUTOR_EP_GROUP 为测试专属 group，环境中的
agent-federation-app entry point 不会干扰；用例结束 monkeypatch 自动还原。
"""

from __future__ import annotations

import importlib
import textwrap

import pytest

from agent_runtime.planner import agentic as agentic_mod
from agent_runtime.planner.agentic import AgenticPlanner, register_agentic_executor_factory

_TEST_EP_GROUP = "agent_runtime.agentic_executor_test"


@pytest.fixture(autouse=True)
def _reset_and_isolate(monkeypatch):
    """重置模块级执行器缓存 + 切换到测试专属 entry point group。"""
    monkeypatch.setattr(agentic_mod, "_executor_factory", None)
    monkeypatch.setattr(agentic_mod, "_EXECUTOR_EP_GROUP", _TEST_EP_GROUP)


def _make_fake_distribution(tmp_path):
    """构造含 entry_points.txt 的 fake dist-info + 可 import 的 fake 执行器包。"""
    pkg = tmp_path / "fake_agentic_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "executor.py").write_text(
        textwrap.dedent(
            """
            async def fake_executor(question, workspace_id, main_agent=None):
                return f"ep:{question}@{workspace_id}"

            def factory():
                return fake_executor
            """
        ),
        encoding="utf-8",
    )
    dist = tmp_path / "fake_agentic_dist-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fake-agentic-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        f"[{_TEST_EP_GROUP}]\nfake = fake_agentic_pkg.executor:factory\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_to_skill_discovers_executor_via_entry_points(tmp_path, monkeypatch):
    """真实发现路径：entry_points 注册的执行器被 to_skill 发现并可调用（T1.7）。"""
    root = _make_fake_distribution(tmp_path)
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()

    skill = AgenticPlanner().to_skill()  # 不显式 register——走 entry_points 发现
    assert skill.name == "agentic"
    result = await skill.executor(question="q", workspace_id="ws")
    assert result == "ep:q@ws"


@pytest.mark.asyncio
async def test_explicit_registration_precedence_over_entry_points(tmp_path, monkeypatch):
    """显式 register_agentic_executor_factory 优先于 entry_points 发现。"""
    root = _make_fake_distribution(tmp_path)
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()

    async def explicit_executor(question, workspace_id, main_agent=None):
        return "explicit"

    register_agentic_executor_factory(lambda: explicit_executor)
    skill = AgenticPlanner().to_skill()
    result = await skill.executor(question="q", workspace_id="ws")
    assert result == "explicit"
