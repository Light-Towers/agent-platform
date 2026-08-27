# Dynamic Agent Execution Boundary

## 1. Decision

Agent Platform does **not** require every business task to be represented as a pre-defined State Graph.
Instead it uses two complementary layers:

1. **Dynamic planning** — Planner / LLM may generate a plan, tool call sequence, Dynamic Graph, or re-plan after observing results.
2. **Explicit execution lifecycle** — Runtime owns the lifecycle of every execution: admission, planning, running, waiting, checkpoint, re-planning, recovery, completion/failure/cancellation.

The distinction is:

> **Task space can be dynamic; execution invariants are explicit.**

## 2. Control boundary

```text
                         User Task
                             |
                             v
                    +------------------+
                    | Mode Selector    |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
    Deterministic         Workflow        Dynamic Graph / Agentic
    fixed capability      registered      LLM plan / re-plan / loop
          |                  |                  |
          +------------------+------------------+
                             v
                  +----------------------+
                  | Execution Boundary   |
                  | explicit lifecycle   |
                  +----------+-----------+
                             |
                  +----------+-----------+
                  | Runtime Governance  |
                  | policy / admission   |
                  | budget / timeout     |
                  | retry / circuit      |
                  | checkpoint / fencing |
                  +----------+-----------+
                             |
                             v
                       Skill Runtime
                             |
                             v
                          Effect
```

The LLM may choose **what to do next**, but it cannot bypass the Runtime boundary to execute an unregistered capability or skip Runtime governance.

## 3. What the explicit state machine controls

The lifecycle state machine is intentionally **not** a catalog of business tasks.
It controls the execution lifecycle:

```text
CREATED
   |
ADMITTED
   |
PLANNING <-------------------+
   |                          |
RUNNING --> REPLANNING -------+
   |  |  \
   |  |   +--> WAITING --> RUNNING
   |  |
   |  +----> CHECKPOINTED --> RECOVERING --> RUNNING
   |
   +----> COMPLETED
   +----> FAILED ------> RECOVERING / PLANNING
   +----> CANCELLED
```

This allows an open-ended task such as "research a repository and decide what to change" to discover new steps dynamically without requiring those steps to have existed in the graph beforehand.

## 4. Dynamic task vs deterministic execution

### Fixed workflow

```text
route -> search/rag/sql -> evidence -> synthesize -> done
```

Use an explicit Graph/Workflow when the business path is known and should be regression-testable.

### Open-ended task

```text
observe -> plan -> tool -> observe -> re-plan -> tool -> ... -> done
```

The individual actions are dynamic. The Runtime still enforces:

- registered Skill boundary;
- permission / policy checks;
- step, depth, token and cost budgets;
- timeout / retry / circuit-breaker policy;
- checkpoint and recovery;
- ownership/fencing for HA executions;
- trajectory / audit / tracing.

## 5. Why this is preferable

A pure fixed workflow cannot enumerate every future Agent task and becomes a giant maintenance graph.
A pure autonomous loop makes execution invariants too dependent on model behavior.

The platform therefore follows:

> **Code defines the execution boundary; the model decides within that boundary; Runtime decides whether the proposed action may execute.**

This is an autonomy/control trade-off, not a claim that one Agent framework is universally better than another.

## 6. Existing v3 building blocks

- `ModeSelector`: chooses deterministic / workflow / graph / agentic mode.
- `ExecutionGraph`: represents Planner-generated Dynamic Graph IR and is validated before execution.
- `AgenticRuntimeBridge`: exposes discovered registered Skills to an Agent loop and routes every tool call through `PlannerRuntime.delegate`.
- `ExecutionLifecycle`: explicit lifecycle state machine.
- `ExecutionBoundary`: connects the lifecycle state machine to `PlannerRuntime.execution`.

The last two are intentionally framework-neutral so DeepAgents, LangGraph, or another Agent loop can consume the same Runtime boundary.
