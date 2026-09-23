# V3 Phase 3.4：AwaitableTask 接入执行路径

> 状态：**设计文档 + 实现中**。
> 前置：V3 Phase 2-4 已完成（Scheduler/Status/Reaper/ControlPlane/CostGov/Forensic 已接入）。
> 日期：2026-09-23。

---

## 1. 问题

当 Skill 声明 `EffectContract(receipt_strategy=EXTERNAL_ID)` 且外部系统返回异步 task_id 时，执行路径应：
1. 创建 `AwaitableTask(EXTERNAL)`，状态 `SUBMITTED`
2. `ExecutionStatus` 转 `WAITING_EXTERNAL`（释放 Worker slot）
3. 外部回调 → `AwaitableTask` 转 `COMPLETED` + `resume_payload`
4. `ExecutionStatus` 转 `RUNNING`，从 checkpoint 恢复继续执行

当前缺口：`AwaitableTask` 模块已实现（InMemory + PG），但 `delegate()` 不检测异步返回，执行不挂起。

## 2. 设计

### 2.1 执行挂起机制

**核心思路**：`ExecutionSuspended` 是控制流信号，不是业务异常。

```text
delegate() 检测 __awaitable__
  ↓
创建 AwaitableTask(SUBMITTED) → awaitable_task_store.save()
  ↓
raise ExecutionSuspended(task_id, node_id)
  ↓
_run() 透传（except ExecutionSuspended: raise）
  ↓
asyncio.gather raises ExecutionSuspended
  ↓
_run_graph_in_place 捕获：
  1. checkpoint.save(completed, resumable=True)  — 已完成节点（不含挂起节点）
  2. yield StreamEvent(type="suspended", task_id, node_id)
  3. return  — 终止 generator
  ↓
execute_plan / execute_graph 透传 suspended 事件
  ↓
SSE: {"type": "suspended", "task_id": "...", "execution_id": "..."}
  ↓
SSE 流结束（客户端拿 task_id 轮询 /api/executions/{id}）
```

### 2.2 执行恢复机制

```text
POST /api/callback/{task_id}  ← 外部回调
  ↓
load AwaitableTask
  ↓
state 已 COMPLETED → 返回（幂等）
state 是 SUBMITTED/RUNNING → CAS 转 COMPLETED + resume_payload
  ↓
load checkpoint → completed dict
  ↓
inject: completed[task.step_id] = task.resume_payload
  ↓
save checkpoint（updated completed）
  ↓
load TrajectoryRecord → plan → 重建 ExecutionGraph
  ↓
ExecutionStatus → RUNNING
  ↓
re-run execute_graph(same execution_id)
  → checkpoint resume：跳过 completed 节点，从下一层继续
  ↓
结果经 Control Plane inspect 可查
```

### 2.3 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 挂起方式 | `ExecutionSuspended` 信号 + 终止 generator | 不占 worker slot；复用 checkpoint resume |
| SSE 语义 | yield suspended 事件 + 结束流 | 客户端拿 task_id 轮询，不需长连接 |
| 恢复触发 | callback HTTP 端点 | 外部系统直接 POST，平台无关 |
| 幂等保证 | AwaitableTask 状态机（COMPLETED 是终态） | `can_transition(COMPLETED, COMPLETED) = True`，重复回调 no-op |
| Plan 重建 | 从 TrajectoryRecord.plan 加载 | plan 已持久化，不需额外存储 |
| checkpoint 注入 | `completed[node_id] = resume_payload` | `_run_graph_in_place` 已支持跳过 completed 节点 |

### 2.4 不变量

1. **同步路径不受影响**：只有 `result.get("__awaitable__")` 为 True 时才挂起，其余 Skill 正常执行
2. **callback 幂等**：同一 callback 重复到达不重复 resume（AwaitableTask 终态 no-op）
3. **checkpoint 一致性**：挂起时 checkpoint 含已完成节点（不含挂起节点）；恢复时注入挂起节点结果后 re-run
4. **slot 释放**：挂起时 ExecutionStatus → WAITING_EXTERNAL + Scheduler complete()；恢复时重新 submit()

## 3. 实现

### 3.1 Phase 3.4a：挂起侧

| 文件 | 改动 |
|------|------|
| `planner/protocol.py` | `ExecutionSuspended` 异常 + `delegate()` 检测 `__awaitable__` + `awaitable_task_store` 字段 + `suspended` 事件类型 |
| `planner/execution_graph.py` | `_run()` 透传 + `_run_graph_in_place` 捕获 + checkpoint save |
| `applications/agent_server/main.py` | 装配 `awaitable_task_store` |

### 3.2 Phase 3.4b：回调 + 恢复

| 文件 | 改动 |
|------|------|
| `applications/agent_server/api/callback.py` | 新文件：`POST /api/callback/{task_id}` |
| `applications/agent_server/api/routes.py` | 注册 callback_router |
| `applications/agent_server/main.py` | 装配 resume 依赖 |

## 4. 验收标准

- Skill 返回 `{"__awaitable__": True, "task_id": "ext-123"}` → SSE 产出 `suspended` 事件
- checkpoint 保存（resumable=True），不含挂起节点
- callback 到达 → AwaitableTask COMPLETED → checkpoint 注入 → 执行恢复
- 重复 callback → 幂等（no-op）
- 同步 Skill 路径不受影响
- 现有测试全绿
