# 修复方案：F-S1-01 — agent-runtime 测试反向 import agent_server（红线 1 违规）

> 日期：2026-09-21
> 严重度：**P2**（红线 1 违规 / 依赖方向）
> 来源：[S2 债务诊断](../analysis/2026-09-21/02-debt-diagnosis.md) §2.2 F-S1-01
> 状态：**已实施**（2026-09-21，方向 B：迁移到 `applications/agent_server/tests/`，门禁第 8 session）

## 1. 目标

消除 `packages/agent-runtime/tests/test_graph_planner_dynamic.py` 对 `applications/agent_server` 的反向 import，恢复红线 1（共享包及其测试不得反向依赖应用层）。

## 2. 问题分析

### 2.1 当前状态

```
packages/agent-runtime/tests/test_graph_planner_dynamic.py:7
  from agent_server.planners.graph import GraphPlanner
```

该测试位于 `packages/agent-runtime/tests/`，已被纳入 CI 门禁（Makefile `test` 第 2 个 session，2026-09-21 F-S0-01 纳入）。→ 共享包测试 session 实际验证应用层代码，污染门禁覆盖范围，且让 agent-runtime 无法脱离 agent_server 独立复用/测试。

### 2.2 测试内容（3 用例）

| 用例 | 验证点 |
|------|--------|
| `test_graph_planner_compose_and_execute` | GraphPlanner + FakeLLM 产出 2 节点 DAG，经 `PlannerRuntime`/`execute_plan` 执行，`input_refs` 跨节点传递 |
| `test_graph_planner_single_candidate_no_llm` | 单候选 + 无 LLM → 退化为单节点 |
| `test_graph_planner_compose_failure_falls_back` | LLM 返回非法 JSON → 组合失败回退单节点（可治理，非无限 loop） |

本质：**应用层 `GraphPlanner`（Planner 协议实现）× agent_runtime 执行链的集成测试**。

### 2.3 GraphPlanner 定位

`applications/agent_server/planners/graph.py:34` `class GraphPlanner(Planner)`——应用层对 `agent_runtime.planner.protocol.Planner` 的具体实现，依赖 `ExecutionGraph` / `compose_execution_graph` / `Plan` 等 agent_runtime API。属**应用层**，依赖方向应为 `agent_server → agent_runtime`。

### 2.4 为什么不能简单 mock

- 测试核心价值是 `GraphPlanner` 的组合 / 回退 / 单候选退化逻辑与 runtime 执行链的集成；
- mock 掉 `GraphPlanner` 后，测试退化为"execute_plan 能执行 graph plan"——该能力已被 `packages/agent-runtime/tests/test_graph_compose.py` 覆盖（`compose_execution_graph` 单元测试）；
- `GraphPlanner` 自身的 LLM 组合 / 失败回退逻辑将**零覆盖**，且这些逻辑位于应用层，本就该由应用侧测试守护。

## 3. 影响面

### 3.1 方向 B（推荐）：迁移测试归属到应用侧

| 文件 | 改动 |
|------|------|
| `applications/agent_server/tests/test_graph_planner_dynamic.py` | **新增**（从 `packages/agent-runtime/tests/` 迁移，内容不变） |
| `applications/agent_server/tests/conftest.py` | **新增**（最小占位；本测试自包含，不依赖 settings/env） |
| `packages/agent-runtime/tests/test_graph_planner_dynamic.py` | **删除** |
| `Makefile` | `test` 目标新增 `uv run pytest applications/agent_server/tests -q`（第 8 个 session） |
| `AGENTS.md` | 门禁说明 7 → 8 session |
| `docs/analysis/2026-09-21/02-debt-diagnosis.md` | F-S1-01 状态更新 |

### 3.2 方向 A（备选）：mock 替代

| 文件 | 改动 |
|------|------|
| `packages/agent-runtime/tests/test_graph_planner_dynamic.py` | 重写：用 fake planner 产出 `Plan(graph=...)`，仅测 `execute_plan` 对 graph plan 的执行 |

- 代价：`GraphPlanner` 组合/回退逻辑失去覆盖，仍需在应用侧补测试（即方向 B 的子集）；
- 收益：不新增 session。
- 结论：**不推荐**——既丢覆盖又仍需补应用侧测试，不如直接做方向 B。

## 4. 迁移策略（方向 B）

### 4.1 新建 `applications/agent_server/tests/`

- `conftest.py`：最小占位（docstring only）。本测试自包含（自带 `_FakeLLM`/`_registry`），不依赖 `agent_server.config` 的 env fixture；未来 agent_server 测试需 `clean_env` 时再补。
- `test_graph_planner_dynamic.py`：原样迁移。import 已是 `from agent_server.planners.graph import GraphPlanner` + `agent_runtime.*`，方向正确（应用层 → 共享包）。

### 4.2 删除 `packages/agent-runtime/tests/test_graph_planner_dynamic.py`

### 4.3 Makefile 加 session

```make
uv run pytest applications/agent_server/tests -q
```

置于现有 7 session 之后。该 session 继承根 `pyproject.toml` 的 pytest 配置（`asyncio_mode=auto`、`--import-mode=importlib`）；`agent_server` 经根 pyproject `packages = ["applications/agent_server"]` editable 安装，可 import（根 `tests/conftest.py:24` 已 `from agent_server.config import get_settings` 印证）。

### 4.4 conftest 冲突评估

`--import-mode=importlib` 下，`applications/agent_server/tests/conftest.py` 与其他应用 `tests/conftest.py` 同名但分属独立 session，不冲突（与 `exhibition-agent/tests/conftest.py`、`agent_federation/tests/conftest.py` 等同模式，已在 CI 验证）。

## 5. 验收标准

### 5.1 功能验收

| # | 命令 | 预期 |
|---|------|------|
| 1 | `uv run pytest applications/agent_server/tests -q` | 3 passed |
| 2 | `uv run pytest packages/agent-runtime/tests -q` | 59 passed（原 62 − 3 迁出） |
| 3 | `rg "agent_server\|applications/" packages/agent-runtime/tests/` | 零命中（红线 1 恢复） |

### 5.2 门禁验收

- `make test` 8 个 session 全绿。

## 6. 回滚策略

文件迁移 + Makefile 一行 + AGENTS.md 一行，`git revert` 单 commit 回滚，无接口变更。

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `agent_server` 包在该 session 不可 import | 低 | 收集期 ModuleNotFoundError | editable install 已配置（根 pyproject `packages=["applications/agent_server"]`），根 tests/ 已能 import |
| conftest 名冲突 | 低 | session 内插件冲突 | 独立 session + importlib 模式，与现有应用 tests 同模式 |
| `GraphPlanner` 未来依赖更多应用层模块 | 中 | 测试需相应 fixture | 届时在 `applications/agent_server/tests/conftest.py` 补 |

## 8. 工作量估计

约 15 分钟（新建 2 文件 + 删 1 文件 + Makefile 1 行 + AGENTS.md 1 行 + 验证）。

## 9. 决策建议

**推荐方向 B**：测试归属与被测代码同层，符合"应用层集成测试应在应用侧"原则；方向 A 会让 `GraphPlanner` 核心逻辑失去覆盖且仍需应用侧补测试，等于做了一半。
