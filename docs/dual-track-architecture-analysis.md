# 双轨架构问题记录：LangGraph 与 DeepAgents 并存

> 状态：问题登记（基于 `docs/plan-e-dual-track-convergence.md` 与两轨源码调研）
> 调研日期：2026-08-16
> 关联：架构边界 `docs/architecture-boundary-app-vs-deepagents.md`、收敛规划 `docs/plan-e-dual-track-convergence.md`
> 说明：本文聚焦"双轨并存暴露的架构问题"，不重复收敛方案（见 `plan-e-dual-track-convergence.md`）。技术债登记见 `architecture-improvement-plan.md` §6（TB-9 ~ TB-13）。

## 0. 背景

`agent-platform` 同时存在两套 Agent 编排架构：

- **轨道 A `app/`**：自研 LangGraph `StateGraph` Supervisor（`app/agent/graph.py:154` `build_graph()`）。
- **轨道 B `deepagents/`**：`deepagents.create_deep_agent(subagents=[...])` 联邦网关（`deepagents/agent/main_agent.py:128`），其 checkpointer 仍是 LangGraph 的 `InMemorySaver`（`main_agent.py:37`）——即 **DeepAgents 包是 LangGraph 之上的封装**，而非替代。

两轨**零代码耦合**（互不包含 import，边界文档 §2 已确认），部署独立（各自 `docker-compose.yml`）。本文记录这种并存关系下**已暴露但尚未全部收敛的架构问题**。

## 1. 问题清单

### AR-1 职责重叠：同一能力两套实现（高优先级）

**现象**：两轨都实现「意图路由 + RAG + SQL + 搜索 + 合成」全链路。

- `app`：`decide_route()`（`app/agent/router.py`）+ `rag_query`/`sql_query`/`search_web` 进程内节点。
- `deepagents`：`agent/intent/classifier.py` + `agent/intent/llm_judge.py` + `agent/rewrite/rewrite_node.py`（L1/L2 意图 + 改写），以及 `database_query_agent`/`network_search_agent`/`knowledge_base_agent` 子 Agent。

**影响**：路由/改写逻辑演化需双份维护；两套意图分类策略可能给出不同结论，行为不一致且难定位。

**趋势**：收敛规划 E-1/E-2 已部分收口（契约断言、SQL 守卫委托内核），但**意图分类与 Query 改写仍是双份**，未对齐到单一真相源。

**建议**：以 `app` 的 `decide_route` + `agent_core` 为路由真相源，deepagents 侧复用或经 kernel 桥接；或明确「deepagents 不自带意图分类、委派前由网关层统一」。

### AR-2 状态管理冲突：记忆语义不等价（高优先级）

**现象**：

- `app`：`app/memory/longterm.py` 的 pgvector 长期语义记忆（`recall`/`remember`），并有 `app/main.py` 的 `AsyncPostgresSaver` checkpoint + `app/infra/revert.py` 会话回退。
- `deepagents`：仅 `InMemorySaver`/`AsyncSqliteSaver`（`main_agent.py:37-43`），**无 pgvector 长期记忆**（收敛规划 §1 已登记）。

**影响**：同一用户跨两轨无法共享长期上下文；deepagents 重启/多实例下会话状态丢失，而 `app` 可回放。两套"会话记忆"语义不等价，是隐性一致性缺陷。

**趋势**：E-3 已将 `MemoryBackend` Protocol 下沉 `agent_core.memory/backend.py`（仅协议），但 **deepagents 侧尚未挂载 pgvector 后端**，仅协议就位、实现缺位。

**建议**：deepagents `create_deep_agent` 的 memory 挂载点接入内核 `MemoryBackend`，使双轨记忆后端可插拔、语义一致；短期至少在文档固化"deepagents 无长期记忆"的边界声明。

### AR-3 配置体系分裂：双套配置范式（中优先级）

**现象**：

- `app`：`app/config.py` 用 pydantic-settings `Settings` 单一配置对象。
- `deepagents`：`deepagents/agent/config.py` 用 dataclass + dotenv，外加 `prompt/prompts.yml` YAML；能力开关（GUARD/PLANNER/REFLEXION/INTENT/CACHE/AGENT_MODE）散落 env（`main_agent.py:73-214`）。

**影响**：新人需同时理解两套配置范式与两套开关语义；env 变量命名空间可能碰撞，排查成本翻倍。

**建议**：长期将 deepagents 配置也收敛到 pydantic-settings 或复用 `app` 的 `Settings`；短期至少在 README 用一张表枚举 deepagents 全部 env 开关与默认值。

### AR-4 共享内核采用度不对称（中优先级，部分已收敛）

**现象**（边界文档 §4）：

- `deepagents` 引用 `agent_core` 24 处、`app` 仅 7 处；
- `shared-schemas` 原仅 `app` 直接 import，`deepagents` 仅经下游子服务间接消费（E-1/P4.1 已补断言，已闭环）；
- `agent_core.cache` 的 `CacheStats`/`build_cache_key` 双轨复用（TB-4 已落地），但 `PgSemanticCache`(app) 与 `ValkeySemanticCache`(deepagents) 尚未统一到 `BaseSemanticCache` 接口实现层。

**影响**："共享内核"这一收敛支点本身是歪的——核心能力（缓存、记忆、SQL 守卫）的采用深度不一致，导致双轨行为对内核升级的敏感度不同。

**建议**：以 `agent_core` 为唯一真相源逐项对齐（缓存 key 构造、记忆后端、SQL 守卫）；新增内核能力时强制双轨同步接入，避免再次分化。

### AR-5 团队认知负担与维护成本（中优先级，结构性）

**现象**：

- 9 个 `pyproject.toml` monorepo + 两套编排哲学（StateGraph 的「边思维」vs DeepAgents 的「委派思维」）+ 两套网关（SSE vs WebSocket）。
- `deepagents` 的 middleware 全开关驱动（`main_agent.py:63-114`）虽便于实验，但也意味着能力是否生效依赖运行时 env，文档与代码易漂移。

**影响**：新人要同时建立两套心智模型；排障时需先判断"请求走的是哪条轨"，再定位对应范式，平均定位成本显著上升。

**建议**：固化边界文档（已做），并在 `AGENTS.md`/`README.md` 显式给出「新业务默认走哪条轨」的决策树，降低认知切换。

### AR-6 编排层收敛的禁区风险（低优先级，护栏性质）

**现象**：社区或团队可能提出"抽 `app` 节点为 `deepagents` subagent"或反向图重写以"统一架构"。

**影响**：会同时破坏 `app` 的合规外壳（admission/coordinator/revert/PG checkpoint/sqlglot 双保险/SSE）与 `deepagents` 的联邦远程治理（429/探活）——收敛规划 §3 已列为硬约束。

**建议**：任何编排层合并提案一律驳回（见收敛规划 S-4）；双轨收敛严格限定在**共享内核/契约层**。

## 2. 问题 → 技术债映射

| 问题 | 技术债编号 | 收敛状态 |
|---|---|---|
| AR-1 职责重叠（意图/改写双份） | TB-9 | 待排期（仅 SQL/契约已收口） |
| AR-2 状态/记忆冲突 | TB-10 | 协议就位（E-3），deepagents 实现缺位 |
| AR-3 配置体系分裂 | TB-11 | 待排期 |
| AR-4 内核采用度不对称 | TB-12 | 部分已闭环（E-1/TB-4/TB-5） |
| AR-5 认知/维护成本 | TB-13 | 结构性，靠文档固化缓解 |
| AR-6 编排合并禁区 | — | 护栏（收敛规划 §3/S-4），不登记为债 |

## 3. 一句话结论

双轨并存本身合理（迁移验证、模块隔离、实验对比），但其**职责重叠、记忆语义不等价、配置分裂、内核采用不对称**是真实且未完全收敛的架构债。收敛的正确边界已在 `plan-e-dual-track-convergence.md` 明确：**只在共享内核/契约层补齐，绝不在编排层合并代码**。本文登记的问题即为该边界内仍需补齐的剩余项。

---

*生成依据：`app/agent/graph.py`、`deepagents/agent/main_agent.py`、`docs/architecture-boundary-app-vs-deepagents.md`、`docs/plan-e-dual-track-convergence.md` 双轨调研；问题编号 AR-1~AR-6，技术债编号 TB-9~TB-13。*
