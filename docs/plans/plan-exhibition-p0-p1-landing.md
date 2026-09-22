# Plan：会展 Agent 平台 P0 Foundation + P1 只读 Agent 落地（agent-platform 侧）

> **状态**：Draft v2 / 待评审（v2：基于两项目清晰边界重写）
> **定位**：把《会展行业 AI Agent 平台》v0.9 的 §22-§25 执行计划（P0/P1 批次）映射到 `agent-platform` 仓库的具体执行项
> **触发**：用户要求基于愿景文档制作下一可执行批次落地规划
> **依据**：`mingyang-warehouse/docs/会展行业 AI Agent 平台.md` v0.9 §2.2 / §8 / §17 / §18 / §22-§25
> **输入契约**：F01-F06（`docs/superpowers/specs/2026-09-08-F0[1-6]-*.md`，本规划引用不重复定义）+ 跨项目接口契约 v1.2（`docs/architecture/cross-project-interface-contract.md`）
> **范围**：warehouse agent 脚手架迁移 + P0 Foundation 六件套 + P1 只读 Agent MVP（知识 Agent + 数据分析 Agent）
> **不在范围**：P2 任务执行（报馆/场馆运营·写操作/HITL/执行引擎）、P3 强依赖（招商/智能化）、本体引入

---

## 1. 背景与现状基线

### 1.1 愿景执行计划（§22-§25 摘要）

```text
P0 Foundation 六件套（须先跑起来）
  18 身份与租户 ── 08 知识平台 ── 16 检索与隔离
  13 Data Readiness
  15 治理评测（Golden Set + 跨租户负样本）
  14 可观测（retrieval trace + 越权/过期计数）
        ▼
P1 只读 Agent MVP（Foundation 就绪后）
  知识 Agent（Phase 1，L1，基于 08/16）
  数据分析 Agent（Phase 3，L2，基于 F04 Metric Registry + 13）
```

> 🔴 **"能开发" ≠ "能上线"**（§22.0）：库内数据以合成为主，P0/P1 交付物在 Production Ready 条件满足前，数值输出须标 `SYNTHETIC`/`NOT_CONNECTED`/`PARTIAL`，禁止冒充实生产事实。

### 1.2 agent-platform 仓库现状

| 模块 | 现状 | 对应愿景件 |
| --- | --- | --- |
| `packages/agent-runtime/` | 通用运行时中间件：admission / cache / circuit_breaker / coordinator / context / db / otel / tracing / mcp_client / planner / skills / sandbox / schemas / trajectory | Foundation 横切能力底座 |
| `packages/agent-core/` | 零依赖内核：tracing / guardrails / llm / memory / events / config / intent / resilience | Foundation 内核 |
| `applications/exhibition-agent/` | **骨架已建**（契约 v1.2，114 passed）：C1 ExecutionContext 中间件 / C2' 直接 REST 客户端 / C4 trace（11 字段）/ 1 只读 skill（venue.schedule.query）/ mock server 9 场景 / INV-10 回归测试 / skill_loader（48 端点） | 18 / 14 / 契约 |
| `applications/zhanggui-zhiku/` | **生产级 RAG 知识库**（M1-M8 工程化，Milvus+Neo4j+MinIO，:8900）：导入→切分→向量化→检索→重排→KG→问答；12 节点仅 2 个业务专属（item_name NER） | **通用知识库能力实例** |
| `applications/wenda-data-agent/` | **Text-to-SQL 问数**（12 节点 LangGraph，pgvector+sqlglot）：NL→关键词→表/列/指标召回→SQL 生成→只读守卫→执行→纠正循环 | **通用 SQL 问数能力实例** |
| `eval/` | 启发式 eval（15 golden）+ `run_planner_eval.py` 双 Planner 基线 | 15 治理评测（雏形） |

### 1.3 exhibition-agent 架构红线（规划须遵守）

- **显式不依赖** `shared-schemas` / `agent-runtime`（跨项目契约独立交付；ExecutionContext 是跨项目对外契约，与联邦内部契约是另一套口径）
- 不直连 MySQL（INV-6）、不 vendor warehouse 代码、不引入 LangChain 全家桶、不设"测试跳过校验"开关
- observability 已复用 `agent_core.tracing`（豁免范围仅限 contract/skills/middleware）

> ⚠ **关键张力**：ExecutionContext 目前是 exhibition-agent 自带实现，未共享到 agent-runtime。P0 须决定共享边界（见 §5.3 待决项 D-CTX）。

### 1.4 通用能力抽象定位（agent-platform = 通用能力平台）

> **核心定位**：agent-platform 是**通用能力平台**，将通用知识库、通用 SQL 问数等能力抽象出来，各业务应用复用，差异只在知识内容/元数据/指标定义。

**现有两个通用能力实例**（名字带业务/课程来源，能力本身通用，重构时规范化命名）：

| 现名 | 通用能力 | 建议规范名 | 业务耦合 | 通用化改造 |
| --- | --- | --- | --- | --- |
| `zhanggui-zhiku`（掌柜智库） | 知识库（RAG：导入→切分→向量化→检索→重排→KG→问答） | `knowledge-service` | 2 个 item_name 节点（电商商品名 NER） | 摘 2 节点 + Metadata 参数化 + 多租户隔离 |
| `wenda-data-agent`（问数） | SQL 问数（NL→关键词→表/列/指标召回→SQL 生成→只读守卫→执行→纠正循环） | `nl2sql-service` | 名字带课程来源"zhanggui-wenda" | 元知识参数化（表/列/指标定义作为配置）+ 命名去课程化 |

**服务暴露方式：分两层**（与 exhibition-agent 现有调 warehouse 模式一致）：

| 层 | 形式 | 内容 | 理由 |
| --- | --- | --- | --- |
| **重量服务层** | 独立 FastAPI 服务，HTTP REST | `knowledge-service`（Milvus/Neo4j/MinIO/torch）、`nl2sql-service`（pgvector/sqlglot） | 重依赖隔离——消费方不被迫装 torch/Milvus；独立扩缩容；与 exhibition-agent HTTP 调 warehouse 一致 |
| **轻量契约层** | `packages/` import 共享 | Metadata schema、生命周期状态机、错误码、检索接口定义 | 消费方获得类型安全客户端；无网络开销；与 shared-schemas/agent-runtime 一致 |

```text
通用能力服务（独立运行，HTTP 被消费）
  knowledge-service（原 zhanggui-zhiku）  ← 知识库存入/获取，:8900
  nl2sql-service（原 wenda-data-agent）   ← SQL 问数

业务应用（消费通用能力 + 业务场景元数据）
  exhibition-agent  ← 会展：HTTP 调 knowledge-service + nl2sql-service + warehouse REST
  kefu-service      ← 客服：调 dialogue-framework
```

> ⚠ **不提取到单一共享包**：knowledge-service 依赖 torch/Milvus/Neo4j，nl2sql-service 依赖 pgvector——若 import 共享，消费方被迫装全部重依赖，违背轻量应用原则。各自独立服务 HTTP 暴露，消费方 import 轻量契约 + HTTP 调重量服务。

### 1.5 两项目清晰边界（v2 新增）

> **用户明确决策（2026-09-22）**：mingyang-warehouse 侧新增的 agent 相关能力放错了位置，agent 能力应统一放 agent-platform 侧。两项目须有明确清晰边界。

| 项目 | 定位 | 拥有 | 不拥有 |
| --- | --- | --- | --- |
| **mingyang-warehouse** | 纯数据服务 | 业务数据（MySQL 168 表）、REST API（49 GET + 1 POST）、数据模型（`datamod/`）、前端 | 任何 agent / AI / LLM / 知识库 / 检索 / 评测 / 模型路由 |
| **agent-platform** | 通用 AI 能力平台 | 所有 agent 能力（ExecutionContext / Model Router / 知识生命周期 / Metric Registry / 评测 / Readiness Gate / Skill Router）、通用服务（knowledge-service / nl2sql-service）、业务应用（exhibition-agent） | 业务数据存储、数据计算 |

**warehouse 侧误放的 agent 代码**（`ontology/web/backend/` 下，均标"脚手架版"/"不注册到 main.py"，`main.py` 不导入任何 agent 模块）：

| 文件 | 行数 | 对应契约 | 内容 | 依赖 |
| --- | --- | --- | --- | --- |
| `execution_context.py` | 247 | F01 | ExecutionContext 编解码 + scope 校验 + 审计 | 纯 Python 无 warehouse 依赖 |
| `data_egress.py` | 275 | F02 | 数据分级 / 出域策略 / 模型路由 | 纯 Python |
| `knowledge_lifecycle.py` | 221 | F03 | 知识状态机 DRAFT→PUBLISHED→EXPIRED + 审计 | 纯 Python |
| `metric_registry.py` + `.json` | 197 | F04 | 指标六态 + readiness 映射 | `tool_catalog.json` |
| `evaluation.py` | 276 | F05 | Golden Set 四类 + 越权/过期检测 | `knowledge_lifecycle` |
| `production_readiness_gate.py` + `manifest.json` | 356 | F06 | 六门门禁 + 审计 | `metric_registry.json` + sqlite3 |
| `skill_router.py` + `tool_catalog.json` | 211 | P1 | discriminator→Tool 映射 + scope 校验 | `tool_catalog.json` |
| `init_agent_skill_lab.py` | 46 | P2 | 招商线索实验库初始化 | `datamod.leads`（唯一 warehouse 数据依赖） |
| `skills/mingyang-venue-ops/` | — | skill | 场馆运营只读 skill 定义 + manifest | — |
| `skills/exhibition-readonly/` | — | skill | 会展只读 skill + golden 测试 | — |

**warehouse 侧保留的纯数据服务**：

| 文件/目录 | 内容 |
| --- | --- |
| `main.py` | FastAPI 数据 REST API（49 GET + 1 POST），不导入任何 agent 模块 |
| `data.py` / `db.py` | 数据端点 + 数据库连接 |
| `datamod/` | 数据模型（exhibition / venue / exhibitor / audience / contract / safety / meeting / clue / leads / predict 等） |
| `_deploy_*.py` | 部署脚本 |

> ✅ **知识存储边界已决**：知识 Metadata + 向量索引 + 生命周期状态机**全部在 agent-platform 侧**（knowledge-service 拥有）。warehouse 仅通过 REST 提供原始业务数据；知识语料采集自文档/手册，不经 warehouse。

---

## 2. P0 Foundation 落地映射

> 每件：现状 → 目标 → 执行项 → 依赖契约 → 验收。**字段级契约引用 F01-F06，不在此重复定义。**

### 2.0 迁移批次：warehouse agent 脚手架 → agent-platform（v2 新增）

> **P0 第一步**：将 warehouse 侧误放的 agent 脚手架代码迁移到 agent-platform，建立两项目清晰边界。迁移后 warehouse 不含任何 agent/AI 代码。

| 项 | 内容 |
| --- | --- |
| 目标 | warehouse 侧 8 个 agent 文件 + 2 个 skills 目录迁移到 agent-platform；warehouse 仅保留纯数据服务 |
| 迁移项 | 见 §1.5 表（execution_context / data_egress / knowledge_lifecycle / metric_registry + .json / evaluation / production_readiness_gate + manifest.json / skill_router + tool_catalog.json / init_agent_skill_lab / skills/ 两个目录） |
| 落点 | `applications/exhibition-agent/foundation/`（F01-F06 脚手架）+ `applications/exhibition-agent/skills/`（skill 定义）|
| 执行项 | ① 将 8 个 .py + 3 个 .json 迁移到 `exhibition-agent/foundation/`，调整 import 路径（evaluation→knowledge_lifecycle, metric_registry→tool_catalog, production_readiness_gate→metric_registry 互相依赖，整体迁移）<br>② 将 `skills/` 两个目录迁移到 `exhibition-agent/skills/`<br>③ `init_agent_skill_lab.py` 依赖 `datamod.leads`——leads 是 P2 招商线索实验库，迁移时断开 warehouse 依赖（改为 agent-platform 侧独立 sqlite3 或暂不迁移，标 P2）<br>④ 迁移后跑通 exhibition-agent 现有 114 测试（确保不破坏）<br>⑤ **warehouse 侧删除已迁移文件**（确认 agent-platform 侧测试通过后）<br>⑥ 跨项目契约 §0 表述纠正：知识平台从 warehouse 侧移到 agent-platform 侧 |
| 验收 | agent-platform 侧迁移代码 import 无断链、114 测试全绿；warehouse 侧 `main.py` 仍可独立启动（49 GET + 1 POST 不受影响）；warehouse `ontology/web/backend/` 不含任何 agent 文件 |

> ⚠ **迁移注意**：`init_agent_skill_lab.py` 依赖 `datamod.leads`（warehouse 数据层），是唯一有跨项目数据依赖的 agent 文件。leads 是 P2 招商线索实验库（sqlite3），不属于 P0 范围。迁移策略：P0 暂不迁移此文件，标 P2 随招商线索功能一并处理。

### 2.1 件 18：身份与租户（ExecutionContext）

| 项 | 内容 |
| --- | --- |
| 契约 | **F01**（ExecutionContext 字段冻结、R1-R5、F1-A/B/C/D） |
| 现状 | **两处实现**：① exhibition-agent 自带 `middleware/execution_context_middleware.py` + `contract/execution_context.py`（C1 已实现，114 passed）；② warehouse 侧 `execution_context.py`（247 行脚手架，迁移后落 `foundation/`） |
| 目标 | 统一到 exhibition-agent 内 C1 完整可用；**共享边界待决**（D-CTX） |
| 执行项 | ① 迁移 warehouse 侧 `execution_context.py` 到 `foundation/`，与 exhibition-agent 自带实现对齐/合并（两份实现功能重叠，须审计差异后取合并集）<br>② 补 `tenant_type` 枚举缺"主场服务商"（F01 §6 待补）<br>③ 补 F1-D 服务凭证与权限映射（平台访问下游业务系统的机器通道）<br>④ 跨租户访问审计记录（R3，含 request_id/user_id/目标 tenant_id）<br>⑤ DEMO/SANDBOX 模式对外输出标注"演示环境，非生产"（R5） |
| 依赖 | F01 §3.1-3.4 |
| 验收 | 越权 scope → 403 且不返回部分结果（R2，防侧信道）；跨租户访问有审计记录；DEMO 模式输出带标注 |

**待决项 D-CTX**：ExecutionContext 是否提取到 `agent-runtime/context/` 共享？
- 选项 A：保持 exhibition-agent 自带（跨项目契约独立，豁免理由成立）
- 选项 B：提取通用 ExecutionContext 抽象到 agent-runtime，exhibition-agent 跨项目契约层适配
- **建议**：P0 阶段保持 A（exhibition-agent 自带已验证 114 passed），待第二个消费方出现再提取（YAGNI）

### 2.2 件 13：Data Readiness

| 项 | 内容 |
| --- | --- |
| 契约 | F01 §3.4 + 契约 C2' `data_readiness.level` |
| 现状 | exhibition-agent 已有 readiness 枚举（`contract/envelope.py`，READY/SYNTHETIC/NOT_CONNECTED/PARTIAL）+ INV-10 双轨落地（422 错误码 + 200 data_readiness.level=pending）；warehouse 侧 `production_readiness_gate.py`（356 行，六门门禁）+ `metric_registry.py`（197 行，readiness 映射）迁移后落 `foundation/` |
| 目标 | 平台侧 readiness 台账 + 缺源降级策略完整 + Readiness Gate 落地 |
| 执行项 | ① 迁移 `production_readiness_gate.py` + `metric_registry.py` + 相关 .json 到 `foundation/`<br>② 数据源/知识源台账（Domain API 返回值标注 readiness）<br>③ 缺源降级：`NOT_CONNECTED` → 答"该指标待接入"，全程不生成 SQL（INV-10，已有回归测试）<br>④ Readiness Gate 六门集成（F06：Identity/Knowledge/Data/Evaluation/Security/Observability） |
| 依赖 | F04（Metric Registry 状态机决定 readiness）+ F06（Readiness Gate） |
| 验收 | `METRIC_NOT_VERIFIED`/`METRIC_BLOCKED`/`DATA_NOT_CONNECTED` → 答"待接入" + `sql_statements == []`（已有 `tests/test_inv10_no_sql.py`）；Readiness Gate 六门可判 |

### 2.3 件 08：会展知识平台

| 项 | 内容 |
| --- | --- |
| 契约 | **F03**（Q3-A 语料 / Q3-B 角色 / Q3-C 生命周期 DRAFT→REVIEWING→PUBLISHED→EXPIRED/REVOKED/SUPERSEDED / Metadata 必备项） |
| 现状 | `zhanggui-zhiku` 已是生产级 RAG 实例（M1-M8 工程化，Milvus+Neo4j+MinIO，:8900）；12 节点仅 2 个业务专属（item_name NER）；warehouse 侧 `knowledge_lifecycle.py`（221 行，状态机脚手架）迁移后落 `foundation/`；**会展知识语料未接入** |
| 目标 | 通用化为 `knowledge-service`：摘业务专属节点 + Metadata 参数化 + 多租户/多知识空间 + 生命周期状态机（迁移脚手架 + 补 AI 侧检索引擎） |
| 执行项 | ① 迁移 `knowledge_lifecycle.py` 到 `foundation/`，作为 knowledge-service 生命周期管理起点<br>② **通用化 zhanggui-zhiku → knowledge-service**：摘除 2 个 item_name 节点（或改可插拔）<br>③ Metadata 参数化：`scope_type=PUBLIC/PRIVATE`、`tenant_id`、`tenant_type`、`effective_from/to`、`version`、`authority`、`status`、`constraint_kind` 作为 `/upload` `/query` 入参（非硬编码）<br>④ 生命周期状态机集成到 knowledge-service（`DRAFT→REVIEWING→PUBLISHED→EXPIRED/REVOKED`，仅 `PUBLISHED` 进 Production Retrieval）<br>⑤ 多租户/多知识空间：Milvus collection 内按 `tenant_id+scope_type` 隔离/过滤（ACL 前置，INV-8）<br>⑥ 入库链路：采集→切分→初标 Metadata→复核→发布（3-5 份真实手册跑通闭环，F03 §2 首期建议） |
| 依赖 | F03（语料清单 Q3-A 待超管审定 / 角色责任方 Q3-B 待确认） |
| 验收 | 3-5 份真实手册走通"采集→标注→审核→发布→可检索"；非 PUBLISHED 知识不进检索；缺 authority/effective_from/to 不得 PUBLISHED；多租户隔离生效 |
| 落地点 | `applications/knowledge-service/`（原 zhanggui-zhiku 通用化 + 改名，独立 HTTP 服务 :8900）；轻量契约（Metadata schema/生命周期状态机）提取到 `packages/` 共享 |

> 🔴 **F3 是 P0 硬阻塞**：无语料 = 知识平台空壳 = Phase 1 知识 Agent 无法 Production Ready。首期 3-5 份真实手册的提供方/审定方须尽快确认。
> ✅ **知识存储全在 agent-platform 侧**：Metadata + 向量索引 + 生命周期状态机均由 knowledge-service 拥有，不依赖 warehouse 存储。

### 2.4 件 16：知识检索与隔离

| 项 | 内容 |
| --- | --- |
| 契约 | F01 R4（Scope 下推）+ F03 Metadata + INV-8（检索隔离）+ §18.4（ACL 前置）+ §18.5（四级检索） |
| 现状 | `zhanggui-zhiku` 已有检索链路（embedding→RRF→rerank→KG），但无 ACL/Scope 前置过滤、无多租户隔离、无越权/过期计数 |
| 目标 | 在 `knowledge-service` 内补齐：ACL/Scope 前置过滤 + Hybrid Search（BM25+Dense）+ RRF + Rerank（L1+L2 主路径）+ 越权/过期计数 |
| 执行项 | ① ACL/Scope 前置过滤（检索入参下推索引层，非召回后过滤；消费 ExecutionContext 的 tenant_id/scopes）<br>② Hybrid Search + RRF + Rerank<br>③ Query Rewrite（L3，术语表起步，§18.10 已纳 MVP）<br>④ 越权召回数 = 0 + 过期知识召回数 = 0（确定性判据，须配跨租户负样本集，见 §2.5）<br>⑤ 知识优先级与冲突判定（§18.6 HARD>SOFT，确定性 resolver）<br>⑥ Graph Retrieval（L4）—— **P3 按需，P0 不做**（§18.9 五条引入条件） |
| 依赖 | 件 08（知识平台）+ 件 18（ExecutionContext）+ F03 Metadata |
| 验收 | 跨租户检索不返回他租户知识；DRAFT/EXPIRED/SUPERSEDED/REVOKED 不进生产回答；越权召回数=0、过期召回数=0 |
| 落地点 | `applications/knowledge-service/` 内（检索是 RAG 服务核心能力）；ACL/Scope 前置过滤 + 越权/过期计数在服务内强制 |

### 2.5 件 15：LLM 治理与评测

| 项 | 内容 |
| --- | --- |
| 契约 | **F05**（Golden Set 类别+通过标准冻结，最小集 20/20/10/10）+ F02（Model Router）+ §19（Groundedness/Hallucination/Cost） |
| 现状 | `eval/` 有启发式 eval（15 golden）+ `run_planner_eval.py` 双 Planner 基线；warehouse 侧 `data_egress.py`（275 行，F02 脚手架）+ `evaluation.py`（276 行，F05 脚手架）迁移后落 `foundation/` |
| 目标 | Golden Set 扩展 + 跨租户负样本集 + groundedness 判据 + Model Router 落地 |
| 执行项 | ① 迁移 `data_egress.py` + `evaluation.py` 到 `foundation/`<br>② Golden Set 冻结测试类别+通过标准（规模用最小集，不锁死终值，随语料扩充）<br>③ 跨租户负样本集（越权召回检测的确定性判据）<br>④ Groundedness 强制：无 Citation 即无回答（§18.8，知识类响应 citations 必填）<br>⑤ **Model Router 落地**（F02 §17.5）：数据分级→出域策略→模型路由；Agent 不得自选模型；三类模型 Small/Private(Qwen 默认+DeepSeek 第二线)/Cloud。迁移 `data_egress.py` 脚手架作为起点，补 LLM 调用实体<br>⑥ Cost per Business Outcome 可观测 |
| 依赖 | F02（数据分级/出域/路由）+ F05（Golden Set）+ 件 08（知识语料） |
| 验收 | 跨租户负样本越权召回=0；知识回答必有 Citation；Model Router 按数据级别路由（CONFIDENTIAL/PII/FINANCIAL → Private Only） |
| 落地点 | Model Router：`exhibition-agent/foundation/data_egress.py`（迁移脚手架）→ 补 LLM 调用实体；评测：扩展 `eval/` + `foundation/evaluation.py` |

> 🔴 **F2 是 P0 硬阻塞**：出域策略未定 ⇒ 任何 Agent 不得进生产（§24.3）。Model Router 须在知识 Agent 入模前落地（知识 Agent 入模内容尤甚）。

### 2.6 件 14：可观测性

| 项 | 内容 |
| --- | --- |
| 契约 | 契约 C4（trace 11 字段）+ §20（Agent Trace + 核心指标） |
| 现状 | exhibition-agent 有 `observability/trace.py`（TraceRecord 11 字段 + InMemoryTraceRecorder）；agent-core 有 `tracing`；agent-runtime 有 `tracing`/`otel` |
| 目标 | retrieval trace 完整 + 越权/过期计数 + 成本可观测 |
| 执行项 | ① retrieval trace 扩展（检索命中 IDs、优先级判定、冲突判定留痕）<br>② 越权召回计数 + 过期知识召回计数（确定性指标，对接件 16）<br>③ 成本可观测（model/cost 字段，对接 Model Router）<br>④ trace 持久化（InMemory → 可选 OTel/外部 sink，agent-runtime.otel 已有底座） |
| 依赖 | 件 16（检索，提供越权/过期计数源）+ 件 15（Model Router，提供 model/cost） |
| 验收 | 每条 trace 含 request_id（C4）；越权/过期计数可查；成本可观测 |

---

## 3. P1 只读 Agent MVP 落地

> P0 Foundation 就绪后启动。只读 Agent 无副作用、不需要执行引擎与审批，依赖面最窄。

### 3.1 知识 Agent（Phase 1，L1）

| 项 | 内容 |
| --- | --- |
| 定位 | §8.4 会展知识 Agent——知识平台在 Agent 层的唯一入口，非 PDF Chat |
| 能力 | 分层知识检索（公开+垂类私域）+ Scope 隔离 + 答案契约（Citation/Version/EffectiveDate/Scope/Confidence/ConflictWarning） |
| 依赖 | `knowledge-service`（HTTP）+ 件 18（ExecutionContext） |
| 执行项 | ① 知识 Agent skill（`knowledge.query`，**HTTP 调 `knowledge-service` 的 `/query`**，传入会展 Metadata：`scope_type`/`tenant_id`/`exhibition_id`/`venue_id`）<br>② 答案契约落地（§18.8，校验返回的 Citation，无 Citation 即不展示）<br>③ 知识-业务冲突检测（§18.7，MVP 搭双路比对骨架，全量覆盖待 Domain API 就绪）<br>④ 挂到 exhibition-agent Supervisor 图（复用现有 graph/） |
| 验收 | 参展商问"报馆需要哪些材料？" → 公开+企业级+实例级同时召回 + 按优先级定主答案 + 带 Citation；越权不返回他租户知识 |
| 生产就绪条件 | 真实语料入库 + Metadata 齐备 + 越权召回数=0（§22.0） |

### 3.2 数据分析 Agent（Phase 3，L2）

| 项 | 内容 |
| --- | --- |
| 定位 | §8.1 数据分析 Agent——自然语言问数 |
| 能力 | 问数三层架构（§11.4.1）：L1 指标层（Metric Registry）/ L2 LLM 语义解析出 DSL / L3 受限 text2sql 兜底 |
| 依赖 | `nl2sql-service`（HTTP）+ **F04 Metric Registry**（硬前置）+ 件 13（Data Readiness）+ 件 18 |
| 执行项 | ① **HTTP 调 `nl2sql-service`**，传入会展指标定义/元知识（表/列/指标作为配置）<br>② Metric Registry 状态机校验：非 `VERIFIED` 不得执行（INV-10，exhibition-agent 已有回归测试）。迁移 `metric_registry.py` 脚手架作为起点<br>③ L2 语义解析（LLM 选指标，不造口径）<br>④ L3 受限 text2sql 兜底（不得重新实现/改写已注册 Metric 口径，INV-10）<br>⑤ 先 3-5 个指标跑通（F04 §2，销售率/空置率标 BLOCKED 不进可执行集） |
| 验收 | `VERIFIED` 指标可查；`BLOCKED`/`NOT_CONNECTED` → 答"待接入" + 不生成 SQL；LLM 只选指标不造口径 |
| 生产就绪条件 | 数据源 READY（非 SYNTHETIC）+ Metric Registry 注册完成（F4） |

---

## 4. 依赖图与批次排序

```text
┌─ 批次 0：迁移 ───────────────────────────────────────────────┐
│  warehouse agent 脚手架 → agent-platform（建立两项目边界）   │
│  execution_context / data_egress / knowledge_lifecycle /     │
│  metric_registry / evaluation / production_readiness_gate /  │
│  skill_router + tool_catalog / skills/ 两个目录              │
│  ⚠ init_agent_skill_lab.py 暂不迁移（P2，依赖 datamod.leads）│
└────────────────────────────────────────────────────────────────┘
                          ▼
┌─ P0 Foundation · 须先跑起来 ──────────────────────────────────┐
│                                                                │
│  18 ExecutionContext（合并两份实现 + 补审计/F1-D/枚举）        │
│       │                                                        │
│       ▼                                                        │
│  08+16 knowledge-service 通用化（zhanggui-zhiku 改造，F3 硬阻塞）│
│       （含检索隔离：ACL/Scope/多租户在 service 内补齐）         │
│       （知识 Metadata + 向量索引 + 生命周期全在 service 内）    │
│                                                                │
│  13 Data Readiness（迁移 readiness gate + 补台账）            │
│                                                                │
│  F02 Model Router（迁移 data_egress 脚手架→补 LLM 实体，F2 硬阻塞）│
│       │                                                        │
│       ▼                                                        │
│  15 治理评测（迁移 evaluation 脚手架 + 扩展 Golden Set）      │
│       │                                                        │
│       ▼                                                        │
│  14 可观测（已有 trace，补检索/越权/成本）                     │
│                                                                │
│  ⚠ F2/F3 未决 ⇒ 以上全部【不得进生产】（只可开发/演示）        │
└────────────────────────────────────────────────────────────────┘
                          ▼
┌─ P1 只读 Agent MVP ───────────────────────────────────────────┐
│                                                                │
│  knowledge-service ──▶ 知识 Agent（Phase 1，L1，HTTP 调用）   │
│  nl2sql-service + F04 ──▶ 数据分析 Agent（Phase 3，L2，HTTP）  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**建议执行顺序**（按就绪度推导，非编号锁死，§22 T8 裁决）：

1. **批次 0：迁移**（建立两项目边界，后续一切的前提）
2. **件 18 补全**（合并两份实现，增量最小，先收口）
3. **F02 Model Router 落地**（迁移脚手架 + 补 LLM 实体，F2 硬阻塞，解除后其余件才能进生产评估）
4. **knowledge-service 通用化**（含件 08 知识平台 + 件 16 检索隔离；F3 语料到位后推进）
5. **件 13 Data Readiness**（迁移 readiness gate + 与 08/16 并行，独立）
6. **件 15 治理评测**（迁移 evaluation 脚手架 + 依赖 08 语料 + F02 Router）
7. **件 14 可观测**（依赖 16 检索 + 15 Router，最后收口）
8. **P1 知识 Agent**（knowledge-service 就绪后，HTTP 调用）
9. **P1 数据分析 Agent**（nl2sql-service + F04 就绪后，HTTP 调用，可与 8 并行）

---

## 5. 阻塞项与待决

### 5.1 P0 硬阻塞（不定则无法进生产）

| # | 阻塞项 | 契约 | 状态 | 解除动作 |
| --- | --- | --- | --- | --- |
| **F2** | 数据分级/出域/模型路由未决策 | F02 | 🟠 脚手架已迁移，待补 LLM 实体 | 定 Data Classification（5 级）→ Egress Policy（企业级）→ Model Router；私有默认 Qwen+DeepSeek |
| **F3** | 知识语料未接入 + Metadata 标注责任方未定 | F03 | 🟠 状态机已迁移，待语料 | 先拿 3-5 份真实手册跑通"采集→标注→审核→发布"闭环；确认 Q3-A 语料清单 + Q3-B 角色责任方 |

### 5.2 P1 硬前置

| # | 项 | 契约 | 状态 |
| --- | --- | --- | --- |
| **F4** | Metric Registry 未建立（现有 `指标定义.md` 为口径文档，非可执行 registry） | F04 | 🟠 脚手架已迁移，待按 schema 注册，先 3-5 个指标跑通 |

### 5.3 本规划待决项

| # | 待决 | 建议默认 | 切换成本 |
| --- | --- | --- | --- |
| D-CTX | ExecutionContext 是否提取到 agent-runtime 共享 | 保持 exhibition-agent 自带（§2.1 选项 A） | 待第二消费方出现再提取 |
| D-KG | 知识平台落点 | ✅ **已决**：`knowledge-service`（原 zhanggui-zhiku 通用化，独立 HTTP 服务） | — |
| D-STORAGE | 知识存储边界 | ✅ **已决**：Metadata + 向量索引 + 生命周期状态机全在 agent-platform 侧 knowledge-service | — |
| D-NL2SQL | nl2sql-service 通用化范围 | 原 wenda-data-agent 改造：元知识参数化 + 命名去课程化 | 中 |
| D-RENAME | 通用服务改名时机（zhanggui-zhiku→knowledge-service / wenda-data-agent→nl2sql-service） | 随通用化改造一并改（pyproject/import/CI/部署） | 中 |
| D-VEC | 向量存储选型 | ✅ **已决**：Milvus（zhanggui-zhiku 已用，稠密+稀疏混合检索） | — |
| D-F6 | Production Readiness Gate 判定人 | Foundation 负责人 + 业务 Owner 双签（F06） | 低 |
| D-MERGE | 迁移后两份 ExecutionContext 实现合并策略 | 审计差异后取合并集（exhibition-agent 自带已 114 passed 为基线，warehouse 脚手架增量补入） | 低 |

---

## 6. 验收标准（P0 + P1）

### 6.1 P0 Foundation 完成判据（缺一不可，§23 P0）

- [ ] **两项目边界清晰**：warehouse 不含任何 agent/AI 代码；agent-platform 拥有所有 agent 能力
- [ ] 身份与租户上下文可用：Retrieval 能拿到可信 `tenant_id/role/scope`（F1）
- [ ] 出域策略已定：Model Router 按数据级别路由，Agent 不自选模型（F2）
- [ ] 知识可检索：真实语料入库且带 `effective_from/to`/`version`/`authority`/`status`（F3）
- [ ] **越权召回数 = 0**（配跨租户负样本集）
- [ ] **过期知识召回数 = 0**（非 PUBLISHED 不进生产回答）

### 6.2 P1 只读 Agent MVP 验收

- [ ] 知识 Agent：分层检索 + 答案契约（无 Citation 即无回答）+ 越权隔离
- [ ] 数据分析 Agent：`VERIFIED` 指标可查；非 VERIFIED → 答"待接入" + 不生成 SQL（INV-10）
- [ ] `uv run pytest` 全绿（exhibition-agent 现有 114 + 新增用例）
- [ ] 合成数据输出显式标注 `SYNTHETIC`/`NOT_CONNECTED`/`PARTIAL`，不冒充实生产事实

---

## 7. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **迁移破坏 exhibition-agent 现有 114 测试** | 迁移后 import 断链或行为漂移 | 迁移前冻结 114 测试基线；迁移后立即跑通；两份 ExecutionContext 实现审计差异后合并，以 114 passed 为准 |
| **warehouse 侧删除文件误删纯数据服务代码** | warehouse REST API 不可用 | 严格按 §1.5 表区分；仅删 agent 文件，保留 main.py/data.py/db.py/datamod/；删除前确认 agent-platform 侧测试通过 |
| F3 语料提供方/审定方迟迟不定 | knowledge-service 无会展语料，P1 知识 Agent 无法 Production Ready | 先用 3-5 份公开手册（T3 已裁决：公司自有对外公开，超管审定）跑通闭环，垂类私域后补 |
| F2 出域策略过度复杂 | Model Router 落地延期 | 私有化≠训练私有模型（§17.2），第一阶段重点是"推理时数据不出域"，先 Private LLM 默认，Cloud 按需 |
| exhibition-agent 与 agent-runtime 共享边界反复 | 重构 churn | P0 保持 exhibition-agent 自带（D-CTX 选项 A），待第二消费方出现再提取，避免过早抽象 |
| 契约 v1.2 未回提主本 | 两份契约漂移 | exhibition-agent README 已登记"契约回提声明"，P0 期间完成回提 |
| Metric Registry（F4）warehouse 侧未就绪 | P1 数据分析 Agent 阻塞 | P1 知识 Agent 不依赖 F4，可先行；数据分析 Agent 等 F4 就绪 |
| knowledge-service 通用化改造引入回归 | zhanggui-zhiku 现有 M1-M8 工程化被破坏 | 改造前冻结现有测试基线，每步增量验证；item_name 节点先改可插拔（保留原测试）再摘除 |
| 跨项目契约 §0"知识平台"列在 warehouse 侧表述错误 | 与"warehouse 不做 AI"矛盾，误导落地 | 迁移批次中一并纠正契约主本 |

---

## 附：与现有 plan 的关系

| 现有 plan | 关系 |
| --- | --- |
| `plan-f-single-runtime-multi-planner.md` | 本规划在 agent-runtime 能力底座上落地；Plan-F 的单 Runtime 多 Planner 是编排层收敛，本规划是会展垂直能力落地，正交 |
| `plan-fix-f-s1-05-contract-revise-to-rest.md` | 契约 v1.1→v1.2 修订已闭环（exhibition-agent 114 passed），本规划在其基础上推进 P0/P1 |
