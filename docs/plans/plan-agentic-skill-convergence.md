# Plan: AgenticPlanner → SkillKind.AGENT 收敛

> 状态：**已落地（契约层 3/3）**，但**默认部署下这条注册不生效** ｜ 依据：落码提交 `11d313a6`（2026-09-22，标题即「AgenticPlanner → SkillKind.AGENT 收敛」）；`planner/agentic.py:180` 有 `to_skill()`、`:208` 置 `kind=SkillKind.AGENT`；`applications/agent_server/main.py:374-381` 在 lifespan 里 `AgenticPlanner().to_skill()` → `registry.register(...)`；测试面除本方案要求的 `test_agentic_skill.py`，后补 `test_agentic_entry_point.py` ｜ 回写：本文件不再更新。
>
> ⚠️ 边界要说准，不得写成"agentic 已在现网可用"：`main.py:383` 的注释自己写明 entry_points 不可用是**常见预期（非 agentic 部署）**，且我实测 `pyproject.toml` 三处（根 / agent-runtime / agent_server）**没有任何 entry-points 声明** ⇒ 现网默认 `planner=deterministic` 时这段走的是 except 跳过分支。收敛的是**调用契约**（可被 `SkillRegistry.execute()` 与 ExecutionGraph 引用），不是部署形态。

## 目标

将 AgenticPlanner 的执行包装为 `SkillKind.AGENT` 型 Skill，使其可通过 `SkillRegistry.execute()` 统一调用。当前旁路治理 gap 已消除（`runtime.execution()` + `skill_guard("agentic")` 已就位），本阶段完成契约层收敛。

## 现状

- `AgenticPlanner.execute()` 通过 entry_points 发现外部执行器 `executor(question, workspace_id)`
- 已有 `runtime.execution()` + `skill_guard("agentic")` 包裹（组合治理 gap 已消除）
- `as_agent_skill()` 已存在，但面向 subagent dict（deepagents），不直接适配 AgenticPlanner
- 未注册为 SkillKind.AGENT → 无法通过 SkillRegistry.execute() 调用、无法在 ExecutionGraph 中引用

## 方案

### 改动

1. **`agent_runtime/planner/agentic.py`**：增加 `to_skill()` 方法，返回 `SkillKind.AGENT` 型 Skill
   - executor 包装 `_discover_executor_factory()()`，接受 `question` / `workspace_id` kwargs
   - permissions / timeout_ms / input_schema 可选注入

2. **`agent_server/main.py`**：lifespan 中尝试注册 agentic skill 到 registry
   - try/except 包裹，entry_points 不可用时静默跳过（零依赖冒烟不受影响）

3. **测试**：新增 `test_agentic_skill.py`，验证 `to_skill()` 契约

### 不改动

- `AgenticPlanner.execute()` / `arun()` 保持不变（向后兼容）
- `as_agent_skill()` 不修改（面向 subagent dict，职责不同）

## 影响面

| 文件 | 改动类型 |
|------|----------|
| `agent_runtime/planner/agentic.py` | 增加 `to_skill()` 方法 |
| `agent_server/main.py` | lifespan 中注册 agentic skill |
| `agent_runtime/tests/test_agentic_skill.py` | 新增测试 |

## 验收标准

1. `AgenticPlanner.to_skill()` 返回 `SkillKind.AGENT` 型 Skill
2. 通过 `SkillRegistry.execute("agentic", question=..., workspace_id=...)` 可调用
3. entry_points 不可用时 `to_skill()` raise RuntimeError（与 `_discover_executor_factory` 一致）
4. 现有测试全绿，无回归
