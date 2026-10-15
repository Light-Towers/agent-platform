# Agno AgentOS × agent-platform 产品对比分析

> **定位**：本文覆盖"平台/运行时产品"层的最直接竞品对比，与两份姊妹文档互补不重复——
> - 《runtime-self-build-analysis.md》（2026-08-22）：**框架层**对比（LangGraph/CrewAI/AutoGen/各家 SDK + 云原生托管）
> - 《opensource-runtime-counterparts.md》：**内核/原语层**对比（LightAgent/agent-os/agent-stack）
> - 本文：**平台层**对比（Agno AgentOS，与本项目"Supervisor + 治理主链路"定位重合度最高的开源竞品）
>
> 成文时间：2026-10-15。数据核验：Agno 侧 GitHub API 2026-10-15 直拉 + 官方文档/定价页 2026-10-14/15 访问；本地侧代码库实证 2026-10-14/15（git ls-files / grep 类级取证 / 配置文件直读）。

---

## 0. 结论先行（TL;DR）

1. **Agno AgentOS 是与本项目定位重合度最高的开源竞品**（42,725★，Apache 2.0），没有之一。
2. **一句话对比**：Agno 把"生产化"（会话/追踪/调度/审批/界面）做成**开箱即用的通用产品**；本项目把"治理"（准入/调度/取证/成本）做成**可接线的主链路模块**。
3. **治理四维度我方赢 3.5 个**（任务级准入、优先级调度、取证链、预算封顶）；**产品化/社区/成熟度 Agno 大幅领先**（star、发布节奏、HITL 成熟度、控制平面）。
4. **两个经复核固化的关键判断**：
   - Agno **无 token 预算封顶**——官方文章手把手教用户自己包 `TokenBudgetAgent`，v3.0 changelog 全文无任何 budget 功能，第三方明言"封顶是用户工程团队的职责"。这是可引用一手来源的差异化。
   - Agno 的 durable execution **同样默认关**（v3 changelog 原文 "Durability defaults to off"）——"治理开关默认关"是双方共性的渐进启用姿态，不是我方独家污点；但"治理平台不默认治理自己"的张力仍在。
5. **行动项**（详见 §8）：P0 = 5 个未接线模块接线 + HA 验收；P1 = 治理开关默认开 + 抄 Agno 产品化三件套。

---

## 1. 对比框架：为什么是 Agno

### 1.1 赛道分层与本项目位置

| 层 | 代表项目 | 占领状态 | 与本项目关系 |
|---|---|---|---|
| 应用搭建层 | Dify 158K★ / n8n 207K★ / Coze 开源 | 已占领 | 不同层，低竞争 |
| 框架层 | LangGraph 43K★ / CrewAI 60K★ / 各家 SDK | 已占领（"框架战争"收官） | 不同层，低竞争 |
| **运行时 + 治理层** | **Agno AgentOS 42.7K★** / OpenHands Enterprise（商业）/ LangSmith Deployment（商业） | **半占领**：开源无成熟占领者，治理能力锁商业版 | **正面竞争** |

### 1.2 定位论证：Agent 治理 = 数据治理 + 微服务治理的下一站

- **数据治理类比**：大数据从野蛮生长（ETL 黑盒）到事故倒逼（口径打架/PII 泄露）再到治理平台化（元数据/血缘/质量/成本分摊成为中台标配），用了 5-8 年；Agent 爆发后同一条曲线正在压缩重演（Gartner 预测 2027 年末 40% agentic 项目因成本/风控被取消）。
- **微服务治理类比**：治理三阶段 = 框架内嵌（Spring Cloud）→ sidecar（Service Mesh）→ 平台化（K8s/OPA）；核心规律是**治理从"应用层自觉"下沉到"基础设施层强制"**。Agent 治理正在复刻：prompt 护栏（自觉）→ 运行时层强制（Agno AgentOS 即"Agent 的 Service Mesh 化"尝试）→ 平台化治理。
- **本项目 = Agent 的 Service Mesh / K8s 治理层位置**；Agno 也在抢这个位置，故为正面竞品。

---

## 2. Agno AgentOS 架构本质（经一手核验）

| 项 | 事实 | 来源与核验 |
|---|---|---|
| 架构 | 三层：SDK（Agent/Team/Workflow 原语）→ **AgentOS 运行时（无状态 FastAPI 应用）** → Control Plane（浏览器 UI）；数据全部留在用户自有库 | 官方文档（2026-10-14） |
| 项目年龄 | 仓库创建于 **2022-05-04**（前身 Phidata，后品牌改名 Agno）——4 年老项目，非 2025 新秀 | GitHub API（2026-10-15 拉取）；改名沿革见第三方定价页 |
| 社区规模 | **42,725★ / 6,133 forks / 6,195 commits** / Apache-2.0 / 最近 push 2026-10-14 | GitHub API 直拉；commits 数经 Link header last-page 法核实 |
| 发布节奏 | 当前最新 **v3.1.3（2026-10-12）**；v3.0.0（2026-08-24）为大版本起点，其后两个月 **12+ 个 release** | releases API（2026-10-15） |
| 部署形态 | 单容器 FastAPI + 数据库（生产推荐 Postgres）；Docker/AWS/GCP/Helm 模板 | 官方文档 + README 模板清单 |
| 多框架 | 适配器把外部 agent 包装为 AgentProtocol：**运行时表面共享（路由/流式/会话），编排语义不共享**（委派/知识/hooks/guardrails 对外部框架不可用，外部 agent 不能成为 Team 成员） | 官方 Multi-Framework 文档 |
| 端点口径 | 官方文档 50+ vs 营销页 80+，**两处不一致**（引用时需注明口径） | 官方文档 + 产品页 |

---

## 3. 治理四维度对比（核心表）

本地侧均为代码库实证（文件 / 行数 / 类名）；Agno 侧为公开信息核对，**否定性断言一律标注"公开文档未见"**。

### 3.1 Admission 准入

| | agent-platform（本地实证） | Agno AgentOS（公开信息） |
|---|---|---|
| 实现 | `admission.py`（269 行）+ `admission_gateway.py`（301 行）：`RateLimiter` / `AdmissionQueue` / `AdmissionController`(Protocol) / `InMemoryAdmissionController` / `PgAdmissionController` / `run_admitted()` 统一入口 / `AdmissionRejected` | JWT RBAC（端点级 scope、角色=scope 包）、服务账号、PublicSurface 匿名边界 + 配额、guardrails（PII/注入/审核）、HITL 审批 |
| 判断 | **任务级准入策略引擎**（谁能提交什么任务/用什么模型/工具的策略强制） | 有身份与边界，**公开文档未见任务级准入策略引擎** |

### 3.2 Scheduler 调度

| | agent-platform | Agno AgentOS |
|---|---|---|
| 实现 | `execution_scheduler.py`（699 行）：`ExecutionPriority` 优先级队列 / `QueueStatus` / `QueueFull` / `SchedulerStore`(ABC) / `InMemorySchedulerStore` / `PgSchedulerStore` / `SchedulerReaper` 租约回收 + `execution_recovery.py` `Rescheduler` | cron 调度器（DB 租约、轮询、重试、超时、运行历史）+ v3.0 持久化后台队列（有界并发**默认 32**、取消、幂等去重、任意副本接管；**durability 默认关**） |
| 判断 | **优先级队列 + 租户级并发配额**（公开信息 Agno 未见） | 有计划任务与持久化执行，**无优先级/租户级调度治理**（公开信息未见） |

### 3.3 Forensic 取证

| | agent-platform | Agno AgentOS |
|---|---|---|
| 实现 | `forensic.py`（181 行）：`ForensicContext` / `StepForensic` / `divergence_diagnosis()` 版本指纹对比；`trajectory/`：`TrajectoryRecord` / `replay_trajectory` 轨迹重放 / `ReplayDivergence` 分歧检测 / `PgTrajectoryStore`；另有 OTel tracing（三态降级） | span 级 trace（模型调用/token/工具/时长/错误，存自有库，需显式 `tracing=True`）+ 审批记录（resolved_by/resolved_at）；**终端用户审计日志在 Enterprise 版** |
| 判断 | **轨迹重放 + 版本指纹对比**（公开信息 Agno 未见）；指纹链 + OTel 双轨 | 有痕迹、无完整性担保（公开信息未见不可篡改审计存储与版本指纹对比） |

### 3.4 CostGov 成本治理

| | agent-platform | Agno AgentOS |
|---|---|---|
| 实现 | `cost_governance.py`（224 行）+ `cost_governance_pg.py`（60 行）：`BudgetDimension` / `BudgetLimit` / `BudgetUsage` / `BudgetExceeded` / `BudgetStore`(ABC) / `PgBudgetStore` / `CostGovernance`——**预算维度 + 限额 + 超限异常 + PG 持久化**（⚠️ 默认关，见 §7.4） | token 归因有（trace/metrics 用量与模型分布）、限流有（PublicSurface 速率/体积/时长/并发上限）；**预算封顶无** |
| 判断 | **设计深度胜**（但默认关 = 实际未启用） | 归因强、封顶缺失——**三重佐证**：① 官方文章《Handling context window limits》教用户自行包装 `TokenBudgetAgent`；② v3.0 changelog 全文无任何 budget/cap 内容；③ 第三方评测明言 "Agno does nothing to cap your token spend — that discipline remains your engineering team's job"（2026-07-04） |

### 3.5 四维度小结

| 维度 | 胜方 | 差距性质 |
|---|---|---|
| Admission | **agent-platform** | Agno 有成熟 RBAC/HITL，缺任务级策略引擎 |
| Scheduler | **agent-platform**（深度）/ Agno（产品化） | 我方有优先级/租户配额；Agno 持久化队列已产品化 |
| Forensic | **agent-platform** | Agno 有产品化 trace，缺重放/指纹/完整性担保 |
| CostGov | **agent-platform**（设计） | Agno 归因产品化，封顶明确缺失 |

---

## 4. 其他关键面对比

### 4.1 多 Planner / 架构哲学

| | agent-platform | Agno |
|---|---|---|
| 规划策略 | **Plan-F：Planner 可插拔**（`planner/registry.py` 注册 + `execution_graph.py` 图执行 + `mode_selector.py` 模式选择 + `durability.py` checkpoint/幂等/执行所有权） | SDK 层三种编排原语（自主循环 / Team 委派 / Workflow 确定性步骤流）；**公开文档未见可插拔规划策略接口** |
| 跨框架 | 统一 Runtime，框架降级为执行实现 | 适配器共享运行时表面，**编排语义不共享**（外部 agent 不能成为 Team 成员） |

### 4.2 多租户与安全

| | agent-platform | Agno |
|---|---|---|
| 隔离机制 | **服务端断言租户**（ADR-0007：RS256 JWT → 网关验签 → X-Internal-Tenant HMAC → 子服务只信签名头）；`identity.py`（322 行）+ `identity_middleware.py`（170 行）+ `workspace_registry.py`（197 行，`assert_workspace_access`） | **user_id 行隔离**（JWT `sub` 键，`user_isolation=True` 后非管理员只见自己的行；v3.0 扩展至 metrics/schedules/evals/knowledge/**多个向量库**（官方未给精确数）） |
| SQL 层 | `sqlglot` 白名单守卫（单条 SELECT、禁 DML/DDL 含子查询、强制 LIMIT） | —（公开信息未见同类） |
| 判断 | 我方隔离机制更硬（内部签名信任链）；Agno 覆盖面广但为用户级而非租户级 | |

### 4.3 HITL 与韧性

| | agent-platform | Agno |
|---|---|---|
| HITL | `human_task.py`（284 行，`HumanTask`/`HumanTaskStore`/`HumanTaskResolver`）——**⚠️ 应用层零调用（未接线）** | Approvals（阻塞/audit 两种，已产品化；v3.0 统一为 `HumanReview` 原语）——**Agno 胜** |
| 韧性 | `execution_recovery.py`（268 行 Reaper/RecoveryManager/Rescheduler）+ `planner/durability.py`（checkpoint/幂等/执行所有权/`reap_stale_executions`）+ `coordinator.py` PG advisory lock 租约 | durable execution（v3.0 DB 持久化队列、接受即落库、任意副本接管；**默认关**） |
| 中间件 | `skills/middleware.py`：熔断/守卫/压缩/重试/限流/审计/Sidecar 式洋葱链；`effect_contract.py`（203 行）：投递语义/幂等策略/失败恢复决策 | —（公开信息未见同类显式效应合约） |

---

## 5. 成熟度与生态对比

| 维度 | agent-platform | Agno AgentOS | 差距 |
|---|---|---|---|
| 代码规模 | 807 .py / 8.7 万行；651 commits / 63 天 / 3 作者（主账号 519 / osmondy 126 / dependabot 6） | 6,195 commits / 4 年 / 42,725★ / 6,133 forks | Agno 量级领先 |
| 发布节奏 | 63 天 651 commits（密度高但为内部迭代） | **按天 changelog、周级小版本、两个月 12+ release** | Agno 领先 |
| 产品化 | 无控制平面 UI、无模板市场 | 三层架构 + 控制平面 UI + Studio 无代码 + 模板 + Demo OS | **Agno 大幅领先** |
| 测试/门禁 | 288 测试文件 ~2,500 用例；golden **342 条**（301 jsonl + 41 exhibition json）+ RAGAS/bootstrap 回归门禁；CI 4 workflow + 1,020 行架构 lint | 有 evals；公开信息未见同等级回归门禁描述 | 我方工程纪律胜 |
| 生产验证 | **真实内网 k8s 部署证据**（rev 门禁构建分发、HA compose、OTel 接线、多份 operations evidence 存档） | 官网自述 Fortune 5 客户、月下载 2M+、SOC 2（**规模未经独立核实**；第三方指出 SOC 2 徽章未附报告/审计方/日期） | 我方有可复核证据，Agno 为自述 |
| 生态 | 6 个内部应用工程 | 100+ 工具包 / 30+ 模型提供商 / 20+ 向量库 / MCP + A2A / 聊天平台接口 / cookbook | **Agno 大幅领先** |
| 文档 | AGENTS/ARCHITECTURE/README + 80 篇 plans | 客户工程 VP 公开称 "some of the best documentation I've ever seen" | Agno 领先 |

---

## 6. 双方强弱清单（双向诚实）

**Agno 明显强于本项目**：产品化（控制平面/模板/下午搭出平台）；发布节奏与社区（42.7K★、按天 changelog、点名 Fortune 级客户）；跨框架互操作与接口生态；无状态 + DB 持久化的水平扩展设计；HITL 产品化成熟度。

**本项目可能强于 Agno**（基于公开信息推断 + 本地实证）：治理深度（任务级准入、租户级预算封顶、轨迹重放 + 版本指纹对比）；租户隔离强度（服务端断言信任链 + SQL 白名单）；评测门禁（342 golden + 回归门禁）；可复核的生产验证证据（内网 k8s vs 官网自述）；**无商业锁定**（Agno 关键治理能力——自定义 RBAC/审计日志/SSO——集中于 Enterprise：Pro $150/月仅 1 live 连接 + 3 席，加座 $30/席、加连接 $95/连接）。

**竞争窗口判断**：Agno v3.x 正快速向治理深水区游（持久化队列、隔离扩展、HITL 统一），且治理增强项被商业版收割——说明它认定治理是付费点，方向反向验证我方定位；但开源治理层仍无成熟占领者，窗口约 12-18 个月。

---

## 7. 复核记录（口径与修正，2026-10-15）

本文所有关键数字均经二手核验，以下为复核过程与修正：

1. **golden 总数修正：329 → 342**。初稿漏计 `eval/dialogue_framework_golden.jsonl`（8 条）与 `eval/wenda_data_agent_golden.jsonl`（5 条）。现行口径：301 条 jsonl（agent_server 15 + federation 200 + knowledge-service 73 + dialogue_framework 8 + wenda_data_agent 5）+ exhibition 41 条 json = **342**（41 沿用此前审计口径，未逐条复核，标注存疑）。
2. **Agno 版本口径修正**：非"v3.0.0 已 GA"，当前最新 release 为 **v3.1.3（2026-10-12）**；v3.0.0 仅为大版本起点。
3. **Agno 项目年龄修正**：仓库创建于 2022-05-04（前身 Phidata），非新秀项目。
4. **"治理开关默认关"定性修正**：Agno durable execution 同样默认关（v3 changelog 原文 "Durability defaults to off"，`QueueConfig(durable=True)` opt-in）——由"我方独家自伤"降级为"双方共性的渐进启用"；但治理平台自我治理的张力仍在（见 §8 行动项）。
5. **核验方法留档**：Agno 侧 GitHub API 直拉（stars/forks/releases）；commits 数经 `per_page=1` Link header last-page 法核实；本地侧 `git log --format='%an'`（绕过 shortlog 故障）、grep 类级取证、配置文件直读（`config.py:148` `scheduler_enabled: bool = False`、`config.py:155` `cost_governance_enabled: bool = False`）、5 个未接线模块经 `grep applications/` 全目录确认零引用（skill_router 仅 `foundation/__init__.py` 文档字符串提及、无 import）。
6. **本地规模自洽校验**：651 commits = 519 + 126 + 6（作者提交数与总数吻合）。

---

## 8. 对我方启示与行动项

| 优先级 | 动作 | 补什么 |
|---|---|---|
| **P0** | 5 个未接线模块接线（human_task / execution_recovery / state_migration / payload_externalization / skill_router） | 把"有实现"变成"在主链路上"——治理版图缺的整块（HITL/恢复/迁移/外置/路由） |
| **P0** | HA 双实例物理故障转移验收 | "生产级"三个字的兑现凭证 |
| **P1** | `scheduler_enabled` / `cost_governance_enabled` 默认开（或至少 scheduler） | 消除"治理平台不默认治理自己"的叙事张力（注意：Agno 同样默认关，此项是自我要求非竞争必需） |
| **P1** | 抄 Agno 产品化三件套：控制平面视图、模板、发布节奏 | 治理深度之外补"可上手"；文档质量按客户级标准 |
| **P2** | 评估 `agent-stack` 的 `AgentBudget`（token + dollar 双硬上限）设计 | 与 `cost_governance.py` 对齐：从"记账+限额"到"前置硬闸门"（见《opensource-runtime-counterparts.md》§5「对本项目的可借鉴建议」第 1 条） |

**面试/叙事一句话**："对比 Agno AgentOS，他们把生产化做成通用产品、官方文档教用户自己包 token 预算；我们把治理做进运行时——任务级准入、租户级预算封顶、轨迹重放取证，且已在真实 k8s 环境验证。治理深度和生产验证是我们的护城河，产品化是必须补的课。"

---

## 9. 来源列表（均经 2026-10-14/15 访问核验）

**Agno 官方**
- [What is AgentOS? - Agno Docs](https://docs.agno.com/agent-os/introduction) — 架构定义、50+ 端点口径、JWT RBAC、多框架
- [Agno v3.0 Changelog](https://docs.agno.com/other/v3-changelog) — durable execution 默认关、user_id 隔离扩展、HumanReview 统一、scheduler 变更（**全文无 budget 功能**）
- [Scheduling - Agno Docs](https://docs.agno.com/runtime/scheduling) — cron + DB 租约调度
- [Per-User Data Isolation - Agno Docs](https://docs.agno.com/agent-os/security/authorization/user-isolation) — user_id 行隔离、admin scope
- [Approvals - Agno Docs](https://docs.agno.com/agent-os/approvals/overview) — 阻塞/audit 两种审批
- [Multi-Framework Support - Agno Docs](https://docs.agno.com/agent-os/multi-framework/overview) — 适配器能力边界
- [Public Surface - Agno Docs](https://docs.agno.com/agent-os/public-surface) — 匿名边界 + 速率/体积/时长/并发上限
- [Agno Pricing](https://www.agno.com/pricing) — Free / Pro $150 月 / Enterprise 治理边界
- [agno.com 首页](https://agno.com/) — "41K stars / 2M+ per month / Fortune 5 customers / SOC 2"（官网自述）
- [Handling context window limits in Agno（官方文章）](https://www.agno.com/articles/handling-context-window-limits-in-agno-token-tracking-preventing-overflow) — **官方教用户自行包装 TokenBudgetAgent**（预算为用户职责的佐证）
- [Toolkit Index](https://docs.agno.com/tools/toolkits/overview) / [Model Providers](https://docs.agno.com/models/providers/model-index) / [Vector Store Index](https://docs.agno.com/knowledge/vector-stores) — 100+/30+/20+ 生态口径

**GitHub API（2026-10-15 直拉）**
- [agno-agi/agno](https://api.github.com/repos/agno-agi/agno) — 42,725★ / 6,133 forks / Apache-2.0 / created 2022-05-04 / pushed 2026-10-14
- releases API — v3.1.3（2026-10-12）当前最新；v3.0.0（2026-08-24）

**第三方**
- [AI Agent Square - Agno Review 2026](https://aiagentsquare.com/agents/agno)（2026-07-04）— "Agno does nothing to cap your token spend"
- [Modern DataTools - Agno Pricing](https://www.modern-datatools.com/tools/agno/pricing)（2026-09-17 验证）— 定价细节与 Phidata→Agno 沿革
- [quidproquo - Agno 3.0.0 动态](https://quidproquo.cc/posts/daily/2026-08-25-framework-agno-300-en)（2026-08-25）— 破坏性变更与迁移要求
- [Key Data 客户故事](https://www.agno.com/customer-stories/key-data) — Darren Haligas（VP of Engineering）文档评价原文

**本项目侧（代码库实证，2026-10-14/15）**
- `packages/agent-runtime/agent_runtime/`：admission.py / admission_gateway.py / execution_scheduler.py / cost_governance.py / cost_governance_pg.py / forensic.py / trajectory/ / execution_recovery.py / human_task.py / identity.py / workspace_registry.py / planner/ / skills/middleware.py / effect_contract.py / coordinator.py
- `applications/agent_server/config.py` L148/L155；`docs/adr/0007-server-asserted-tenant-identity.md`
- git 历史与 golden 清点（§7 方法留档）

---

## 10. 局限性声明

1. **否定性断言口径**："Agno 无 X"均为"公开文档/ changelog 未见"级核查，不排除未公开文档或我未检索到的能力；引用时应保留该口径。
2. **Agno 生产规模**（Fortune 5 客户、月下载 2M+、SOC 2）为官网自述，未经独立核实；第三方已指出 SOC 2 徽章缺报告/审计方/日期。
3. **本地侧 41 条 exhibition golden** 沿用 2026-10-14 审计口径，本轮未逐条复核。
4. **star/forks 为时点快照**（2026-10-14/15），社区数据随时变动。
5. 本文为内部竞争定位分析，非公开评测；对外引用需自行复核一手来源时效。
