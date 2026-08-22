# Plan Context Decoupling 方案

> 消灭 `Plan.notes` 万能字典，建立 Context Ownership 正规化

---

## 背景

当前 `Plan.notes: dict[str, Any]` 承载了大量运行时上下文字段，形成隐式状态总线，破坏了 v2 已建立的四层 Context 分层边界。

## 目标

将 `Plan.notes` 中的各字段迁移到其正确归属的 Context 层，最终删除 `Plan.notes`。

## 字段归属表

| Plan.notes 字段 | 最终归属 | 原因 |
|----------------|---------|------|
| `question` | `PlannerContext.question` | Planner 决策输入 |
| `workspace_id` / `user_id` | `ExecutionIdentity` | 身份/租户，非执行状态 |
| `last_snapshot` | `PlannerContext.previous_execution` | 上一轮执行输入 |
| `messages` / `compacted` | `ConversationContext` | 对话状态 |
| `constraints` | `TaskState.constraints` | 任务状态 |
| `iterations` | `PlanningState.iteration` | 重规划状态 |
| `execution_mode` | `Plan.mode` | 已存在，无需迁移 |
| `kwargs` | `SkillInvocation.args` | 单次调用参数 |

---

## 三阶段实施

### Phase 1：禁止新增写入（兼容层）

- `Plan.notes` 保留为 `dict[str, Any]`，标记 `@deprecated`
- 新代码**禁止**向 `notes` 写入上述字段
- 读取路径保持兼容（`plan.notes.get("x")` 仍可工作）

### Phase 2：逐字段迁移（利用现有设施）

v2 已存在的设施：
- `PlannerContext` (protocol.py)
- `ConversationContext` (context_manager.py)
- `TaskState` (context_manager.py)
- `PlanningState` (context_manager.py)
- `ExecutionIdentity` - 需新增

迁移顺序：
1. 新增 `ExecutionIdentity` dataclass
2. `PlannerContext` 增加 `question`、`previous_execution` 字段
3. `ConversationContext` 确认已有 `messages`/`compacted`
4. `TaskState` 确认已有 `constraints`
5. `PlanningState` 确认已有 `iteration`
6. 各 Planner 的 `plan()` 写入对应 Context 而非 `notes`
7. 各 Planner 的 `execute()` 从 Context 读取而非 `plan.notes`
8. `ExecutionContext` 增加 `identity: ExecutionIdentity` 字段
9. `SkillInvocation` / `delegate()` 显式传参替代 `kwargs`

### Phase 3：删除 `Plan.notes`

- 删除 `Plan.notes` 字段
- 清理兼容读取代码
- 更新测试断言

---

## 影响面

| 模块 | 变更类型 |
|------|---------|
| `protocol.py` (Plan, PlannerContext, ExecutionContext) | 字段增删 |
| `context_manager.py` (ConversationContext, TaskState, PlanningState) | 字段确认/增补 |
| `execution_graph.py` (_persist_trajectory, execute_plan) | 读取路径变更 |
| `planners/deterministic.py` | plan/execute 读写路径 |
| `planners/graph.py` | 同 |
| `planners/agentic.py` | 同 |
| `planners/unified.py` | 同 |
| `planners/__init__.py` | 可能涉及 |
| `main.py` (PlannerRuntime 装配) | 注入 ExecutionIdentity |
| 测试文件 | 断言路径更新 |

---

## 验收标准

1. 所有现有测试通过（350+ 根 + 92 联邦 + 8 kefu）
2. `eval/run_eval.py` 启发式路由 12/12 通过
3. 无 `plan.notes["x"]` 写入残留（grep 验证）
4. `Plan.notes` 字段可删除不报错
5. Context 分层边界清晰：无跨层直接读写

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 迁移遗漏导致运行时 KeyError | Phase 1 兼容层保留读取，逐步替换 |
| 多 Planner 行为不一致 | 统一抽象基类/工厂方法规范读写 |
| 测试大量改动 | 先改测试断言，再改实现（TDD） |
| 性能回归 | 避免新增对象拷贝，复用现有 ContextVar |

---

## 里程碑

- [ ] 方案文档确认
- [ ] Phase 1 兼容层
- [ ] Phase 2 字段迁移（分 8 步）
- [ ] Phase 3 删除 notes
- [ ] 全测试通过 + eval 通过