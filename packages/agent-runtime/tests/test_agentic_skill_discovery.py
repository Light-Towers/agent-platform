"""T1.7（tech-debt-cleanup 补充 7）：AgenticPlanner.to_skill() 的**真实 entry_points 发现路径**集成测试。

背景（W6 审计）：``test_agentic_skill.py`` 的每条用例都先调
``register_agentic_executor_factory(lambda: fake_executor)`` **显式注入**执行器，
于是 ``_discover_executor_factory()`` 的第一分支（``_executor_factory is not None``）
直接命中，**从不走 ``importlib.metadata.entry_points`` 那条真实发现路径**。
而生产里 ``agent_server/main.py:413`` 的 ``AgenticPlanner().to_skill()`` 恰恰依赖
entry_points 发现（agent_federation 经 ``pyproject.toml`` 的
``[project.entry-points."agent_runtime.agentic_executor"]`` 注册工厂）。
⇒ 显式注入的测试全绿，却掩盖了「真实安装下发现路径是否通」——这正是 W6 指出的盲区。

本文件补两条：
1. **正向**：真实安装下（EP 可发现），**不显式注入**，``to_skill()`` 须经 entry_points
   发现执行器并产出合法的 ``SkillKind.AGENT``（锁住生产发现路径；EP 注册被破坏则本用例红）。
   EP 不可发现属**环境条件**（未装 ``--extra agentic``）而非代码缺陷 ⇒ skip（同仓 requires_pg /
   ZHIKU_INTEGRATION 守卫范式）。
2. **负向（确定性，不依赖环境）**：无任何执行器可用（EP 空 + 未显式注册）时，
   ``_discover_executor_factory()`` 必须**抛 RuntimeError**（fail-loud），绝不静默返回——
   这是 W6「RuntimeError 被 logger.debug 吞掉」在发现层的锁（应用层的条件告警见 main.py:417-427 / T1.2c）。
"""

from __future__ import annotations

import importlib.metadata

import pytest

from agent_runtime.planner import agentic as _agentic_mod
from agent_runtime.planner.agentic import AgenticPlanner
from agent_runtime.skills.registry import SkillKind

_EP_GROUP = "agent_runtime.agentic_executor"


@pytest.fixture(autouse=True)
def _reset_executor_factory(monkeypatch):
    """每条用例前把模块级执行器缓存清成 None，强制走发现逻辑；用后还原防污染。

    必须清：``agent_federation.planners.agentic`` 在 **import 期**就调
    ``register_agentic_executor_factory``，一旦它被本 session 任何路径 import 过，
    ``_executor_factory`` 就非空，发现路径会被短路——那正是要避免的假绿。
    """
    monkeypatch.setattr(_agentic_mod, "_executor_factory", None)


def _ep_installed() -> bool:
    return bool(list(importlib.metadata.entry_points(group=_EP_GROUP)))


def test_to_skill_discovers_executor_via_entry_points_without_explicit_registration():
    """真实安装下：不显式注入，to_skill() 经 entry_points 发现执行器 → 合法 AGENT skill。"""
    if not _ep_installed():
        pytest.skip(
            f"{_EP_GROUP} entry point 未发现（未安装 agent-federation-app / --extra agentic）；"
            "属环境条件，非代码缺陷"
        )

    # 前置：确认此刻确实没有显式注册的工厂（fixture 已清 None），逼 to_skill 走发现路径
    assert _agentic_mod._executor_factory is None

    skill = AgenticPlanner().to_skill()

    assert skill.name == "agentic"
    assert skill.kind is SkillKind.AGENT
    # 发现路径真的执行了：EP 加载后把工厂写回了模块级缓存（不是靠显式注入）
    assert _agentic_mod._executor_factory is not None
    assert callable(_agentic_mod._executor_factory)


def test_discover_raises_runtimeerror_when_no_executor_available(monkeypatch):
    """无执行器可用（EP 空 + 未显式注册）→ 必须抛 RuntimeError（fail-loud，绝不静默）。

    确定性：直接把 entry_points 打成空，不依赖真实安装形态。
    """
    assert _agentic_mod._executor_factory is None  # fixture 已清
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **kwargs: [])

    with pytest.raises(RuntimeError) as excinfo:
        AgenticPlanner().to_skill()

    # 错误信息必须给出可操作的解锁动作（装 extra 或显式注册），而非空泛失败
    msg = str(excinfo.value)
    assert "agent-federation-app" in msg or "register_agentic_executor_factory" in msg
