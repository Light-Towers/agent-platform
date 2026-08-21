"""Trajectory Replay（P3-2）。

读取一条 ``TrajectoryRecord``（golden 轨迹），用「重放注册表」按录制顺序回放 Skill 调用，
并与原始轨迹逐 step 比对，报告 divergence 点：

- ``order``：同序位调用的 Skill 名称变化（route / skill 顺序变化）；
- ``extra_call``：重放触发的调用超出录制步数（多余调用）；
- ``missing_call``：录制存在但重放未触发的 Skill；
- ``result_change``：同 Skill 成功但结果内容变化；
- ``error_change``：同 Skill 成功/失败状态反转。

设计：``replay_trajectory`` 复用 ``execute_plan`` 真实执行链（重放注册表作 ``registry``），
保证「route 变化 / skill 顺序变化 / 多余调用」都能在真实编排路径上被捕获；比对逻辑与
执行解耦（读重放注册表记录的 actual_steps），不依赖持久化是否完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.planner.execution_graph import execute_plan
from agent_runtime.planner.protocol import Plan, PlannerRuntime
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep


class ReplayDivergence:
    """单点 divergence：类型 + 序位 + 描述。"""

    def __init__(self, kind: str, index: int, detail: str) -> None:
        self.kind = kind
        self.index = index
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "index": self.index, "detail": self.detail}


class ReplayReport:
    """重放报告：divergence 列表 + 重放实际步序 + 是否发散。"""

    def __init__(
        self,
        execution_id: str,
        divergences: list[ReplayDivergence],
        replay_steps: list[TrajectoryStep],
    ) -> None:
        self.execution_id = execution_id
        self.divergences = divergences
        self.replay_steps = replay_steps

    @property
    def diverged(self) -> bool:
        return bool(self.divergences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "diverged": self.diverged,
            "divergences": [d.to_dict() for d in self.divergences],
            "replay_steps": [s.to_dict() for s in self.replay_steps],
        }


class ReplayRegistry:
    """按录制轨迹构造的重放注册表：``execute`` 按录制顺序回放并自检 divergence。

    - 达录制步数前：与期望 Skill 名比对（不同则记 ``order``），返回/抛出录制结果；
    - 超出录制步数：记 ``extra_call`` 并抛 RuntimeError（中止以暴露多余调用）；
    - ``actual_steps`` 记录真实发生的调用（名称/入参/结果/错误），供 replay 比对。
    """

    def __init__(self, record: TrajectoryRecord) -> None:
        self._steps = list(record.steps)
        self._i = 0
        self.divergences: list[ReplayDivergence] = []
        self.actual_steps: list[TrajectoryStep] = []

    def _record_actual(self, name: str, kwargs: dict[str, Any], result: Any, error: str | None) -> None:
        self.actual_steps.append(
            TrajectoryStep(
                name=name, args=kwargs, result=result, error=error,
                latency=0.0, tokens=0, index=len(self.actual_steps),
            )
        )

    async def execute(self, name: str, **kwargs: Any) -> Any:
        if self._i >= len(self._steps):
            self.divergences.append(
                ReplayDivergence("extra_call", self._i, f"重放超出录制步数，多余调用: {name}")
            )
            raise RuntimeError(f"replay: 超出录制步数，多余调用 {name}")
        expected = self._steps[self._i]
        idx = self._i
        self._i += 1
        if expected.name != name:
            self.divergences.append(
                ReplayDivergence("order", idx, f"序位 {idx} 期望 {expected.name} 实得 {name}")
            )
        if expected.error is not None:
            self._record_actual(name, kwargs, None, expected.error)
            raise RuntimeError(expected.error)
        self._record_actual(name, kwargs, expected.result, None)
        return expected.result


def build_replay_registry(record: TrajectoryRecord) -> ReplayRegistry:
    """从 golden 轨迹构造重放注册表（默认严格回放录制行为）。"""
    return ReplayRegistry(record)


class _RecordingWrapper:
    """记录重放注册表真实发生的每一步（任何 registry 皆可，不依赖其内部实现）。"""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.actual_steps: list[TrajectoryStep] = []

    async def execute(self, name: str, **kwargs: Any) -> Any:
        try:
            result = await self.inner.execute(name, **kwargs)
        except Exception as exc:  # noqa: BLE001 记录失败步并向上抛
            self.actual_steps.append(
                TrajectoryStep(name=name, args=kwargs, result=None, error=str(exc), index=len(self.actual_steps))
            )
            raise
        self.actual_steps.append(
            TrajectoryStep(name=name, args=kwargs, result=result, error=None, index=len(self.actual_steps))
        )
        return result


async def replay_trajectory(
    record: TrajectoryRecord,
    registry: Any,
    *,
    runtime_cls: Any = PlannerRuntime,
    max_steps: int = 50,
) -> ReplayReport:
    """重放一条轨迹并报告 divergence。

    :param record: 原始（golden）轨迹，作为比对基线。
    :param registry: 重放注册表（通常由 ``build_replay_registry`` 构造，或注入「当前行为」
        以检测漂移）；须实现 ``async execute(name, **kwargs)``。
    :return: ``ReplayReport``（divergences / replay_steps / diverged）。
    """
    wrapper = _RecordingWrapper(registry)
    runtime = runtime_cls(registry=wrapper, max_steps=max_steps)
    plan = Plan(**record.plan)
    # 重放走真实执行链（execute_plan→delegate→registry.execute），route/顺序/多余调用均暴露
    try:
        _ = [ev async for ev in execute_plan(plan, runtime)]
    except Exception:  # noqa: BLE001 重放中预期内的失败（录制即失败）不阻断比对
        pass

    # inner 自带 divergence（如 ReplayRegistry 的 order / extra_call）合并；actual 以 wrapper 为准
    divergences = list(getattr(registry, "divergences", []) or [])
    actual = list(wrapper.actual_steps)

    # missing_call：录制步数 > 实际触发
    if len(record.steps) > len(actual):
        for j in range(len(actual), len(record.steps)):
            divergences.append(
                ReplayDivergence("missing_call", j, f"录制存在但重放未触发: {record.steps[j].name}")
            )

    # result_change / error_change：同名同序但结果或成败状态变化
    for old, new in zip(record.steps, actual):
        if old.name != new.name:
            continue
        old_ok = old.error is None
        new_ok = new.error is None
        if old_ok != new_ok:
            divergences.append(
                ReplayDivergence("error_change", old.index, f"{old.name}: 成功/失败状态反转")
            )
        elif old_ok and new_ok and old.result != new.result:
            divergences.append(
                ReplayDivergence("result_change", old.index, f"{old.name}: 结果内容变化")
            )

    return ReplayReport(execution_id=record.execution_id, divergences=divergences, replay_steps=actual)


__all__ = [
    "ReplayDivergence",
    "ReplayReport",
    "ReplayRegistry",
    "build_replay_registry",
    "replay_trajectory",
]
