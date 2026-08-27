from agent_runtime.planner.execution_lifecycle import (
    ExecutionLifecycle,
    ExecutionState,
    InvalidExecutionTransition,
)


def test_dynamic_agent_execution_lifecycle_allows_replan_and_resume():
    lifecycle = ExecutionLifecycle()

    lifecycle.transition(ExecutionState.ADMITTED, reason="admission accepted")
    lifecycle.transition(ExecutionState.PLANNING, reason="select execution mode")
    lifecycle.transition(ExecutionState.RUNNING, reason="start dynamic agent loop")
    lifecycle.transition(ExecutionState.REPLANNING, reason="tool result requires a new plan")
    lifecycle.transition(ExecutionState.PLANNING, reason="build revised plan")
    lifecycle.transition(ExecutionState.RUNNING, reason="resume with revised plan")
    lifecycle.transition(ExecutionState.CHECKPOINTED, reason="durable checkpoint")
    lifecycle.transition(ExecutionState.RECOVERING, reason="resume from checkpoint")
    lifecycle.transition(ExecutionState.RUNNING, reason="recovery complete")
    lifecycle.transition(ExecutionState.COMPLETED, reason="goal reached")

    assert lifecycle.state is ExecutionState.COMPLETED
    assert lifecycle.terminal
    assert len(lifecycle.history) == 9


def test_lifecycle_rejects_bypassing_runtime_boundary():
    lifecycle = ExecutionLifecycle()

    # A dynamic Agent must not jump directly from CREATED to RUNNING.
    try:
        lifecycle.transition(ExecutionState.RUNNING, reason="agent decided to run")
    except InvalidExecutionTransition:
        pass
    else:
        raise AssertionError("CREATED -> RUNNING must be rejected")


def test_failed_execution_can_be_recovered_or_replanned():
    lifecycle = ExecutionLifecycle()
    lifecycle.transition(ExecutionState.ADMITTED)
    lifecycle.transition(ExecutionState.PLANNING)
    lifecycle.transition(ExecutionState.RUNNING)
    lifecycle.transition(ExecutionState.FAILED, reason="tool unavailable")
    lifecycle.transition(ExecutionState.RECOVERING, reason="resume from durable checkpoint")
    lifecycle.transition(ExecutionState.RUNNING)
    lifecycle.transition(ExecutionState.COMPLETED)

    assert lifecycle.state is ExecutionState.COMPLETED


def test_snapshot_is_checkpoint_friendly():
    lifecycle = ExecutionLifecycle()
    lifecycle.transition(ExecutionState.ADMITTED, reason="accepted")
    snapshot = lifecycle.snapshot()

    assert snapshot["state"] == "admitted"
    assert snapshot["history"][0]["from"] == "created"
    assert snapshot["history"][0]["to"] == "admitted"
