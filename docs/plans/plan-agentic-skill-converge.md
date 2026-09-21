# Dynamic Agent 纳入 Skill 体系方案

> 消除 AgenticPlanner.execute() 旁路，使 agentic 执行受统一组合治理

---

## 背景

Plan-F 演进方向"Dynamic Agent 纳入 Skill 体系"：AgenticPlanner 已迁入 agent_runtime（F-S1-02），
但 `execute()` 仍直接调用 `executor(question, workspace_id)`，不走 `runtime.execution()` /
`runtime.skill_guard()`——agentic 执行不受组合治理（步数/深度/循环），不记录 trajectory step。

`arun()` 已用 `runtime.execution()` + `runtime.skill_guard("agentic")`，但 `execute()` 未对齐。

## 目标

`AgenticPlanner.execute()` 与 `arun()` 对称：用 `runtime.execution()` + `runtime.skill_guard("agentic")`
包裹执行，使 agentic 执行受组合治理 + 记录 trajectory step。

不强制走 `runtime.delegate()`（registry 可能为 None，保持向后兼容）。

## 实施

### AgenticPlanner.execute() 改动

当前：
```python
yield StreamEvent(type="route", ...)
answer = await executor(question, workspace_id)
```

改为：
```python
yield StreamEvent(type="route", ...)
async with runtime.execution():
    async with runtime.skill_guard("agentic"):
        answer = await executor(question, workspace_id)
```

加上 `record_step()` 记录 trajectory（如果 context 存在）。

### 不变项

- monitor 事件桥接（`_subscribe_monitor` / `_handle`）保持不动
- `arun()` 已有治理，不改
- entry_points 发现机制不改
- `_execute_agent_core` 副作用链不改

## 影响面

| 模块 | 变更类型 |
|------|---------|
| `agent_runtime/planner/agentic.py` | execute() 加 execution() + skill_guard 包裹 |
| 测试 | 可能需要适配（FakeRegistry 等测试替身） |

## 验收标准

1. 所有现有测试通过
2. eval 12/12 通过
3. AgenticPlanner.execute() 在 execution() 边界内执行
4. agentic 执行受 skill_guard 治理（步数超限抛 SkillCompositionError）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| execution() 边界引入 ownership_store acquire | 测试验证 InMemoryExecutionOwnershipStore 路径 |
| 测试中 runtime 无 registry | execution() 已处理 registry=None |
