# 部署指南（Deployment）

> 本文件描述 agent-platform 的运行时部署约束与推荐拓扑。重点标注 **multi-worker / 多副本** 下的已知限制。

## 单副本 / 单 worker（当前默认，推荐）

```bash
# 单进程、单 worker：同 session 串行、异 session 并发保证成立
uvicorn agent_server.main:app --port 8000 --workers 1
```

或容器化时 `replicas: 1`。`SessionCoordinator` 的会话互斥在此拓扑下完全有效。

## multi-worker 部署约束（重要）

> ⚠️ **`SessionCoordinator` 是 process-local 协调器。**

`packages/agent-runtime/agent_runtime/coordinator.py` 的 `__doc__` 已自我声明：其「同 session 串行、异 session 并发」保证依赖一组 **进程内 asyncio 状态**（`_active` / `_queues` / `_conditions` / `_cancelled`），**仅在单进程实例下成立**。

以下部署方式会**破坏**该保证：

| 部署形态 | 是否安全 | 原因 |
|---|---|---|
| `uvicorn --workers 1`（单副本） | ✅ 安全 | 全量状态在同一进程 |
| `uvicorn --workers N`（`N>1`） | ❌ 不安全 | 同 session 请求可能落到不同 worker 并行执行 |
| K8s `replicas > 1` | ❌ 不安全 | 同上，跨 Pod 无共享协调 |
| 多副本 + 滚动更新瞬时 | ❌ 不安全 | 旧/新副本并存期间同样无跨进程互斥 |

### 不一致根因

checkpoint 已分布到 PG（状态是分布式的），但会话级 execution ownership 仍是本地的 —— 即「状态分布式、协调本地」的错配。后果：同 session 的并发请求可能并行执行，绕过 `SessionCoordinator` 的互斥。

### 上线前必须二选一

1. **保持单副本 / 单 worker**：最简单，当前 v2 默认形态即满足。
2. **先做分布式 session ownership（见 P4-1）**：将 `_active` 的进程内 dict 上移为 PG advisory lock / lease 表，或交由 admission / durable execution 系统持有。未完成前 **不要** 以 `workers>1` 或多副本部署。

> 关联代码契约：[`coordinator.py` `__doc__`](packages/agent-runtime/agent_runtime/coordinator.py)（架构审核 P0 段）。
> 演进方向见 `docs/plan-f-single-runtime-multi-planner.md`。

## 其他运行时开关

`applications/agent_server/config.py` 中与部署相关的关键配置：

- `max_skill_depth` / `max_steps`：agentic 组合护栏边界（deterministic 静态 DAG 不使用）。
- `max_execution_seconds`：单次 execution 的 wall-clock 上限（秒），经 `PlannerRuntime.max_duration_seconds` 注入 `execution()` 边界，由 `execute_graph` 按层检查 deadline 提前终止。
