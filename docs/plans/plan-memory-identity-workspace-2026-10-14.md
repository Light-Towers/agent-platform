# 身份 · 隔离 · 记忆 · 画像 · 工作空间：现状事实卡与分阶段方案（2026-10-14）

> 性质：**方案文档，不含任何代码改动**。触发原因：需求方确认"一个完整的企业级 agent 平台需要这些能力"，
> 并要求先核实 RAG 检索是否带 `workspace_id` 谓词（结论见 §1.4，它改写了阶段划分）。
> 关联：ADR-0004（typed memory kernel）· ADR-0006（T9/W1 隔离双维、T10 工作空间注册）·
> ADR-0007（身份=服务端断言租户）· **已立案待拍板：`plan-query-tenant-from-client-not-server-asserted-2026-10-10.md`**
> （数据面读客户端 tenant 的完整取证，本文阶段 1 = 执行它，不重复立案）·
> `plan-tenant-identity-2026-09-27.md` · `plan-p0-ha-tenant-fixes-2026-09-25.md` ·
> `docs/plans/plan-observability-target-model-2026-10-14.md`（同一套"先方案后编码"纪律）·
> 台账与基线（均在 `docs/operations/minimal-release-runbook.md`）：§9 台账 ⑮（search 未启用）、
> ㉓（观测面含原文）、㉔（记忆回放带取证标识）；§5 基线 2 下那段"服务端断言目前只对会话归属成立"的收窄表述。
>
> **证据强度标注**（本文所有结论都带这个标记，动手前按标记决定要不要复核）：
> ✅ = 本轮我逐条读原文复查过；◻ = 子代理探查读数，**我未逐条复核**，实施前必须自己确认。

## 0. 一句话结论

**多轮会话已真通；跨会话不是"缺功能"而是"粒度错了"；画像与工作空间是"表结构与谓词链都在、值的来源不对"。**
所以真正要补的不是四个能力，而是**一个前置**：数据面的 `tenant_id / workspace_id / user_id` 现在**来自客户端请求**，
而会话与审计侧已经改成**服务端断言** ⇒ 同一个请求里并存两套口径。身份不落地就打开画像与多空间，
得到的不是"每人一份画像、每部门一个空间"，而是"调用方自选桶 + 全公司共用一份画像"。

## 1. 现状事实卡

### 1.1 多轮会话（✅ 全条复查）

| 项 | 事实 | 证据 |
|---|---|---|
| 载体 | LangGraph `AsyncPostgresSaver`，三张表 `checkpoints/checkpoint_blobs/checkpoint_writes` | `applications/agent_server/main.py:46-62` → `packages/agent-core/agent_core/memory/__init__.py:83-92`；表由 `saver.setup()` 建，**仓库 SQL 迁移里没有它们的 DDL** |
| thread 身份 | 鉴权开启即**忽略客户端 session_id**，一律 `tenant-<default_tenant_id>`（现网 `tenant-default`） | `api/auth.py:32-44`、`agent_core/guardrails/auth.py:56-84` |
| 历史进 prompt | reducer `add_messages` → `state.messages` 读并压缩；Planner 路径另有 `thread_persist` 读写 | `agent/state.py:32`、`agent/graph.py:86-104`、`thread_persist.py:23-41,64-118` |
| 形状后果 | 读只取最新一行 `aget_tuple` 的 `channel_values.messages`，写把整条列表重新序列化 ⇒ **消息不是独立行，删不了单句**（10-13 只能整桶清空的代码级原因） | `memory/recall_exact.py:70-75`、`thread_persist.py:87,106,116` |
| 清理 | checkpoint 保留器**只在 `agent_federation` 接线**，agent_server 没有 ⇒ 单服务侧只增不减 | `agent_federation/checkpoint_cleaner.py:83-109`、`api/server.py:101-103`（◻ 调用点） |

### 1.2 跨会话（✅）

- **没有** tenant 级 thread 列表、**没有**全局 state、**没有**画像聚合实体。
- 实际存在的两条跨会话通路都是副作用：
  1. **租户塌桶**：鉴权启用时所有客户端共用一个 thread ⇒ A 的历史自动进 B 的 prompt；
  2. **记忆按 (tenant, workspace|user) 召回，不按 thread** ⇒ 同租户内跨会话可见（`typed.py:477-506` ◻）。
- ⇒ 屏上"我之前问了哪些问题"能被答出来，是通路 1 + 2，**不是画像能力**。

### 1.3 用户画像（✅ 开关，◻ 细节）

| 项 | 事实 | 证据 |
|---|---|---|
| 有没有画像实体 | **没有** profile 表，**没有任何 `UPDATE memories`** ⇒ `importance` 写死不再演化，严格说只有"逐条事实" | grep 无命中（◻） |
| 最接近画像的东西 | `memories.scope='user'` 的行，需 `MEMORY_DUAL_SCOPE=True`；**默认 False**，关时 user 行降级写成 workspace 行 | ✅ `packages/agent-core/agent_core/memory/typed.py:149,290,301-310`（注释原文："画像不跨空间"） |
| 写入 | 每轮自动 `remember`；但 `memory_extraction_enabled=False` ⇒ **不抽结构化事实，整条 `"Q:…\nA:…"` 原文以 semantic/0.5 落库** | ✅ `applications/agent_server/config.py:47`；◻ `memory/longterm.py:142-152` |
| 召回 | pgvector 余弦 top-k，**无相似度阈值**；评分 `type_weight(1.2/1.1/1.0) × importance × 1/(1+0.01·age_days)` ⇒ ADR-0004 的"加权融合+时间衰减"真实存在 | ◻ `typed.py:71-83,158-173,478-485` |
| 遗忘 | `consolidate` 删 `importance<0.1 且 >30 天`，每 5 轮触发；单条 `forget_memory` **生产零调用、无端点** | ◻ `typed.py:407-442`、`longterm.py:159-185` |
| 半成品 | `SemanticMemory`/`UserSemanticStore`/`SharedSemanticStore` 无生产实现；`MemorySeeder` 仅测试引用 | ◻ `semantic_memory.py:54-109`、`ARCHITECTURE.md:148` |

### 1.4 RAG 检索的 workspace 谓词（✅ 本轮逐条复查——**这是本次最有价值的更正**）

**结论：带了，而且是双维、成对、全路径一致；不需要补 SQL。** 但**值的来源不可信**。

- 谓词链：`chunks` 的 INSERT / DELETE / 向量召回 / BM25 / 取回**五处全部**带
  `WHERE tenant_id = %s AND workspace_id = %s`（`applications/agent_server/rag/store.py:78,93,108,120,133,179`），
  契约写在文件头（ADR-0006 T9/W1）。
- `_tenant_gate.resolve_tenant` 只保证**显式性**（漏传即抛，绝不静默落 default 桶），
  **不校验值是否属于调用方**（`packages/agent-core/agent_core/memory/_tenant_gate.py:1-30`）。
- ⚠️ **真正的洞在这里**：数据面所有 `tenant_id` 都取自**客户端请求**——
  `req.tenant_id or "default"`（`api/query_router.py:94,108,237,264,273,359`）、`workspace_id=req.workspace_id`（`:52,271`），
  且 `workspace_id`/`tenant_id` 在契约里是**可选入参**（`packages/shared-schemas/shared_schemas/query.py:18` 默认 `None`）。
  ⇒ 今天的隔离是"**调用方自选桶**"，不是"边界"：传 `tenant_id=victim` 即可读该租户 chunks。
  **这一条不是新发现**——2026-10-10 已立案并逐条取证：`plan-query-tenant-from-client-not-server-asserted-2026-10-10.md`
  （11 处 `req.tenant_id`、`subagents/rag.py:10-19` 的守卫被调用方按参数语义合法绕过、`SINGLE_TENANT` 改非 default 会
  "入库了却永远检索不到且不报错"）。本文只把它**升格为阶段 1 的前置**，不重复立案。
- ⇒ 与 §1.1 的身份链**方向相反**：会话与审计已改服务端断言（ADR-0007），数据面还在吃客户端值。
  屏上 `租户身份: single` 与"能自选桶"同时成立，就是这个不一致的表现。
- 🆕 **今天新读出的一条（10-10 那份没记，且比"伪造"更要紧）**：`semantic_cache.cache_lookup` 在 `tenant_id`
  为**空串**时直接走"不加 WHERE"分支 ⇒ **跨全部租户全局匹配**（`packages/agent-runtime/agent_runtime/cache.py:51-61` ✅）。
  而触发它的不是攻击者，是**默认行为**：契约里 `tenant_id` 默认 `None`（`shared_schemas/query.py:18` ✅）→
  调用方 `req.tenant_id or ""`（`query_router.py:162,313` ✅）→ 空串 → 无谓词。控制台页面**不发**这个字段
  （10-10 方案事实 6）⇒ **现网今天每一次问答走的都是这条全局匹配分支**。
  单租户下库里只有一个桶，所以今天没有实际泄漏；但它的形状是"**第二个租户一写进来就立刻串**"，
  且不需要任何人主动伪造。**与 10-10 记的"自选租户"是两支不同的失效**：那支要调用方主动传值，这支是默认值。

### 1.5 工作空间（✅ 半边，◻ 半边）

- 定位是**归属表 + 注册表**，不是容器：`workspaces(tenant_id,id)` 复合主键（`migrations/007_workspaces.up.sql:7-13` ◻）
  + `chunks.workspace_id`（`002_workspace.up.sql:4` ◻）。**无文件、无生命周期、无对外 API**。
- 现网恒一个空间：`main.py:420` `workspace_id="default"` ✅（PlannerRuntime 身份硬编）。
- 归属校验是 defense-in-depth：**缺表即降级放行**（`workspace_registry.py:108-113,164-169` ◻）。
- ⇒ 准确说法："**隔离槽位已预留、谓词链已通**"，不是"多工作空间可用"。

### 1.6 两处"算了就丢 / 该判没判"（✅）

- `ContextGovernor` 治理出的 `governed_memories` 塞进 `PlannerContext` 后**全仓无读取点**
  （只有 `query_router.py:255-277` 赋值 + `planner/protocol.py:162` 定义）⇒ 记忆治理层"有实现、无装配"。
- `/session/revert` **不走 `resolve_thread_id`**，直接用客户端 `req.session_id` 当 thread_id
  （`session_router.py:72` + `revert.py:36`），且 `operator` 只写审计、**从不与 thread 归属比对**
  （`revert.py` 全文无归属判定，`FORBIDDEN` 分支是死码）⇒ 多租户一开就是"能回退别人会话"的口子。

## 2. 目标态：企业级要的是什么（判据，不是愿望）

| 能力 | 达标判据（可被否掉的说法） |
|---|---|
| 身份 | 一个请求内**只有一套**租户/用户口径：数据面、会话面、审计面取到的是同一个**服务端断言**值；两条反证都要红转绿——① 带**伪造** `tenant_id` 请求 ⇒ 读不到他租户数据；② **不发** `tenant_id`（今天页面的默认行为）⇒ 也不得退化成跨租户全局匹配（尤其语义缓存） |
| 工作空间 | 同一租户内两个空间各放一份文档，A 空间提问 ⇒ `evidence` 里**不出现** B 空间文档；空间有创建/列举/归档动作与生命周期 |
| 跨会话记忆 | 说得出"谁的哪些会话"：能按 user 列会话、能把记忆归因到来源会话，且**默认不跨 user 泄漏** |
| 用户画像 | 存在"随时间演化"的载体：同一事实在第 N 次出现时 `importance` 被更新（有 UPDATE 路径与去重键），能回答"关于这个用户我们知道什么"并给出**证据来源会话** |
| 记忆治理 | 治理结果**被消费**：`governed_memories` 有读取点，且注入 prompt 前有预算与脱敏；Gate 的去重/冲突结论可在 trace 里回读 |

## 3. 迁移策略（五阶段，顺序不可换；每阶段独立可验收）

> 顺序理由见 §0：阶段 1 是其余四项的**共同前置**。跳过它去做画像/多空间，等于把"自选桶"放大成"自选画像"。

- **阶段 1 身份合一（先方案后编码，改动集中在入口层）**
  目标：数据面的 `tenant_id/workspace_id/user_id` 从"客户端可选入参"改为"服务端断言"，与 ADR-0007 对齐。
  **本阶段 = 执行已立案的 `plan-query-tenant-from-client-not-server-asserted-2026-10-10.md`**（那份已把 11 处
  `req.tenant_id`、`subagents/rag.py` 守卫被绕过、`SINGLE_TENANT` 改非 default 即"入库了却检索不到"三件事取证完），
  本文只在其基础上**追加一项它未覆盖的前置**：`user_id` 目前没有任何服务端来源（画像与"按 user 列会话"都卡在这），
  需要与 `tenant_id` 同批改由 ContextVar 注入，否则阶段 3/4 打不开。
  影响面：`query_router.py`（9 处 `req.tenant_id`）、`import_router.py`、`sql_router.py`、`capabilities.py`（工具入参 schema 里
  的 `workspace_id` 要变成"服务端注入"而非"模型/调用方可填"）、`shared-schemas` 的 `QueryRequest`（**契约变更，需先审消费者**：
  联邦网关与 kefu/nl2sql 等子服务都传这两个字段）。
  迁移策略：契约保留字段但**服务端忽略并覆盖**，同时把"被忽略"做成可观测事件（否则调用方静默失效）；
  现网 `identity_mode=single` 下值不变 ⇒ 行为等价，只是把口径从 req 挪到 ContextVar。
  **RAG 侧不用改 SQL**：五处读写已经是 `(tenant_id, workspace_id)` 双谓词（§1.4 ✅），阶段 1 换的是**值的来源**。
  验收：§2"身份"那行的两条反证（伪造 + 缺省）都有用例且**红→绿**；`/health` 报出的身份读数与数据面实际谓词一致（不是两套）。
- **阶段 2 隔离与授权（开多租户的闸门，含三处：两个真 bug + 一个缺维度的表）**
  目标：`/session/revert` 走同一条身份链并做归属判定；`semantic_cache` 空租户不再退化为全局匹配；
  checkpoint 表补 tenant 维度（现在**无 tenant 列**，`/history` 只按 thread_id ⇒ "看起来隔离"）。
  验收：跨租户 revert 返回 403 且 `FORBIDDEN` 分支不再是死码；`cache_lookup` 在 tenant 缺省时**拒绝或按租户分桶**，
  有回归用例；`/history` 谓词含租户。
- **阶段 3 记忆写入质量（让"逐条事实"变成"可演化的事实"）**
  目标：`memory_extraction_enabled` 打开（LLM 抽取 type/importance/scope）+ 去重键 + `UPDATE` 路径（importance 随复现演化）
  + `MEMORY_DUAL_SCOPE` 打开（**必须在阶段 1 之后**，否则 user 行仍落在同一个塌桶上）。
  验收：同一事实问两次 ⇒ 表里是**一行且 importance 变了**，不是两行；`forget` 有端点或明确"不提供"并写进口径。
- **阶段 4 画像与工作空间（能力层，最后做）**
  目标：画像＝按 user 聚合的事实集 + 可读的"为什么知道"（来源会话/时间）；工作空间补生命周期与内容边界
  （SQL 侧已有双谓词，缺的是**值的来源**（阶段 1）与空间管理动作）。
  验收：§2 表里那两句可测的话。
- **阶段 5 治理闭环**
  目标：`governed_memories` 有读取点、`MemoryRetriever` 注入 semantic、`ContextGovernor` 结论进 trace 可回读
  （与观测方案 P2 同一批属性键，见 `plan-observability-target-model-2026-10-14.md` §3）。
  验收：一次请求的 trace 里能指出"哪些记忆被治理丢弃、为什么"。

## 4. 口径表：**阶段 N 之前不得声称**（演示与对外话术都按此答）

| 能力 | 今天（阶段 0）能说到哪 | 不得说 |
|---|---|---|
| 多轮会话 | ✅ 已实证：同一次会话内上下文连续，可回退、可回读历史原文 | 不得说"按句可删/可精确清理"（§1.1 形状） |
| 跨会话 | 只能说"**同一租户桶内的回放**" | 不得说"跨会话用户级记忆" |
| 用户画像 | 无 | **不得出现"画像"二字**（`MEMORY_DUAL_SCOPE` 默认关、无 UPDATE） |
| 工作空间 | 可以说"**隔离槽位与谓词链已预留**，当前恒 default" | 不得说"多租户/多空间隔离已具备"（§1.4 值来自客户端） |
| 记忆治理 | 可以说"有 Gate 与衰减评分" | 不得说"治理后记忆已影响回答"（§1.6 无读取点） |

## 5. 风险与非目标

- **主要代价不在代码在取证**：阶段 1/2 一改，今天所有"已实证"的数据面读数（检索、消融、会话记录、缓存命中）
  都要在新身份模型下**重跑**；`make test` 里断言 `req.tenant_id` 行为的用例与 `shared-schemas` 消费者要一起审。
- **不要在演示前动任何一条**（与观测方案同一纪律）：发布通道一轮 ≈25 分钟，且会新增演示残留。
- 非目标：不自研向量库/不换 pgvector；不做"人格化画像"（那是产品层的事，本平台只负责事实存储与归因）；
  不在本轮引入新的身份框架（沿用 ADR-0007 的 ContextVar + JWT 路线）。
- 待核（本轮未复核，实施前先确认）：`MemoryRetriever` 是否真的没注入 semantic（`main.py:159` ◻）；
  `workspaces` 缺表降级放行的具体分支（`workspace_registry.py:108-113` ◻）；
  episodic 生产读是 `ILIKE` 而非向量（`memory_pg.py:65-75` ◻）——若成立，阶段 3 要顺带定性它算不算"半成品"。
