# Plan：B 组架构落差修复方案（B-2 / B-3 / B-5）

> **创建时间**：2026-09-23
> **状态**：方案制定完成，待确认后实施
> **前置**：P0×4 + P1×3 + C×11 + B-4 已修复并落盘（commit `37d9342` / `a0870b6` / `194c723`）

---

## B-2：federation PlannerRuntime 缺 pool/checkpoint/trajectory/llm 注入

### 问题

`applications/agent_federation/planners/__init__.py:52-57` 的 `get_planner_runtime()` 只传 4 个参数：

```python
PlannerRuntime(
    registry=registry,                              # 默认 None
    max_skill_depth=env_int("FED_MAX_SKILL_DEPTH", 4),
    max_steps=env_int("FED_MAX_STEPS", 20),
    max_duration_seconds=env_int("FED_MAX_DURATION_SECONDS", 60),
)
```

**缺失 11 项**：`llm` / `pool` / `trajectory_store` / `checkpoint_store` / `side_effect_store` / `ownership_store` / `post_execution_hooks` / `max_tokens` / `max_cost` / `enable_loop_fingerprint` / `replica_id`。

### 影响

- 无 checkpoint/resume：联邦 agentic 执行不可恢复
- 无 trajectory：无执行轨迹持久化，无法 replay/forensic
- 无 LLM usage 计量：token/cost 预算空转
- 无记忆沉淀：`post_execution_hooks`（EpisodicSink/ProceduralSink）未注入
- 无副作用审计：`side_effect_store` 缺失，HA resume 无法判断哪些 step 已落地

### 前提条件（已满足）

| 依赖 | 状态 | 来源 |
|------|------|------|
| `init_pool()` 在 lifespan 调用 | ✅ | `api/server.py:81` |
| `get_pool()` 可用 | ✅ | `agent/db.py` re-export from `agent_runtime.db` |
| `PgCheckpointStore` | ✅ | `agent_runtime/planner/durability_pg.py:53` |
| `PgTrajectoryStore` | ✅ | `agent_runtime/trajectory/store_pg.py:27` |
| `PgSideEffectStore` | ✅ | `agent_runtime/planner/durability_pg.py:395` |
| `PgExecutionOwnershipStore` | ✅ | `agent_runtime/planner/durability_pg.py` |
| `build_chat_model` (llm) | ✅ | `agent_core.llm` |

### 方案

**改动文件**：`applications/agent_federation/planners/__init__.py`

**策略**：在 `get_planner_runtime()` 中懒构建 PG stores + llm + hooks，注入 PlannerRuntime。

```python
def get_planner_runtime() -> PlannerRuntime:
    global _runtime_singleton, _runtime_bridge_flag
    bridge = _bridge_enabled()
    if _runtime_singleton is None or _runtime_bridge_flag != bridge:
        registry = ...  # 现有逻辑不变

        # 懒构建 PG stores（pool 未初始化时跳过，退化为 InMemory）
        pool = None
        checkpoint_store = None
        trajectory_store = None
        ownership_store = None
        side_effect_store = None
        try:
            from agent_runtime.db import get_pool
            pool = get_pool()
            from agent_runtime.planner.durability_pg import (
                PgCheckpointStore, PgSideEffectStore, PgExecutionOwnershipStore,
            )
            from agent_runtime.trajectory.store_pg import PgTrajectoryStore
            checkpoint_store = PgCheckpointStore(pool)
            trajectory_store = PgTrajectoryStore(pool)
            ownership_store = PgExecutionOwnershipStore(pool)
            side_effect_store = PgSideEffectStore(pool)
        except Exception as exc:
            logger.warning("PG stores 构建失败，退化为 InMemory: %s", exc)

        # llm（可选，构建失败不致命）
        llm = None
        try:
            from agent_core.llm import build_chat_model
            llm = build_chat_model()
        except Exception:
            pass

        _runtime_singleton = PlannerRuntime(
            registry=registry,
            llm=llm,
            pool=pool,
            max_skill_depth=env_int("FED_MAX_SKILL_DEPTH", 4),
            max_steps=env_int("FED_MAX_STEPS", 20),
            max_duration_seconds=env_int("FED_MAX_DURATION_SECONDS", 60),
            checkpoint_store=checkpoint_store,
            trajectory_store=trajectory_store,
            side_effect_store=side_effect_store,
            ownership_store=ownership_store,
            enable_loop_fingerprint=os.getenv("FED_ENABLE_LOOP_FINGERPRINT", "").lower() in ("1", "true"),
            replica_id=os.getenv("FED_REPLICA_ID", "federation"),
        )
        _runtime_bridge_flag = bridge
    return _runtime_singleton
```

**注意**：`post_execution_hooks` 暂不注入——联邦 agentic 执行经 `_execute_agent_core`（deepagents 内部循环），hooks 在 `PlannerRuntime.execution()` 退出时触发，但 agentic 的 executor 是裸函数不感知 hooks。注入后 hooks 不会被调，属于死代码。待 B-3 修复（executor 感知 runtime）后再接入 hooks。

### 验收标准

1. `get_planner_runtime()` 返回的 PlannerRuntime 非 None 的 store 字段在 pool 可用时为 PG 实例
2. pool 不可用时退化为 None（不崩溃）
3. 联邦现有 134 passed 不回归

### 风险

- **低**：所有 store 实现已就绪且有单测，改动纯装配
- `get_pool()` 在 `init_pool()` 前调用会抛异常——已 try/except 兜底

---

## B-3：agentic 默认绕过 skill_guard

### 问题

`AgenticPlanner.execute()`（`agent_runtime/planner/agentic.py:147-149`）直接调 `executor(question, workspace_id)`：

```python
async with runtime.execution():
    async with runtime.skill_guard("agentic"):      # 只 guard "agentic" 这一层
        answer = await executor(question, workspace_id)  # executor 内部的子 agent 委派不经 delegate
```

deepagents 内置 `task` tool 的子 agent 委派在框架内部循环完成，不经 `runtime.delegate()` → `step_count` 恒为 1，深度/步数/循环约束不生效。

### 影响

- 无委派深度限制：理论上可无限递归（`task` → `task` → `task` ...）
- 无步数预算：子 agent 调用不计入 `ExecutionContext.step_count`
- 无轨迹：子 agent 调用不计入 `ExecutionContext.steps`
- 无 token/cost 聚合：子 agent 的 LLM 调用不经 `record_usage`

### 方案选型

| 方案 | 描述 | 侵入性 | 完整性 |
|------|------|--------|--------|
| A. 改 executor 签名接 runtime | `_execute_agent_core(question, workspace_id, runtime)` + 在 deepagents `task` tool 回调中调 `runtime.delegate` | 高（改 deepagents 内部） | 完整 |
| B. 启用 AGENTIC_RUNTIME_BRIDGE + 拦截 task | 默认开 bridge，把 `task` tool 也经 `RuntimeToolCaller` 路由 | 高（改框架行为） | 完整 |
| C. 手动步数计数器 | 在 `_execute_agent_core` 中 hook `task` tool 调用，手动 `ctx.enter_skill/exit_skill` | 中 | 部分（有计数无中间件链） |
| D. 文档化限制 + recursion_limit 兜底 | 接受 deepagents `task` 是框架边界，靠 `recursion_limit`（已加 C-5）防无限递归 | 无 | 最低但安全 |

**推荐：方案 D + 方案 C 的轻量版**

**理由**：
1. deepagents 0.7.5 是 PyPI 依赖（非自有代码），改其内部 `task` tool 侵入性过高，升级时易碎
2. `recursion_limit=50`（C-5 已修）已防止无限递归——这是安全底线
3. `AGENTIC_RUNTIME_BRIDGE=true` 已提供部分覆盖（桥接工具经 delegate），可按需启用
4. 手动步数计数器（方案 C）可在 `_execute_agent_core` 中用 `monitor.on("task_result", ...)` 监听子 agent 调用，手动调 `ctx.enter_skill`/`exit_skill`——但 `ExecutionContext` 经 contextvars 绑定，deepagents 内部 asyncio task 可能不在同一 context，需验证

### 方案 D + C 轻量版实施

**改动文件**：`applications/agent_federation/agent/main_agent.py`

1. 在 `_execute_agent_core` 中订阅 `monitor` 的 `task_result` 事件，手动计数
2. 超 `max_steps` 时抛 `SkillCompositionError`

```python
async def _execute_agent_core(task_query: str, workspace_id: str, main_agent=None) -> str:
    from agent_runtime.planner.protocol import get_current_runtime, SkillCompositionError
    runtime = get_current_runtime()
    step_counter = {"count": 0}
    max_steps = runtime.max_steps if runtime else 50

    def _on_task_result(ev):
        step_counter["count"] += 1
        if step_counter["count"] > max_steps:
            raise SkillCompositionError(f"子 agent 委派步数超上限（{max_steps}）")

    from agent_core.monitor import monitor
    monitor.on("task_result", _on_task_result)
    try:
        # ... 现有执行逻辑 ...
    finally:
        monitor.off("task_result", _on_task_result)
```

**注意**：`monitor` 是进程级单例，`on/off` 需保证异常路径也清理。`SkillCompositionError` 在 deepagents 内部循环中抛出会被 `AgenticPlanner.execute` 的 `except Exception` 捕获并转为 error 事件。

### 验收标准

1. 子 agent 委派超 `FED_MAX_STEPS` 时产生 error 事件而非无限递归
2. `recursion_limit=50` 仍作为框架级兜底
3. 联邦现有 134 passed 不回归

### 风险

- **中**：`monitor` 事件是否在 deepagents `task` tool 调用时触发需验证（若 deepagents 不发 `task_result` 事件则方案 C 无效，退为纯方案 D）
- 若无效，则接受方案 D（文档化限制），不强行改 deepagents

---

## B-5：中间件零装配

### 问题

两类未装配：

**5a. SkillRegistry 中间件未装配**（`agent_runtime/skills/middleware.py` 定义 6 个，只装了 2 个）

| 中间件 | agent_server | agent_federation |
|--------|-------------|-----------------|
| CircuitBreakerMiddleware | ✓（仅 search） | ✗ |
| ToolResultCompressionMiddleware | ✓（条件性） | ✗ |
| RetryMiddleware | ✗ | ✗ |
| RateLimitMiddleware | ✗ | ✗ |
| AuditMiddleware | ✗ | ✗ |
| GuardMiddleware | ✗ | ✗ |

**5b. 运行时组件未实例化**（定义有完整实现 + 单测，但 lifespan 未装配）

| 组件 | 定义 | 装配 |
|------|------|------|
| ExecutionScheduler | `execution_scheduler.py:481` | ✗ |
| ControlPlane | `control_plane.py:78` | ✗ |
| WorkingMemory | `working_memory.py:94` | ✗ |
| ExecutionRecovery | `execution_recovery.py:146` | ✗ |
| side_effect_store | `durability_pg.py:395` | ✗ |

### 方案

#### 5a. SkillRegistry 中间件装配（快速可做）

**改动文件**：
- `applications/agent_server/api/capabilities.py:125-136` — 追加 RetryMiddleware + AuditMiddleware
- `applications/agent_federation/planners/agentic_runtime_bridge.py:39` — 给 `SkillRegistry()` 加中间件

```python
# agent_server
middlewares = [
    CircuitBreakerMiddleware(_get_breaker(), skill_names=("search",)),
    RetryMiddleware(max_retries=3, retryable_exceptions=(TimeoutError, ConnectionError)),
    AuditMiddleware(logger=logging.getLogger("skill.audit")),
]
if settings.tool_result_compression_enabled:
    middlewares.append(ToolResultCompressionMiddleware(...))
registry = SkillRegistry(middlewares=middlewares)
```

**RateLimitMiddleware 暂不装**：需要 Redis/token bucket 后端，当前无 Redis 依赖，装入会引入新依赖。记为后续。

**GuardMiddleware 暂不装**：agent_server 的 guard 在 `context_governor` 层（ContextGovernor），非 SkillRegistry 洋葱链。联邦的 guard 在 deepagents middleware 层。两层语义不同，不强行统一。

#### 5b. 运行时组件装配（需评估必要性）

| 组件 | 评估 | 决策 |
|------|------|------|
| `side_effect_store` | B-2 已注入到 PlannerRuntime | **随 B-2 完成** |
| `ExecutionScheduler` | 联邦 agentic 走 deepagents 内部循环，不走 ExecutionScheduler 的调度队列 | **暂不装**（无消费方） |
| `ControlPlane` | 控制面是 agent_server 的 admission + coordinator 已覆盖 | **暂不装**（功能重叠） |
| `WorkingMemory` | 联邦有 `_create_store`（deepagents BaseStore），agent_server 有四类 Memory 架构 | **暂不装**（已有等价能力） |
| `ExecutionRecovery` | 需要 ExecutionScheduler 先装配（Recovery 依赖 Scheduler 的 stuck 检测） | **暂不装**（依赖链断） |

**结论**：5b 的四个组件（ExecutionScheduler / ControlPlane / WorkingMemory / ExecutionRecovery）是 V3 执行平台的编排层组件，设计用于 deterministic/graph 路径的集中调度。联邦 agentic 走 deepagents 内部循环，不消费这些组件。agent_server 的 admission + coordinator + 四类 Memory 已提供等价能力。**强行装配会产生双重编排**，违反"框架选型偏好"。

`side_effect_store` 随 B-2 注入即可。

### 验收标准

1. agent_server SkillRegistry 装配 RetryMiddleware + AuditMiddleware
2. agent_federation SkillRegistry 装配 CircuitBreakerMiddleware（至少 search 熔断）
3. 现有测试不回归

### 风险

- **低**：中间件实现已就绪且有单测，改动纯装配
- RetryMiddleware 需确认 retryable_exceptions 不误重试非幂等 Skill

---

## 实施顺序

1. **B-2**（联邦 PlannerRuntime 注入）— 改 1 文件，低风险
2. **B-5a**（SkillRegistry 中间件装配）— 改 2 文件，低风险
3. **B-3**（agentic 步数计数）— 改 1 文件，需验证 monitor 事件有效性
4. **B-5b**（side_effect_store）— 随 B-2 完成，无需独立改动

## 不做（明确豁免）

- **B-5b 的 ExecutionScheduler / ControlPlane / WorkingMemory / ExecutionRecovery**：已有等价能力，强行装配产生双重编排
- **B-3 方案 A/B**：改 deepagents PyPI 包内部，侵入性过高
- **RateLimitMiddleware**：需 Redis 依赖，当前无
- **post_execution_hooks（联邦侧）**：待 B-3 完成后 executor 感知 runtime 才能接入
