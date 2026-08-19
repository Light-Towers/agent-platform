# Plan-F：单 Runtime + 多 Planner（双轨收敛）

> **状态**：ACTIVE（2026-08-19 启动）
> **定位**：取代 plan-e 的"双轨收敛"表述，精确化为"单 Runtime + 多 Planner"
> **触发信号**：用户提出"多轨并行维护成本太高"——真实需求驱动，非过度设计

---

## 1. 背景与问题

agent-platform 存在两条独立部署的编排轨：

| | `app/` | `agent_federation/` |
|---|---|---|
| 形态 | 单进程 Supervisor | 联邦网关 + 子服务编排 |
| 入口 | `app/main.py` FastAPI（SSE `/query`） | `api/server.py` FastAPI（WS `/ws/{thread_id}`） |
| 编排 | 显式 `StateGraph`（route→capability→synthesize） | `create_deep_agent`（tool-calling 委派） |
| 状态 | `AgentState`（Pydantic，含 route/evidence/iterations/mcp_*） | LangChain messages + thread |
| 外壳 | `infra/`：admission/coordinator/revert/otel/mcp/tracing | `gateway/`：rate_limit/gray/guard + intent/cache/singleflight |
| 测试 | 无 tests 目录（薄弱） | 12 个测试文件（完备） |
| 可观测 | otel.py / tracing.py（薄） | langfuse/clickhouse/minio/valkey 全套 |

**维护痛点**：两套编排 + 两套外壳 + 两套配置 + 两套部署 = 每次能力增强要改两处。

**关键事实（侦察确认）**：
- 两轨**底层都是 LangGraph**——"哲学差异"是路由决策机制，不是框架对立
- `agent-core`（5578 行）已共享——能力层已经收敛，真正双份的只有编排层与外壳
- 联邦 `_LOCAL_FALLBACK_MODULES` 已具备"远程子服务挂本地兜底"机制——能力注册表的基础已存在
- 联邦 `STORE_POSTGRES_DSN` 已支持 PostgresStore——状态层向 PG 收敛的代码已存在
- 联邦 `deepagents`→`agent_federation` 改名（2026-08-19）——认知成本累积中

---

## 2. 卡点分析（K1–K5，审核后修正版）

### K1：双编排层

~~route_mode 开关~~ → **Planner Strategy 接口**（审核修正）。

原因：一个 boolean 承载不了三组差异——状态模型（`AgentState` vs messages）、拓扑（固定 DAG vs 动态委派）、失败/流式语义（图内 retry + SSE vs agent self-reasoning + WS）。决策方式不同应抽象为**策略接口**，而非图内开关。

### K2：外壳不对称（双向）

不是"app 有外壳联邦没有"，而是**两套外壳各强化一侧**：

| 侧 | app 独有 | 联邦独有 |
|---|---|---|
| 内容 | admission/coordinator/revert/SSE/compaction | intent/语义缓存/singleflight/rate_limit/gray/langfuse/monitor/动态角色(P5) |

方向：**外壳横向化（取并集）**，迁入共享 `agent-runtime`，而非单向"app 补到联邦"。

### K3：数据库栈

- 状态存储：联邦已支持 PG（PostgresStore + pgvector + bge）→ **统一 PG**
- 业务数据：wenda MySQL 是 **domain 数据，保留隔离**（不强制全 PG）
- SQL guard 已统一为 `agent_core.sql.guard(dialect=...)`——方言是参数非分支

### K4：端口/部署

两套 compose 都写死 :8000 → 收敛后单 compose 单入口。

### K5：能力层半重叠

app 的 search/rag/sql/mcp（进程内节点）与联邦 `database_query_agent`/`network_search_agent`/`knowledge_base_agent`（本地 subagent）功能重叠。→ **Capability Registry**（见 §4），避免"全 agent 化"。

---

## 3. 风险清单（审核补充后）

| 风险 | 内容 | 缓解 |
|---|---|---|
| **R0 Runtime ownership conflict（最高）** | retry/timeout/cancellation/memory/tracing/streaming 归属不清 → `retry(retry(agent(tool())))` 套娃 | **决策/执行分离**：retry/超时/熔断归 Runtime 对 capability 调用的统一边界；Planner 只决策不执行（契约点 P1） |
| R1 行为漂移 | app 12 golden（deterministic）vs 联邦无等价基线 | 双跑 eval 基线（P5）→ app 侧 `eval/run_planner_eval.py` 已闭环；联邦侧 `eval/run_eval.py` 已加 `--baseline`/`--compare` 漂移门禁（2026-08-19 收尾） |
| R2 外壳迁移遗漏 | admission/coordinator/revert 是生产外壳，plan-e §3 硬约束禁止弱化 | 逐模块独立迁移 + 双轨回归 |
| R3 范围爆炸 | 6000+4000 行一次性合并 | Phase 0–3 拆分，每阶段 `make test` + eval 门禁 |
| R4 数据归属 | app PG 存量 vs 联邦 Mongo/MySQL | 先统一 ThreadState 契约（P2），再迁存量 |
| R5 认知成本 | 9 包 monorepo + 改名 | 收敛后 AGENTS.md 改"单 Runtime 多 Planner"表述 |
| R6 违反不过度设计 | 结构性重构 | 用户"维护成本高"为真实需求信号；按阶段验证收益再推进 |

---

## 4. 目标架构

```
                    API Gateway (SSE / WS adapter)
                             |
                    agent-runtime   ← 新增共享包（runtime middleware）
        admission / session / checkpoint / tracing
        cache / rate_limit / circuit_breaker / mcp
                             |
             -------------------------------
             |                             |
    DeterministicPlanner          AgenticPlanner   ← 统一 Planner 协议
             |                             |
             -------------------------------
                             |
                   Capability Registry
          FunctionExecutor | AgentExecutor | RemoteExecutor
                             |
              --------------------------------
              |          |          |         |
             RAG        SQL       Search     MCP
                     (capability 执行，retry/超时归 Runtime)

        状态：ThreadState(shared-schemas) → PG（统一）
        业务：wenda MySQL / 下游 domain 数据（隔离）
```

**核心原则**（架构审核确立）：
> 不要统一 Agent；统一 Runtime。
> 不要统一 Graph；统一 Capability。
> 不要统一决策方式；统一决策接口。

未来 LangGraph / DeepAgents / AutoGen / CrewAI / 自研 Planner 均可作为策略挂入。

---

### 4.1 Skill 统一能力协议（用户架构审核精确化，2026-08-19）

用户审核确立一条更上层的抽象，与 §4 核心原则**同构而非冲突**：

> **Skill 是 Agent Platform 的统一能力协议；Static DAG 是 Skill 的确定性执行实现；
> Dynamic Graph 是 Skill 的智能组合与规划实现。统一的是 Skill Contract 和 Runtime，
> 不是具体编排引擎。**

架构形态：

```
                Agent / Planner
                       ↓
                 Skill Registry        ← 注册制 + 契约制（Agent 只见元数据，不见 Python 实现）
                       ↓
       ┌────────────────┼─────────────────┐
       ↓                ↓                 ↓
  Static DAG        Single Tool      Dynamic Agent / External
（Workflow Skill）  （Atomic Skill）   （Agent Skill / Remote）
```

**与现有代码的映射**（关键结论：Capability Registry 已是 Skill Registry 的雏形，缺口集中且可枚举）：

| Skill 架构 | agent-platform 现有代码 | 状态 |
|---|---|---|
| Skill Registry | `agent_runtime/skills/registry.py`（SkillRegistry：register/get/list/execute + 入参契约校验 + 统一超时边界） | ✅ Phase 1（已 rename，2026-08-19） |
| Skill 元数据 | `Skill`（name/description/kind/executor/timeout_ms/input_schema/output_schema） | ✅ Phase 1.5 |
| 多 Executor | `as_function_skill` / `as_agent_skill` / `as_remote_skill` / `as_dag_skill` | ✅ Phase 1 + 1.5 |
| Workflow Executor（原 Static DAG） | `as_dag_skill`（kind=WORKFLOW）包装 `graph.py` → `general_qa`；LangGraph 仅是执行实现 | ✅ Phase 1.5/3 |
| Skill Planner | `agent_runtime/planner/`（Planner ABC：plan/execute + PlannerRegistry） | ✅ Phase 2 |
| 组合治理（max_depth / cycle detection） | `PlannerRuntime.skill_guard`（per-request 隔离，2026-08-19 架构审核 P0 落地） | ✅ Phase 3 |

**落地决策（架构师建议，用户待确认）**：
1. **内部命名保持 `Capability`，对外/文档统一称 Skill**——避免全仓无意义 rename 噪音（污染 git 历史）；
   契约语义升级优先于命名升级；若后续两词并存造成认知成本，再做一次性 rename。
2. **元数据补齐（Phase 1.5，最小增量）**：`Capability` 增加可选 `input_schema` / `output_schema`
   （JSON Schema dict，供 Agent 工具描述生成与入参校验）；`version` / `risk_level` / `policy` 暂缓
   （当前单实例部署无多租户风险分级诉求，需要时再加——不过度设计）。
3. **DAG Executor = Phase 3 精确落点**：`app/agent/graph.py` **不删除**，包装为 `general_qa`
   Workflow Skill（用户明确"不会直接删掉，而会把它包装成 GeneralQASkill"）；编排权移交 Planner——
   deterministic 编排 = general_qa Skill 内部 DAG；agentic 编排 = Skill 动态组合。
4. **组合治理（Phase 3 随 AgenticPlanner 落地）**：`PlannerRuntime` 增加 `max_skill_depth` /
   `max_steps` / cycle detection；仅 agentic 组合路径需要（deterministic 静态 DAG 天然无环，不为此加复杂度）。

---

## 5. 五个契约点（落地前置，防止 Phase 2 返工）

| # | 契约 | 内容 | 归属 |
|---|---|---|---|
| **P1** | Planner 执行契约 | `plan(ctx) -> Plan`（决策）+ `execute(plan, runtime) -> AsyncIterator[StreamEvent]`（执行）。retry/超时/熔断归 Runtime，Planner 不持有 | agent-runtime |
| **P2** | ThreadState 统一状态 | `messages`（LangChain 序列化 dict）+ `metadata`（编排状态）+ `version`。app 编排字段（route/evidence 等）归 metadata | **shared-schemas（已落地）** |
| **P3** | 流式协议统一出口 | Planner 只产 `StreamEvent` 流，Runtime 决定 SSE/WS adapter（现有客户端协议不变） | agent-runtime |
| **P4** | MCP 层归属 | `MCPClientManager` 是带连接管理的 runtime 资源（归 agent-runtime/mcp），Capability 消费它 | agent-runtime |
| **P5** | 双跑 eval 基线 | 同一 golden 双跑（deterministic/agentic）各自记录基线 = 回归门禁 + Planner 解耦验证探针 | ✅ app 侧 `eval/run_planner_eval.py`（2026-08-19）+ 联邦侧 `eval/run_eval.py` `--baseline`/`--compare` 漂移门禁（2026-08-19） |

---

## 6. 路线图

| Phase | 内容 | 关键产出 | 状态 |
|---|---|---|---|
| **0** | `app/infra` → `agent-runtime`（9 个运行时模块全部迁入）；同步定 ThreadState 契约 | 共享 runtime + 统一状态 schema | ✅ **完成（2026-08-19）** |
| **1** | `capabilities/` 注册表（Function/Agent/Remote 三执行器） | 能力层中立化 | ✅ **完成（2026-08-19）** |
| **1.5** | Skill 契约升级：`Capability` 补 input/output schema（JSON Schema） | Skill = 带契约的能力单元（对外统一称 Skill） | ✅ **完成（2026-08-19）** |
| **2** | Planner 协议 + 双实现；`PLANNER` 环境变量 | 编排解耦 + 双跑 eval 基线 | ✅ 完成（2026-08-19） |
| **3** | graph.py → `general_qa` Workflow Skill（包装非删除）+ 统一 SSE/WS 出口 + 组合治理（max_skill_depth/cycle detection）+ 联邦 `run_deep_agent` 经 Planner 协议 + `PlannerRuntime` 治理驱动（双轨闭环） | 单 Runtime 成型 | ✅ **完成（2026-08-19）** |

### Phase 0 迁移单元顺序

1. ✅ `admission`（admission.py + AdmissionDecision 类型）→ `agent-runtime`
2. ✅ `coordinator`（CoordinationDecision）→ `agent-runtime`
3. ✅ `revert`（RevertResult）→ `agent-runtime`
4. ✅ `mcp_client`（McpServerConfig/McpToolResult）→ `agent-runtime`（P4）
5. ✅ `otel`/`tracing` → `agent-runtime`（可观测横向化）
6. ✅ `cache` / `circuit_breaker` → `agent-runtime`（基础中间件）
7. ✅ `db.py` 连接池 → `agent-runtime`（状态存储统一 PG 的基础，`SCHEMA_TEMPLATE` 随迁归位）

> 配置依赖倒置：`db.init_pool(database_url, db_pool_max_size)` / `db.ensure_schema(pool, vector_dim)`
> / `tracing.get_langfuse_callbacks(public_key, secret_key, host)`——agent-runtime 零依赖 app.config，
> 参数由 app lifespan / scripts 从自身 Settings 注入。`app/infra/` 现仅保留空包占位（退役标记）。

---

## 7. 执行记录

### 2026-08-19
- ✅ 方案文档建立（本文件）
- ✅ `shared-schemas/shared_schemas/thread.py`：ThreadState 契约（P2）
- ✅ `agent-runtime/` 包创建（uv workspace 注册 + pyproject）
- ✅ `admission` 首个迁移单元：`app/infra/admission.py` → `agent_runtime/admission.py`，`AdmissionDecision` → `agent_runtime/schemas.py`，app 侧 re-export 兼容
- ✅ Phase 0 完成（2026-08-19）：cache/circuit_breaker/coordinator/revert/mcp_client/otel/tracing/db 全部迁入
  `agent_runtime.*`；`app/schemas.py` 对 4 个运行时类型 re-export；调用点（app/scripts/tests 16 文件）全量改引用；
  `app/infra/` 仅剩空包占位。验证：根 tests **261 passed**（零回归，与迁移前一致），lint 0 error。

- ✅ Phase 1 完成（2026-08-19）：`agent_runtime/capabilities/` 注册表——`Capability`（name/description/kind/executor/timeout_ms）+ `CapabilityRegistry`（register/get/list/execute，统一执行入口承载超时边界）+ 三执行器工厂 `as_function_capability` / `as_agent_capability`（lazy deepagents.create_deep_agent，与联邦 `_get_local_agent` 同路径）/ `as_remote_capability`。
  - `app/capabilities.py`：装配 4 个进程内能力（search/rag/sql/mcp）为 function 型注册项，惰性单例 `get_registry()`。
  - `app/agent/graph.py` 四节点改经 `registry.execute(...)`（能力层中立化首个生产路径验证）；mcp 能力签名依赖 state+manager，注册表 kwargs 透传承载。
  - 验证：根 tests **268 passed**（261 基线 + 新增 7），新测试 `tests/test_capability_registry.py` 覆盖注册/发现/重复注册/超时/三执行器，lint 0 error。
  - 联邦侧 `as_agent_capability` / `as_remote_capability` 工厂已就绪；**main_agent.py 委派路径已在 Phase 3 联邦侧收尾切换**：`run_deep_agent` 经 `AgenticPlanner.arun` + `PlannerRuntime.skill_guard` 驱动（2026-08-19 闭环，见 Phase 3 联邦侧收尾），`deep_agent` subagents 委派机制（内部 `_build_subagents`）保持不动（零破坏 eval/WS 契约）。

- ✅ Phase 2 完成（2026-08-19）：Planner 协议 + 双实现 + `PLANNER` env + 双跑 eval 基线。
  - `agent_runtime/planner/`：契约 P1 落地——`Plan`（route/sub_query/reason/notes，notes 为扩展位）+ `StreamEvent`（type/payload，与 SSE 出口同构）+ `PlannerContext`（含 mcp_* 透传字段）+ `PlannerRuntime`（registry/llm/mcp_manager/pool 注入）+ `Planner` ABC（kind + plan/execute）+ `PlannerRegistry`（与 CapabilityRegistry 同构）。
  - `app/planners/deterministic.py`：**DeterministicPlanner**——从 graph.py 提炼决策 plan()（guard→intent→memory→router 同源复用模块级函数，防漂移）+ 编排 execute()（按 Plan.route 经 registry 调能力 + synthesize 合成 + 记忆写入，产出统一 StreamEvent 流）；`app/planners/__init__.py` 的 `get_planner()` 按 `PLANNER` env 切换实现（get_settings 为 lru_cache，切换前需 cache_clear）。
  - `agent_federation/planners/agentic.py`：**AgenticPlanner**——包装 `_execute_agent_core`（deep_agent 执行适配为 Planner 协议；plan 占位 return route="deep_agent"；execute 产 route/answer/error 事件流；异常降级 error 事件不抛出）。
  - `app/config.py` 加 `planner` 字段；`app/main.py` lifespan 挂 `app.state.planner`（Phase 3 统一 SSE 出口后供 api 消费）。
  - `eval/run_planner_eval.py`：双跑基线——deterministic 决策准确率（golden 12 条 100%）+ agentic 协议结构基线；`eval/baselines/planner_{kind}_latest.jsonl` 默认 latest 覆盖（`--stamp` 可选留痕），`--fail-below 0.8` 门禁。
  - 测试：`tests/test_planner_protocol.py`（14 用例：协议/注册表/Deterministic plan+execute/guard/mcp 透传）+ `agent_federation/tests/unit/test_agentic_planner.py`（plan 占位/execute 包装/异常降级）。
  - 验证：三套件全绿——根 **304 passed** / 联邦 **78 passed** / kefu **8 passed**，lint 0 error。
  - 环境注记：根 project 仅依赖 shared-schemas/agent-runtime，dialogue-framework/wenda-data-agent 为 workspace member 需 `make install`（`uv sync --all-packages --extra dev`）才安装；缺装会导致根套件 collection error（ModuleNotFoundError），回归前须先 `make install`。

### 4.1 补充（同轮）：
> 用户架构审核确立 **Skill 统一能力协议**（见 §4.1）：Capability Registry = Skill Registry 雏形；graph.py Phase 3 包装为 `general_qa` Workflow Skill（非删除）；Capability 内部名保持、对外统一称 Skill；Phase 1.5 补 input/output schema；组合治理（max_skill_depth/cycle detection）仅 agentic 路径落地。

### Phase 1.5 完成（2026-08-19）—— Skill 契约升级
- `agent_runtime/capabilities/registry.py`：`CapabilityKind` 增 `WORKFLOW = "workflow"`；`Capability` dataclass 增 `input_schema` / `output_schema`（JSON Schema dict，可空）；新增 `to_tool_schema()` → `{"type":"function","function":{"name","description","parameters"}}`（供 Agent 工具描述生成 + 入参契约显式化）。
- `function.py` / `agent.py` / `remote.py` 三工厂函数增 `input_schema` / `output_schema` 形参并透传。
- **新建 `capabilities/dag.py`**：`as_dag_capability(name, description, fn, *, timeout_ms, input_schema, output_schema)` → kind=WORKFLOW，把确定性 DAG 执行器封装为可注册 Skill（Static DAG Executor，对应 §4.1 的 Workflow Skill）。
- `app/capabilities.py`：定义 `_QUERY_SCHEMA` / `_RAG_SCHEMA` / `_GENERAL_QA_INPUT_SCHEMA` / `_GENERAL_QA_OUTPUT_SCHEMA`；`build_registry(graph=None)` 在注入 `graph` 时注册 `general_qa` Workflow Skill（经 `_run_general_qa` → `graph.astream` 归约 answer，graph.py **包装非删除**）；`get_registry(graph=None)` 惰性单例。
- 不做（不过度设计）：`version` / `risk_level` / `policy` 元数据暂缓（单实例无多租户分级诉求）；`to_tool_schema` 仅覆盖参数级契约，不预做工具调用服务端编排。

### Phase 3 完成（2026-08-19）—— 单 Runtime 成型
- `agent_runtime/planner/protocol.py`：新增 `SkillCompositionError(RuntimeError)`；`PlannerRuntime.__init__` 增 `max_skill_depth=4` / `max_steps=20` + `_call_stack` / `_steps` 计数；新增 `@asynccontextmanager async def skill_guard(self, name)`——执行序：步数上限 → 循环检测（相邻/跨层）→ 深度上限，仅 agentic 组合路径使用（deterministic 静态 DAG 天然无环，不为此加复杂度）。
- `app/memory/thread_persist.py`（新建）：`read_thread_messages(checkpointer, thread_id)`（aget_tuple 读 channel_values.messages）+ `append_thread(checkpointer, thread_id, question, answer)`（推进 channel_versions["messages"] + new_versions={"messages":ver} 落 blob；空 answer 或 checkpointer 缺失均 noop；thread 间隔离）。
- `app/api/routes.py`：`/query` 取 `planner` / `planner_runtime` / `checkpointer`；**Planner 主路径**——`PlannerContext(...)` → `planner.plan` → `planner.execute` → `_stream_event`（StreamEvent→SSE 映射：route/evidence/memory/status/answer/error）；graph 执行异常降级兜底；历史经 `append_thread` 写回 checkpointer。
- `app/main.py`：lifespan 装配 `registry=get_registry(graph=...)` + `app.state.planner_runtime=PlannerRuntime(...)`；启动日志增 planner kind。
- `app/config.py`：增 `max_skill_depth: int = 4` / `max_steps: int = 20`。
- 不做（不过度设计）：WS 出口统一延后（当前 app 仅 SSE，联邦 WS 适配不在本 phase 范围）；组合治理参数走 Settings 注入，不硬编码。
  → **已于 2026-08-19 收尾**：见下方「WS 出口统一收尾」。
- 验证：新增/扩展测试 25 例全绿（`tests/test_capability_registry.py` 13 例含 schema 契约 + WORKFLOW + general_qa 装配；`tests/test_planner_governance.py` 6 例含 skill_guard 三违规；`tests/test_thread_persist.py` 6 例含 append/read 往返）；**根 tests 全量回归 322 passed（零回归）**，lint 0 error。

### Phase 3 联邦侧收尾（2026-08-19）—— 双轨真正闭环
> Plan-F 核心目标「单 Runtime 多 Planner」此前 app 侧已成型，联邦 `run_deep_agent` 仍裸调 `_execute_agent_core`（未落 Planner 协议 + 组合治理）。本收尾把联邦主链路接入统一运行时，与 app `/query` 对称。

- `agent_federation/planners/agentic.py`：新增 `AgenticPlanner.arun(question, workspace_id, runtime, main_agent=None) -> str`——与 `execute`（供 app SSE 产出 StreamEvent）并存，本方法返回答案字符串、`async with runtime.skill_guard("agentic")` 包裹 `_execute_agent_core`，将 Phase 3 组合治理（max_skill_depth/max_steps）落地到联邦主链路；`main_agent` 透传保留联邦 P5 动态 agent 选择能力（不进统一协议）。
- `agent_federation/planners/__init__.py`：新增 `get_planner_runtime()` 模块级单例（联邦无 FastAPI app.state 注入先例），治理参数取 `FED_MAX_SKILL_DEPTH` / `FED_MAX_STEPS`（默认 4/20，与 `PlannerRuntime` 默认及 app/config 对齐），`registry=None`（联邦 agentic 不查能力注册表）。
- `agent_federation/agent/main_agent.py`：`run_deep_agent` 把 `singleflight(_execute_agent_core, ...)` 改为 `singleflight(AgenticPlanner().arun, ..., get_planner_runtime(), selected_agent)`——保留 singleflight 缓存击穿防护 + 全部副作用链（guard/intent/cache/memory/monitor/remember_episodic/SemanticCache），仅把「最终执行」委托给 Planner 协议 + 治理；eval/WS 的 monitor 事件契约零破坏。
- **Boundary 严守（不过度设计）**：`deep_agent` subagents 委派机制（`_build_subagents` / `create_deep_agent`）保持不动——Plan-F 目标是「编排收敛」而非「重写委派」，避免破坏现有行为；联邦仍走老委派，但被统一 Planner 协议 + `PlannerRuntime` 治理包裹。
- 验证：扩 `tests/unit/test_agentic_planner.py`（arun 经治理复用 _execute_agent_core 返回答案 + main_agent 透传 + 步数超限抛 `SkillCompositionError`）；新增 `tests/unit/test_run_deep_agent_planner.py`（run_deep_agent 经 planner.arun 走通 + monitor.report_task_result 仍上报）；联邦 unit 81 passed / 根 tests 322 passed（零回归），lint 0 error。

### R1 漂移门禁收尾（2026-08-19）—— 双跑 eval 基线闭环
> R1 风险点：联邦 `run_deep_agent` 经 Planner 协议切换后，需锁行为基线以验证「行为未漂移」。app 侧 `eval/run_planner_eval.py` 双跑基线已闭环；联邦侧补齐等价漂移门禁。

- `agent_federation/eval/run_eval.py`：新增 `--baseline <path>`（把本次结果快照为行为基线，只落可复现对比字段 `id`/`routed_agents`/`routing_score`/`rubric_rate`，不存 answer 全文避免噪声膨胀）+ `--compare <path>`（与基线逐项对比，检测 exact 退化 / jaccard 退化 / rubric 退化 / 缺失题，报告漂移率）+ `--fail-below`（漂移率超阈值则退出码非零，可作 CI 门禁）。
- 纯数据结构对比，无 LLM 依赖，CI 可守；`save_baseline` / `compare_baseline` 抽为独立纯函数复用。
- **用法**：先 `--baseline eval/baselines/fed_latest.jsonl` 锁切换后基线 → 后续改动 `--compare eval/baselines/fed_latest.jsonl --fail-below 0.05` 守门禁。
- 不做（不过度设计）：不引入新 golden schema、不改动 judge 逻辑、不做跨 run 的 LLM 语义相似度比对（路由决策层已足够定位漂移）。
- 验证：新增 `tests/unit/test_eval_baseline.py`（4 例覆盖 baseline 快照剥离 + exact/jaccard/rubric 退化 + 缺失题 + clean 无漂移）；联邦 unit 85 passed / 根 tests 322 passed（零回归），lint 0 error。

### WS 出口统一收尾（2026-08-19）—— 双轨流式事件同构

> 原 Phase 3「统一 SSE/WS 出口」仅落 app 侧 SSE；联邦 `/ws/{thread_id}` 仍是 echo/pong 桩，未接 deep_agent 事件流。本收尾把联邦 WS 也接入统一 `StreamEvent` 出口，使 app(SSE) / 联邦(WS) 双轨事件 schema 同源（传输层各异，事件语义统一）。

- `agent_runtime/planner/protocol.py`：新增 `serialize_stream_event(event: StreamEvent) -> dict | None`，作为 **app / 联邦共享的单一映射**（route/evidence/memory/status/answer/error 扁平化输出），消除双轨出口 schema 漂移源。
- `app/api/routes.py`：`_stream_event` 改为委托 `serialize_stream_event`（输出结构不变，消除 app 内硬编码映射副本），app SSE 出口仍经此函数。
- `agent_federation/api/server.py`：`/ws/{thread_id}` 从 echo/pong 升级为——收 `{"type":"query","text":...}` → `AgenticPlanner.execute(plan, runtime)` 产 `StreamEvent` → 逐条 `send_json(serialize_stream_event(event))` → 收尾 `{"type":"done","thread_id","answer"}`；非 query 合法 JSON 仍回退 pong（保留旧 echo 兼容）。`/api/task` 现状不动。
- **Boundary（不过度设计）**：仅统一「事件 schema 出口」，不重写联邦 WS 鉴权/并发/前端协议；`AgenticPlanner.execute` 当前产出 route/answer/error（`_execute_agent_core` 内部 monitor 事件未桥接为 StreamEvent），evidence/memory 桥接留作后续（非本次范围）。
- 验证：新增 `tests/unit/test_ws_stream.py`（2 例：query 流式收 route+answer+done；非 query 回退 pong，mock `AgenticPlanner.execute` 免 LLM）；联邦 unit 87 passed / 根 tests 322 passed（零回归），lint 0 error。

### 架构审核落地（2026-08-19 晚）—— Planner/Skill/Runtime 收口 + 演进方向

> 用户基于 v2 做架构级审核：核心结论「LangGraph/DeepAgents 应降级为执行实现；**Skill = 能力统一抽象，Planner = 决策/组合层，Runtime = 执行治理层**」。审核论断逐条代码核实全部属实，按「不过度设计—最小必要优先」落地分级：

**本轮已落地（P0 真实风险 + P1 轻量）**
1. **PlannerRuntime per-request 隔离（P0）**：`protocol.py` 的 `_steps`/`_call_stack` 由实例 mutable state 改为 `contextvars.ContextVar`——异 session 并发互不干扰、同 session 串行（同 task 链）共享预算。修复单例注入下「一次执行的预算被并发请求耗尽」的跨请求污染。`max_steps`/`max_skill_depth` 保持不可变配置。**配套测试语义修正**：`test_planner_governance.py`/`test_agentic_planner.py` 原「跨多次 arun 累计步数」断言即 bug 行为，改为「单次执行内嵌套超限 + 执行结束预算复位」。
2. **SessionCoordinator 语义明确（P0）**：`coordinator.py` docstring 明确 **process-local 单实例**语义（`_active/_queues/_conditions` 均为 asyncio 进程内状态），多副本下「同 session 串行」不成立；标注演进方向（Postgres/Redis 分布式 lease 或 durable execution 持有 ownership），本期不做。
3. **Skill 入参契约真正执行（P1）**：`registry.py` 新增 `SkillExecutionError` + `_validate_input()`——`execute()` 入口校验 `required` 存在性 + `properties` 类型，缺 schema 向后兼容（不拒绝注册方注入参数如 mcp 的 state/mcp_manager）。Agent 组合 Skill 传错参数得到明确契约错误而非内部 Python exception。
4. **术语精确化（P2 轻量）**：`SkillKind.WORKFLOW` 注释与本文档统一「Static DAG → Workflow（Static/Conditional）」，LangGraph 明确为执行实现。

**演进方向（文档化，暂缓重构）**——按「边界出现再拆」原则留档：
- **SkillRegistry / SkillRuntime 分离**：当前 execute 仅 timeout + 契约校验两个边界，拆两层为时尚早；待 retry/circuit 等第二边界真实出现时，按「Registry=Discover / Runtime=Execute」拆分。
- **Dynamic Agent 纳入 Skill 体系**：`AgenticPlanner` 仍直调 `_execute_agent_core`（旁路）。收敛为 `SkillKind.AGENT` 是完整架构收口，但 `_execute_agent_core` 挂着 guard/intent/cache/memory/monitor 副作用链，包装须保行为，作独立阶段。
- **`Plan.notes` → `ExecutionContext`**：notes 承载 question/workspace_id/user_id 已近隐形上下文；演进为独立 `ExecutionContext`（request_id/thread_id/messages/budget/deadline/trace_id），Plan 仅存 route/steps/reason。
- **Workflow Definition → Workflow Skill 编译**：支持 YAML/声明式 Workflow（`steps: [search, rag, summarize]`）编译为 WorkflowSkill 注册进 Registry，LangGraph 仅是其中一种执行后端。

**验证**：root tests 180 passed（含 governance 7 + capability registry 16 契约测试）/ 联邦 unit 89 passed（零回归），ruff 0 error。未提交（待与真实 R1 基线一起）。
