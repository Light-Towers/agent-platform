# Runtime Governance 后续任务清单（Roadmap，待外部审核）

> 本文件是 [deployment.md](deployment.md) 之外、v2 Runtime Governance 的**后续可选**任务清单。
> 「本次治理闭环」（P0-1 + P1-1/1-2/1-3）已完成，本文件仅列 P2 及以上、按依赖顺序排优先级。
> 每项标注：改动文件 / 改动内容 / 工作量（人工天）/ 验收标准 / 前置依赖。
> 供外部模型审核排期用，未开始实现。

> ⚠️ **第三方审核稿已部分过时**：以下 6 项在审核稿中被判「成立/缺失」，但当前代码已实现，请勿重复「从零重建」：
> 1. `Plan` 已有 `mode` + `graph` 字段（`protocol.py:61,66`）；
> 2. `GraphPlanner` 已打通 `Plan→PolicyValidator→execute_graph`（`applications/agent_server/planners/graph.py:83-91`）；
> 3. `execute_plan` 已强制 `PolicyValidator.validate()`（`execution_graph.py:223-228`）；
> 4. `registry._validate_output` 已实现并调用（`skills/registry.py:157,290`，轻量 type 校验）；
> 5. `execute_graph` 的 `_run` 已节点级异常隔离（`execution_graph.py:160-165`）；
> 6. `deadline` 已由 P1-1 接入并在 `execute_graph` 消费。
> **真正的缺口**是：新控制平面（graph 路径）已完整但**非默认**——`config.py:102` 默认 `planner="deterministic"`，`DeterministicPlanner` 仍走 `route→registry.execute`，`AgenticPlanner` 包装 `_execute_agent_core`（deep_agent 黑盒，不经 `registry`），两者均不产出 `graph`。后续优先级见下方 §0。

> **已完成基线速览**（P0-1 + P1-1/1-2/1-3 均已完成并验证）：
> - **P0-1** 部署约束文档 → `docs/deployment.md`（multi-worker 约束 + coordinator.py 链接）。
> - **P1-1** deadline 闭环 → `config.py:112` `max_execution_seconds` → `main.py:152` → `protocol.py:226-233`（`execution()` 建 deadline）→ `execution_graph.py:150-158`（逐层消费）；测试 `test_execute_plan_deadline_aborts`。
> - **P1-2** max_parallel 接线 → `execute_plan(max_parallel=...)` → `policy.py:66-69`；已接线但无调用方（GraphPlanner 未传）。
> - **P1-3** 回归测试 → `tests/test_execute_plan.py`：`test_execute_plan_deadline_aborts` / `test_execute_plan_max_parallel_rejected`（7 测试通过）。

## 0. 真正的架构缺口（与外部审核稿对齐后的修正版）

审核稿把问题归因为「模块缺失 / 完全没接」，但实测当前代码**模块都在、新链路也已打通**，核心缺口是 **Runtime 迁移未完成**：

- 🔴 **P0（真正第一刀）**：让 graph 控制平面成为**默认主链**。
  - `Plan → PolicyValidator → execute_graph` 已存在且可用，但默认 `deterministic` planner 绕过它。
  - 建议：`DeterministicPlanner.execute` 重构为「先 `plan()` 产出（可选）`graph`，再统一走 `execute_plan`」；或把默认 `settings.planner` 切到 `graph` 并补足 GraphPlanner 的多 Skill 组合（当前只选 Top-1 单节点）。
  - agentic **不**应被强行 DAG 化；而是：agentic 主入口保留 `execution()` + `skill_guard`，其动态产生的 Skill 调用经 `delegate()` 仍受护栏，未来可选择性把「已决定子图」回写为 `ExecutionGraph` 供 `PolicyValidator` 校验。
- 🟠 **P1（新链路稳固后补）**：ContextManager 成为统一上下文事实来源；中文/semantic Skill Discovery；`PolicyValidator` 增 cost/parallelism/resource 约束；`max_parallel` 真正被 planner 设置（P1-2 已接线但无调用方）。
- 🟡 **P2（迁移清理）**：`delegate` 无 `execution()` 边界的兼容 fallback 暂保留（有意设计）；`delegate_ref` mutable holder 值得重构但非优先。

> 注意：原审核稿里被判 P0 的「Plan 缺 graph」「PolicyValidator 未成闸门」「output_schema 未校验」「节点失败拖垮整层」「deadline 未闭环」**均已不成立**，排期时勿再分配工作量。

## 汇总表

| 编号 | 项 | 优先级 | 工作量(天) | 核心改动文件 | 前置 |
|---|---|---|---|---|---|
| P2-1 | tokens/cost 聚合器 | P2 | 0.3 | `protocol.py` (ExecutionContext) | P1-1 | ✅ 已落地（2026-08-21）：ExecutionContext 新增 tokens_used/cost_used/max_tokens/max_cost + record_usage() 方法，超限抛 SkillCompositionError；PlannerRuntime 透传 max_tokens/max_cost 配置 |
| P2-2 | llm client 计量点 | P2 | 0.5 | `agent_core/llm/` | P2-1 | ✅ 已落地（2026-08-21）：计量源 `FallbackChatModel`/`LangChainFallbackModel` 抽取 `usage_metadata`（含 `response_metadata` 兜底）→ `on_usage` 回调外发；`PlannerRuntime` 装配期把 `llm.on_usage` 接到当前 `ExecutionContext.record_usage`（contextvars 按 task 隔离，边界外静默丢弃）；`execute_plan` 的 `status` 事件带出累计 `tokens_used`/`cost_used` |
| P3-1 | Trajectory 持久化 | P3 | 1.5 | `trajectory/`(新) + `execution_graph.py` | P2-2（tokens 可后补时仅 P1-1） | ✅ 已落地（2026-08-21）：`agent_runtime/trajectory/`（models/store/store_pg/replay）+ `execute_plan` 末尾 `_persist_trajectory` 挂持久化 + `PlannerRuntime.trajectory_store` 注入 + 宿主 `main.py` 装配 `PgTrajectoryStore` |
| P3-2 | Trajectory Replay | P3 | 2 | `eval/replay/`(新) | P3-1 | ✅ 已落地（2026-08-21）：`trajectory/replay.py`（`replay_trajectory` 复用 `execute_plan` 真实执行链，报告 order/extra_call/missing_call/result_change/error_change 五类 divergence） |
| P4-1 | 分布式 session lease | P4 | 3 | `coordinator.py` | P0-1 |
| P4-2 | 收紧 registry.execute | P4 | 0.5 | `registry.py` + CI lint | — | ✅ 已落地（2026-08-21）：架构约束 lint 脚本 `scripts/lint_architecture.py` + Makefile `lint` 目标串联 |
| P4-3 | coalesce 诚实改名/真实现 | P4 | 0.3 | `coordinator.py` | — | ✅ 已落地（2026-08-21）：方案 A（诚实改名），coalesce 从策略枚举移除，仅保留 queue/reject 二策略 |
| P5-1 | TrajectoryFingerprint | P2 | 1.5 | `fingerprint.py`(新) | — | ✅ 已落地（2026-08-21）：`protocol.py` 的 `_fingerprint`（skill + 归一化 kwargs，键序无关）+ `ExecutionContext.fingerprints` 重复指纹拒绝；`enable_loop_fingerprint` 默认关闭防误伤合法重放 |

---

## P2 — ExecutionBudget 扩展

### P2-1 ✅ 已落地（2026-08-21）
- **改动文件**：`packages/agent-runtime/agent_runtime/planner/protocol.py`
- **改动内容**：`ExecutionContext` 新增 `tokens_used: int = 0` / `cost_used: float = 0.0` / `max_tokens: int | None = None` / `max_cost: float | None = None` 字段及 `record_usage(tokens, cost)` 方法（累计 + 超限抛 `SkillCompositionError`）；`PlannerRuntime.__init__` 新增 `max_tokens` / `max_cost` 参数，`execution()` 入口透传至 `ExecutionContext`。
- **设计原则**：`ExecutionContext` 是聚合器 + 闸门，`agent-core llm` 是计量源（P2-2），`PlannerRuntime` 是装配方，三者职责不重叠。
- **工作量**：0.3
- **验收**：单元测试验证 `record_usage` 累计与超限抛 `SkillCompositionError`。

### P2-2 ✅ 已落地（2026-08-21）
- **改动文件**：`packages/agent-core/agent_core/llm/fallback.py`（计量源：`on_usage` 回调 + `_extract_usage` + `_emit_usage` + 流包装 `_wrap_stream`/`_wrap_astream`）；`packages/agent-core/agent_core/llm/fallback_lc.py`（`LangChainFallbackModel` 转发 `on_usage`）；`packages/agent-runtime/agent_runtime/planner/protocol.py`（`PlannerRuntime` 装配期接线 `_on_llm_usage`）；`packages/agent-runtime/agent_runtime/planner/execution_graph.py`（`status` 事件带 `tokens_used`/`cost_used`）。
- **改动内容**：评估结果——底层 LangChain 客户端（`ChatOpenAI`）本就携带 `usage_metadata`，但此前 `FallbackChatModel` 透传原始 `AIMessage` 不做抽取，故本项是**真新代码（计量点）**而非单纯接线。计量源职责：从 `AIMessage.usage_metadata`（pydantic/dict）或 `response_metadata.usage` 抽取 `total_tokens`（缺失时回退 `input+output`），经 `on_usage(tokens, cost)` 回调外发；cost 在本层无定价信息恒为 0.0。装配方职责：`PlannerRuntime.__init__` 对具备 `set_on_usage` 的 llm 注入回调，回调在 LLM 调用发生时读当前 `ExecutionContext`（contextvars 隔离）并 `record_usage`；边界外静默丢弃。三者职责不重叠（计量源 / 聚合器 / 装配方）。
- **工作量**：0.5
- **验收**：`tests/test_p2_2_usage_metering.py` 10 passed——覆盖 `usage_metadata`/`response_metadata` 抽取、invoke/ainvoke/stream/astream 四路径外发、runtime 接线累计、边界外丢弃、`status` 事件带 tokens。
- **前置**：P2-1

---

## P3 — Trajectory（在 Budget 闭环后）

P2-1 与 P3-1 的**并行关系取决于 P3-1 是否硬依赖 token 计量点**：若 trajectory 的 `tokens` 字段允许后补（`None` 占位），则 P3-1 仅依赖 P1-1（可并行）；若硬依赖计量点，则 P3-1 前置 P2-2（与汇总表一致）。P3-2（Replay）始终依赖 P3-1（持久化）。

### P3-1 ✅ 已落地（2026-08-21）
- **改动文件**：新增 `packages/agent-runtime/agent_runtime/trajectory/`（`models.py` TrajectoryRecord/TrajectoryStep + `store.py` 契约与内存实现 + `store_pg.py` PG 实现 + `replay.py`）；`execution_graph.py` 的 `execute_plan` 末尾 `_persist_trajectory`；`planner/protocol.py`（`trajectory_store` 注入 + ExecutionContext.steps 逐步明细）。
- **改动内容**：`TrajectoryRecord` 含 `execution_id / parent_execution_id / session_id / planner / plan / steps（skill+args+result+error+latency+tokens）/ total_tokens / total_cost / snapshot / created_at`。存储契约 `TrajectoryStore`（save / get / list_by_session）三实现：`InMemoryTrajectoryStore`（LRU 上限，单进程默认）、`PgTrajectoryStore`（PG 持久化，`_coerce_record` 反序列化复用）；宿主 `agent_server/main.py` 装配期 pool 非 None 时注入 `PgTrajectoryStore`。tokens 字段由 P2-2 计量闭环直接写入 `total_tokens`。
- **验收**：`tests/test_trajectory.py`——execute_plan 后按 `execution_id` 可查询完整轨迹（skill / args / result / latency / tokens / errors），`list_by_session` 按 session 倒序。

### P3-2 ✅ 已落地（2026-08-21，依赖 P3-1）
- **改动文件**：`packages/agent-runtime/agent_runtime/trajectory/replay.py`
- **改动内容**：`replay_trajectory` 复用 `execute_plan` 真实执行链（重放注册表作 registry），比对逻辑与执行解耦（`_RecordingWrapper` 记录 actual_steps）。五类 divergence：`order`（同序位 skill 名变化/route 漂移）、`extra_call`（重放超出录制步数）、`missing_call`（录制存在但重放未触发）、`result_change`（同 skill 成功但结果变化）、`error_change`（成功/失败状态反转）。`ReplayReport` 带 `diverged` 属性与 `to_dict()` 序列化。
- **验收**：`tests/test_trajectory_replay.py`——对 golden 轨迹重放并报告各 divergence 点。
- **前置**：P3-1 ✅

---

## P4 — 分布式 / Recovery（生产级成熟度的最后一块）

### P4-1 ✅ 已落地（2026-08-21，可插拔 lease 后端）
- **改动文件**：`packages/agent-runtime/agent_runtime/coordinator.py`（新增 `LeaseBackend` / `InMemoryLeaseBackend` / `PgAdvisoryLeaseBackend`）
- **改动内容**：`_active` 进程内 dict 抽成可插拔 `LeaseBackend`——默认 `InMemoryLeaseBackend`（asyncio 进程内快路径，行为与旧 `_active` 一致）；多副本注入 `PgAdvisoryLeaseBackend`（`session_leases` 表 `INSERT ... ON CONFLICT DO UPDATE WHERE expires_at<now()` 单飞授权 + TTL 自动过期防崩溃死锁 + 双写本地镜像）。`serialize` 授权经 `lease.try_acquire` 单飞：仅一个 owner 成功，其余走 queue/reject。`Coordinator(lease_backend=, lease_ttl=)` 注入式；`release` 经 `lease.release`（未持有则 no-op）。
- **工作量**：3（实现 + 单测）
- **验收**：`tests/test_session_lease.py` 覆盖 InMemory 单飞/释放、PG 单飞/双写/TTL 过期/错误 owner 释放 no-op、Coordinator 注入后端后同 session 仅一 owner、`PgAdvisoryLeaseBackend` 模拟跨进程并发拒绝。
- **前置**：P0-1（部署约束文档）已存在，避免 lease 落地前误导多副本部署。
- **已知局限**：跨进程 queue 唤醒（B 进程排队后 A 进程 release 需跨进程通知）仍需 durable execution，不在本期；单进程部署完全等价旧行为。多副本启用前需建 `session_leases` 表（DDL 见部署文档）。

### P4-2 ✅ 已落地（2026-08-21）
- **改动文件**：新增 `scripts/lint_architecture.py`；`Makefile` lint 目标串联。
- **改动内容**：架构约束 lint 检测 `registry.execute(` / `get_registry().execute(` 在白名单外的直接调用；白名单含 `protocol.py`（delegate 实现）、`graph.py`（_invoke 回退）、`registry.py`（自身）及测试/评测目录。
- **验收**：`uv run python scripts/lint_architecture.py` 通过；`make lint` 串联执行。
- **关键**：三处现有直调调用未改动（宿主代码、行为正确），仅以 lint/文档约束新增调用。

### P4-3 ✅ 已落地（2026-08-21，方案 A 诚实改名）
- **改动文件**：`coordinator.py`、`schemas.py`、`agent_server/config.py`
- **改动内容**：coalesce 从策略枚举中移除（`Literal["queue", "reject"]`），退化的 coalesce 分支（与 queue 等价）删除，`CoordinationDecision.decision_type` 同步移除 `"coalesce"`。
- **验收**：`ruff check` 全绿 + 根 tests 全绿（零回归）。
- **后续**：若需真 coalesce（取消旧请求），按方案 B 独立专项实施。

---

## P5 — Semantic Loop Detection（结构检测增强）

### P5-1 ✅ 已落地（2026-08-21，默认关闭的增强项）
- **改动文件**：`packages/agent-runtime/agent_runtime/planner/protocol.py`
- **改动内容**：`_fingerprint(name, kwargs)`（skill + 归一化 kwargs，sha256，键序无关）记录在 `ExecutionContext.fingerprints`；`enter_skill` 发现重复指纹时抛 `SkillCompositionError` 拒绝继续。`PlannerRuntime(enable_loop_fingerprint=)` 装配开关，**默认关闭**避免误伤合法重放/重规划（同入参重复调用是重放场景的合法行为）。
- **验收**：`tests/test_p5_1_fingerprint.py`——`A→B→A'`（同入参）能拦；不同入参同名 Skill 不误报；kwargs 键序无关；默认关闭时同入参重复调用放行。
- **定位**：结构检测（`name in call_stack`）仍为默认第一道防线，指纹为可选增强。
- **备注**：编号 P5 是类别号（Semantic Loop Detection 区段），**非优先级**；优先级以「汇总表」列为准。

---

## 外部审核要点建议

1. **优先级与依赖**：P2-1 → P2-2 硬依赖；P3-1 的前置为 P2-2（trajectory 的 `tokens` 字段若允许后补，则降级为仅依赖 P1-1，可与 P2-1 并行）；P3-2 依赖 P3-1；P4-1 依赖 P0-1（已完成）；P4-2/P4-3/P5-1 可独立开工。
2. **风险点**：P2-2 需先核实 `agent-core` llm client 是否已透传 `usage`（决定是真新代码还是接线）；P4-1 工作量最大且涉及双写一致性。
3. **范围边界**：P4-2 明确要求**不要**改三处现有直调调用，仅加 lint/文档约束，避免回归。
4. **已完成基线**：P0-1（`docs/deployment.md`）+ P1-1/1-2/1-3（`protocol.py` / `execution_graph.py` / `config.py` / `main.py` / `tests/test_execute_plan.py`，7 测试通过）。
