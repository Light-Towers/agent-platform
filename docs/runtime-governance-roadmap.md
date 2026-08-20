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
| P2-1 | tokens/cost 聚合器 | P2 | 0.3 | `protocol.py` (ExecutionContext) | P1-1 |
| P2-2 | llm client 计量点 | P2 | 0.5 | `agent_core/llm/` | P2-1 |
| P3-1 | Trajectory 持久化 | P3 | 1.5 | `trajectory/`(新) + `execution_graph.py` | P2-2（tokens 可后补时仅 P1-1） |
| P3-2 | Trajectory Replay | P3 | 2 | `eval/replay/`(新) | P3-1 |
| P4-1 | 分布式 session lease | P4 | 3 | `coordinator.py` | P0-1 |
| P4-2 | 收紧 registry.execute | P4 | 0.5 | `registry.py` + CI lint | — |
| P4-3 | coalesce 改名/真实现 | P4 | 0.3–1 | `coordinator.py` | — |
| P5-1 | TrajectoryFingerprint | P2 | 1.5 | `fingerprint.py`(新) | — |

---

## P2 — ExecutionBudget 扩展

### P2-1 引入 `tokens` / `cost` 预算聚合器
- **改动文件**：`packages/agent-runtime/agent_runtime/planner/protocol.py`（`ExecutionContext`）
- **改动内容**：`ExecutionContext` 增加 `tokens_used: int = 0`、`cost_used: float = 0.0`、`max_tokens: int | None = None`、`max_cost: float | None = None` 及 `record_usage(tokens, cost)` 方法。
- **关键约束（层边界）**：token/cost 计量点**不在本包**，而在 `agent-core` 的 `llm` client 层。本项只做**聚合器**，不在此埋点。
- **设计原则**：`ExecutionContext` 是聚合器 + 闸门，`agent-core llm` 是计量源，`PolicyValidator`/`PlannerRuntime` 是装配方，三者职责不重叠。
- **工作量**：0.3
- **验收**：单元测试验证 `record_usage` 累计与超限抛 `SkillCompositionError`。
- **前置**：P1-1

### P2-2 在 `agent-core` llm client 层做 token 计量（计量点）
- **改动文件**：`packages/agent-core/agent_core/llm/`（chat/completion 封装处）
- **改动内容**：LLM 调用返回处暴露 `usage`（prompt/completion tokens）；由 `agent-runtime` 的 Planner 侧消费并 `ExecutionContext.record_usage`。
- **备注**：需先评估现有 llm client 是否已透传 `usage`；若没有，这是本项唯一真正的新代码。
- **工作量**：0.5
- **验收**：一次 agentic 执行后，`status` snapshot 能带出累计 tokens。
- **前置**：P2-1

---

## P3 — Trajectory（在 Budget 闭环后）

P2-1 与 P3-1 的**并行关系取决于 P3-1 是否硬依赖 token 计量点**：若 trajectory 的 `tokens` 字段允许后补（`None` 占位），则 P3-1 仅依赖 P1-1（可并行）；若硬依赖计量点，则 P3-1 前置 P2-2（与汇总表一致）。P3-2（Replay）始终依赖 P3-1（持久化）。

### P3-1 Trajectory 持久化
- **改动文件**：新增 `packages/agent-runtime/agent_runtime/trajectory/`（存储 + schema）；`execution_graph.py` 的 `execute_plan` 末尾挂持久化。
- **改动内容**：
  - 基于 `ContextManager.snapshot()`（`context_manager.py:148-150`）已有的结构化输出，补充 `execution_id`、`parent_execution_id`、`session_id`、`planner`、`plan`、每步 `latency`/`tokens`。
  - `AgentContext.metadata`（`context_manager.py:75`）已有扩展位，可承载 `execution_id` 等关联字段，不必改 snapshot 结构。
  - 写入存储（PG 表或 OTel span），`status` 事件已产出 snapshot（`execution_graph.py:243,252`），持久化在此消费即可。
- **工作量**：1.5
- **验收**：一次执行后，按 `execution_id` 可查询完整轨迹（skill / args / result / latency / tokens / errors）。
- **理由**：`record_skill` + snapshot 模型已落地，缺的只是存储与查询，不是模型。

### P3-2 Trajectory Replay（依赖 P3-1）
- **改动文件**：新增 `eval/replay/` 或 `packages/agent-runtime/.../replay.py`
- **改动内容**：读取轨迹 → Mock LLM/Tool → 重放 → 与原始结果比对找 divergence（route 变化、skill 顺序变化、多余调用）。
- **工作量**：2
- **验收**：能对一条 golden 轨迹重放并报告 divergence 点。
- **前置**：P3-1

---

## P4 — 分布式 / Recovery（生产级成熟度的最后一块）

### P4-1 分布式 Session Ownership（PG lease）
- **改动文件**：`packages/agent-runtime/agent_runtime/coordinator.py`
- **改动内容**：把 `_active` 的进程内 dict 换成 PG `advisory lock` 或 `lease` 表；`acquire`/`release` 改走 DB。保留当前 asyncio 实现为单进程快速路径，双写。
- **工作量**：3
- **验收**：两个进程同 session 并发请求，只有一个能 `serialize`，另一个 `queue`/`reject`。
- **前置**：P0-1（部署约束文档）必须同时存在，避免在 lease 落地前误导多副本部署。
- **备注**：v2 当前单进程部署下无实际暴露，优先级取决于「是否近期要多副本」。

### P4-2 收紧 `registry.execute` 的直接可见性
- **现状（已核实三处直调）**：`protocol.py:273-274`（delegate 边界外回退）、`agent_server/agent/graph.py:60-64`（`_invoke` 回退）、`deterministic.py:202,209`（`_run_capability` 直调）。
- **改动内容**：Python 无真 private，实际手段 = ①命名约定（如 `_execute_internal`）②CI lint 规则（禁止 `registry.execute(` 出现在 `skills/` 外部）③文档契约声明「Skill→Skill 唯一合法路径是 `runtime.delegate()`」。
- **关键**：**不要现在就改三处调用**——它们是宿主代码、行为正确，改坏风险大于收益，先以 lint/文档约束。
- **工作量**：0.5
- **验收**：CI 加一条 grep 规则，非白名单文件出现 `registry.execute(` 或 `get_registry().execute(` 即失败（`agent/graph.py:64` 的调用形态是 `get_registry().execute(`，两种形态都要覆盖）。

### P4-3 真实现 coalesce（或诚实改名）
- **改动文件**：`coordinator.py`
- **改动内容**（二选一，推荐 A）：
  - **A（短期诚实）**：把 policy 类型字面量从 `"coalesce"/"queue"/"reject"` 收紧为 `"queue"/"reject"`，删掉 `coordinator.py:80-101` 的假 coalesce 分支；等真实现后再加。
  - **B（长期完整）**：真实现——coalesce 命中时向旧 `request_id` 发取消信号并唤醒队列，只保留最新请求。
- **工作量**：A=0.3 / B=1
- **验收**：A=policy 枚举不再含 `coalesce`；B=并发请求只执行最新一个。
- **理由**：`coordinator.py:82-84` 注释已自认退化为 queue，名称 ≠ 语义是架构债。

---

## P5 — Semantic Loop Detection（结构检测增强）

### P5-1 `TrajectoryFingerprint`
- **改动文件**：`packages/agent-runtime/agent_runtime/planner/`（新模块 `fingerprint.py`）或 `protocol.py`
- **改动内容**：`skill + normalized args + state hash + result class` 的组合指纹，记录在 `ExecutionContext`；发现重复指纹时拒绝继续（抛 `SkillCompositionError`）。
- **注意**：`normalized args` 对可变对象 / 大 payload 需先做规范化（排序键、截断、类型降级），避免哈希不稳定或超大。
- **工作量**：1.5
- **验收**：`search("北京天气")` 后 `search("北京今天的天气")` 不同参数不误报；完全重复的 `A→B→A'`（同 args 同 result class）能拦。
- **定位**：结构检测（`protocol.py:142` 的 `name in call_stack`）已够用，这是增强项，不阻塞任何东西。
- **备注**：编号 P5 是类别号（Semantic Loop Detection 区段），**非优先级**；优先级以「汇总表」列为准。

---

## 外部审核要点建议

1. **优先级与依赖**：P2-1 → P2-2 硬依赖；P3-1 的前置为 P2-2（trajectory 的 `tokens` 字段若允许后补，则降级为仅依赖 P1-1，可与 P2-1 并行）；P3-2 依赖 P3-1；P4-1 依赖 P0-1（已完成）；P4-2/P4-3/P5-1 可独立开工。
2. **风险点**：P2-2 需先核实 `agent-core` llm client 是否已透传 `usage`（决定是真新代码还是接线）；P4-1 工作量最大且涉及双写一致性。
3. **范围边界**：P4-2 明确要求**不要**改三处现有直调调用，仅加 lint/文档约束，避免回归。
4. **已完成基线**：P0-1（`docs/deployment.md`）+ P1-1/1-2/1-3（`protocol.py` / `execution_graph.py` / `config.py` / `main.py` / `tests/test_execute_plan.py`，7 测试通过）。
