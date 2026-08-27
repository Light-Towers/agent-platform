import pytest

from agent_runtime.planner.execution_boundary import ExecutionBoundary
from agent_runtime.planner.execution_lifecycle import ExecutionState


class FakeRuntime:
    def execution(self, *, validate_composition=True, execution_id=None):
        return FakeScope()


class FakeScope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_boundary_supports_dynamic_plan_replan_and_completion():
    boundary = ExecutionBoundary(FakeRuntime())
    async with boundary:
        boundary.planning("select mode")
        boundary.running("start agent loop")
        boundary.replanning("tool result requires another step")
        boundary.planning("revise plan")
        boundary.running("continue")
        boundary.complete()

    assert boundary.state is ExecutionState.COMPLETED
    assert [e.to_state for e in boundary.lifecycle.history] == [
        ExecutionState.ADMITTED,
        ExecutionState.PLANNING,
        ExecutionState.RUNNING,
        ExecutionState.REPLANNING,
        ExecutionState.PLANNING,
        ExecutionState.RUNNING,
        ExecutionState.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_boundary_marks_unhandled_error_failed():
    boundary = ExecutionBoundary(FakeRuntime())
    with pytest.raises(RuntimeError):
        async with boundary:
            boundary.planning()
            boundary.running()
            raise RuntimeError("tool failed")

    assert boundary.state is ExecutionState.FAILED
