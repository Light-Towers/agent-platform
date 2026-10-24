# 方案：平台级租户/工作空间身份体系——全景盘点与分批次实施计划（2026-10-18）

> 性质：**方案文档，不含任何代码改动**（本轮唯一先行落地物是 nl2sql 连接池工厂，与本体系弱相关，已在工作区）。
> 触发：用户要求"Agent Platform 整个项目都需要这套租户业务 ID"（不止 nl2sql 一个服务）。
> 定位：本文件**不重复立案**任何技术方案——ADR-0006/0007 与六份 plan 已把设计写全；本文件做三件事：
> ① 把散落状态收敛成**一张可审计的全景矩阵**；② 给出**收敛顺序与批次**（既有文档各自为政，顺序隐含）；③ 列出**必须由用户拍板的决策**。
> 纪律：所有结论带 `文件:行号` 锚点；区分「已实施（代码+测试）/ 待拍板 / 待环境」三种状态，不拿文档状态行当完成。
> **批次归属（2026-10-18 用户口径）**：本计划整体处于 **nl2sql 本期（M0）之外**——nl2sql 侧范围裁定见 `plan-nl2sql-meta-lifecycle-2026-10-17.md` §4.0；本文件 T1（关缓存默认分支）不依赖 nl2sql，按本文件自身顺序推进即可，但**不并进 nl2sql 本期范围**，避免一期两摊。

---

## 0. 结论先行

1. **平台的租户体系已经建了一半，且是难的那一半**：身份内核（RS256+HMAC 内部头+启动守卫）、隔离机制（tenant 谓词链、fail-fast）、身份门 6/6 装配 + P13 门禁、LLM 可填租户通道封堵——全部有代码有测试。缺的是**来源收口、内部传播、四个横切归属面、以及 nl2sql 的租户语义定义**。
2. **当前最危险的不是"某个服务没租户"，是"同一个请求里两套租户口径并存"**：会话/审计面已服务端断言（`tenant-default`），数据面仍读客户端 body（`req.tenant_id`）。10-12 已用 PoC 证实：同一请求 `thread_id=tenant-default` 而缓存落进客户端自报的 `tenant-B`。
3. **比"自报"更优先的是"默认分支失效"**：`semantic_cache` 在 tenant 为空串时走**无 WHERE 全表匹配**（`cache.py:51-61`），而控制台页面**从不发** `tenant_id` ⇒ 现网每次问答都走这条全局匹配分支。这不是攻击面，是默认行为——第二个租户一写进来就串，无需任何人伪造。
4. **nl2sql 是全平台唯一零租户维度的服务**，但它不是最紧急的（它还没有多租户数据）；它的正确定位是 **T2 批次的语义定义样本**（隔离什么：元知识库 / SQL 谓词 / 结果集三层）。
5. **顺序**：先关默认分支（T1，1-2 人日，不依赖任何拍板）→ 再收口来源（T2，含 nl2sql 语义与网关签名头）→ 再补横切归属（T3）→ 才谈得上 user 画像（T4）、fork 收敛与 enforce（T5）。**倒序的代价**：在"调用方自选桶"之上开画像/多空间，得到的是"自选画像"（plan-memory-identity-workspace §0 原判断，本轮复核仍成立）。

---

## 1. 既有工作地图（读完这份再动手，避免重复建设）

| 层 | 状态 | 文档 / 代码锚点 |
|---|---|---|
| 隔离维度契约（tenant=边界 / workspace=归属；D1-D5） | ✅ 已采纳 | `docs/adr/0006-isolation-dimension-contract.md` |
| 服务端断言租户身份（A=JWT / C=内部签名头；分支 A 拍板=活跃 P0） | ✅ 已采纳 | `docs/adr/0007-server-asserted-tenant-identity.md` |
| T9-T13 隔离加固（chunks/sql_* 补 tenant、workspaces 归属表、memories 双 scope、episodic tenant） | ✅ 已实施 | `plan-isolation-hardening-2026-09-27.md` §7；迁移 `006`~`010` |
| A1 追溯审计脚本（只读，五排查点） | ✅ 已产出，**待环境执行** | `scripts/audit_tenant_access.py` |
| A2 LLM 可填租户通道封堵（tool schema 删 tenant_id/user_id + `_sanitize_identity`） | ✅ 已实施 | `plan-tenant-identity-2026-09-27.md` §A2 实施记录 |
| A3 身份内核（RS256 签验 / HMAC 头 / 启动守卫）+ agent_server、federation 接线 | ✅ 已实施 | `packages/agent-runtime/agent_runtime/identity.py`、`identity_middleware.py` |
| A4 内部签名头（软模式，仅 knowledge-service 一路签发） | ✅ 已实施（部分） | `plan-tenant-identity` §A4；`tools/knowledge_tools.py` 附头 |
| 身份门 6/6 装配 + P13 存在性门禁（4 shared / 2 fork） | ✅ 已实施 | `plan-identity-gate-6of6-2026-10-16.md` §8（commit `a2bac21`） |
| 记忆/身份/工作空间五阶段方案 | 📋 方案在册，**阶段 1-5 均未动** | `plan-memory-identity-workspace-2026-10-14.md` |
| `/query` 租户来源收口 + 缓存默认分支 PoC | 📋 **已立案待拍板，未动代码** | `plan-query-tenant-from-client-not-server-asserted-2026-10-10.md` |

⇒ 需要新写的只有**顺序与批次**；设计全部指向上面九份文档。

---

## 2. 全景矩阵：6 服务 × 9 维度

图例：✅ 已实施且可验证 ｜ ⚠️ 部分/有条件 ｜ ❌ 缺失 ｜ 📋 方案在册未动

| 维度 | agent_server | agent_federation | knowledge-service | nl2sql-service | kefu-service | exhibition-agent |
|---|---|---|---|---|---|---|
| **① 身份门装配** | ✅ shared（`main.py` 挂 `IdentityMiddleware`） | ✅ shared（独立头 `X-Tenant-JWT` 桥接自有 ContextVar，`identity_bridge.py`） | ⚠️ fork：`TenantHeaderMiddleware`，开关 `TENANT_HEADER_ENFORCE` | ✅ shared（observe 档，10-16 接入） | ✅ shared（observe 档，10-16 接入） | ⚠️ fork：`X-Execution-Context`，**逐端点调用**，DEV 档 base64 **不验签** |
| **② tenant 来源** | ❌ `/query` 10 处 `req.tenant_id`（数据面=客户端）；其余入口 ✅ `server_tenant_id()` | ✅ 服务端断言（`X-Tenant-JWT`） | ✅ 签名断言 > provided(仅审计) > default | ❌ **零消费**：契约有 `tenant_id` 字段，源码从不读 | ❌ 2 处 `req.tenant_id or "default"`（`__main__.py:73`、`:121`） | ✅ `ctx.tenant_id`，body 自报仅交叉校验→403 |
| **③ 契约层** | ⚠️ `QueryRequest.tenant_id` 可选入参（`shared_schemas/query.py:18`），语义未降级 | — | ⚠️ `tenant_id: Form("")` 曾可空，已改服务端注入 | ⚠️ `SqlQueryRequest(QueryRequest)` 继承字段但零读取 | ⚠️ 同 agent_server 契约 | ⚠️ 自有契约 |
| **④ 存储层 tenant 列** | ✅ chunks/sql_ddl/sql_docs/sql_examples/memories/episodic（迁移 006-010）；❌ checkpoint 三表无 DDL 无 tenant 列 | ❌ Mongo checkpointer 分组带 tenant 但无归属表 | ⚠️ Milvus filter + Mongo 元数据，租户元数据在案 | ❌ **meta 表（列/指标/取值/别名/码表）零租户维度** | ❌ 无自有存储（用 LangGraph thread） | ⚠️ 自有 execution context 存储 |
| **⑤ 谓词链（tenant 成对）** | ✅ RAG 五处读写全双谓词（`rag/store.py:78-179`）；❌ `semantic_cache` 空租户走全表（`cache.py:51-61`） | — | ✅ 写入恒带租户（T11 后） | —（无租户概念故无论词链） | — | ✅ `enforce_scope_filter` 生产实现在位 |
| **⑥ workspace 归属校验** | ✅ `workspaces(tenant_id,id)` 复合 PK + `resolve_workspace`（缺表降级放行） | — | ⚠️ knowledge_id 归属沿用元数据，无独立校验 | ❌ 无 workspace 概念 | ❌ 无 | ⚠️ 有 scope 收窄 |
| **⑦ user 维度** | ⚠️ `MEMORY_DUAL_SCOPE` 默认**关**（`typed.py:149`）；`server_user_id` 管道在、无生产绑定 | 📋 A5 未做 | ❌ 无 user 断言 | ❌ 无 | ❌ 无 | ⚠️ execution context 带 operator |
| **⑧ 横切归属面** | ⚠️ 主链 `execute_plan` 持久化轨迹 ✅（`execution_graph.py:606/624`）但 **tenant_id 落库 ❌**：`TrajectoryRecord.tenant_id` 模型字段在位（`models.py:57`，由 `plan.tenant_id` 填充，仅喂 memory_sink 内存消费），`trajectories` 表无该列（`001_baseline.up.sql:173-184`）、迁移止于 012、`store_pg.py:47-79` INSERT 不含它 ⇒ 按租户查轨迹不可能；❌ `cost_records` 建表+索引但**代码零读写**（§28）；❌ forensic `external_inputs` 三字段**零写入点**（判定 6 已因此下修） | ⚠️ checkpoint_cleaner 按 tenant 分组；❌ **轨迹零持久化**：联邦 agentic 走 `AgenticPlanner.arun`→`_execute_agent_core`（`main_agent.py:523`），不经 `execute_plan` ⇒ `_persist_trajectory` 从不调用；`trajectory_store` 已装配（`planners/__init__.py:54`）但**永不消费**；post_execution_hooks 亦未注入（源码注释自认待 B-3） | ⚠️ 成本按知识库 | ❌ 无 trace 落库 | ❌ 无 | ⚠️ citations 属 skill 返回体 |
| **⑨ 网关→子服务签名头** | ✅ 出站已签（knowledge 一路） | ✅ 签发方 | ✅ 收方（软模式） | ❌ **出站未签，tenant 走 body**（`async_subagents.py:118` payload 字段） | ❌ 同 nl2sql | ❌ 不经网关 |

### 2.1 矩阵读法（三条比格子更重要的事实）

1. **② 列是主矛盾**：6 家里 3 家（agent_server / nl2sql / kefu）tenant 来源仍是客户端；其中 nl2sql 连读都不读。ADR-0007 的"服务端断言"今天只对**会话归属**与**部分入口**成立，对数据面不成立——10-10 方案已逐条取证，本矩阵只是把它平台化。
2. **⑨ 列是隐形断裂**：A4 只给 knowledge-service 一路签发 `X-Internal-Tenant`；nl2sql/kefu 的出站**只把 tenant_id 放 body**（6of6 方案 §1.2 实证"不带任何身份凭据"）。后果：这两家的身份门即使从 observe 翻 enforce，拿到的仍是 body 值 ⇒ **fail-closed 翻了也断不了自报**。T2 必须包含"网关出站带签名头"这一环，否则 A6 是空转。
3. **⑧ 列是"归属计量"缺口**：隔离（谁能看）之外，租户体系还包含"谁花的钱、谁的执行"（判定 6：身份+调用+来源+成本四问，现已下修为部分达标）。三个横切字段载体在位、零写入，属同一族问题（§25/§28 已登记，未闭合）。

---

## 3. 缺口清单（分级；每条带"为什么是这个级"）

### P0（多租户现实风险，默认路径即触发）

| # | 缺口 | 证据锚点 | 为什么 P0 |
|---|---|---|---|
| G1 | `semantic_cache` 空租户 ⇒ 无 WHERE 全表匹配 | `cache.py:51-61`；调用方 `query_router.py:162/313` `req.tenant_id or ""` | **默认行为即跨租户读**：控制台不发 tenant_id ⇒ 现网每次问答走全局匹配；10-12 PoC 已证实串读。修法=10-10 方案选项 D（删 else 分支，空租户无缓存），一条用例可钉 |
| G2 | `/query` 数据面 10 处 `req.tenant_id` | `api/query_router.py`（`grep -c`=10，含工作区解析/调度/预算/缓存/graph state/PlannerContext） | 自选桶 ⇒ 越权读 + 缓存污染 + 配额绕过三合一；10-10 已取证（含 `SINGLE_TENANT` 改非 default 会"入库了却检索不到且不报错"的现场版） |
| G3 | `/session/revert` 不走 `resolve_thread_id`，operator 从不与 thread 归属比对（`FORBIDDEN` 是死码） | `session_router.py:72`、`revert.py:36` | 多租户一开即"能回退别人会话"；身份链已有现成函数，这是**接线缺失**不是能力缺失 |
| G4 | nl2sql 租户语义无定义 | 源码零 `tenant` 命中（server.py:25 注释自认）；meta 表零租户维度 | roadmap §3 第 10 项已挂"待拍板"：不定义隔离什么（元知识/SQL 谓词/结果集）就无法验收；且它即将接 DW/Doris 多源，晚定义成本更高 |
| G5 | 网关→nl2sql/kefu 无签名头，tenant 走 body | `async_subagents.py:118` + `:113-125` headers 仅 Content-Type+traceparent | 见 §2.1 ②：不补这一环，T5 的 fail-closed 对这两家空转 |

### P1（多租户正确性，非默认路径但要先于能力层）

| # | 缺口 | 证据锚点 | 说明 |
|---|---|---|---|
| G6 | kefu 2 处 `req.tenant_id or "default"` | `__main__.py:73`、`:121` | 同 G2 形状，量小；随 T2 一并收 |
| G7 | checkpoint 三表无 tenant 列、无 DDL 入 VCS | `main.py:46-62` → `saver.setup()` 建表，仓库 SQL 无 DDL | `/history` 只按 thread_id ⇒ "看起来隔离"；thread 前缀已是 `tenant-<t>`，要么加列要么把前缀解析升格为显式契约 |
| G8 | 归属计量三缺口：`cost_records` 零读写；`trajectories` 表无 tenant_id 列（主链落库缺）；forensic `external_inputs` 零写入。**本轮新增取证——两条执行链路的轨迹状态不对称**：主链（agent_server `unified.py:91`/`graph.py:153`→`execute_plan`→`_persist_trajectory`）有持久化但 store 层丢 tenant_id；联邦链（`AgenticPlanner.arun`→`_execute_agent_core`，`main_agent.py:523`）**根本不持久化**（不经 `execute_plan`，`_persist_trajectory` 从不调用，hooks 未注入待 B-3）⇒ "每次回答可追溯身份+成本"（判定 6）对联邦链路整段不成立 | `001_baseline.up.sql:256` 建表零写；`001_baseline.up.sql:173-184` 表无 tenant 列；`models.py:57` 模型字段仅内存消费；`execution_graph.py:69-71` 填充点；`agentic.py:125-165` 无持久化调用；`planners/__init__.py:84` 注释自认 B-3 未修 | 判定 6 下修记录；三缺口同族（载体在位≠字段被填），本轮把"轨迹"从单点扩为双链路 scope |
| G9 | `MEMORY_DUAL_SCOPE` 默认关 + `memory_extraction_enabled=False` | `typed.py:149`、`config.py:47` | 画像层事实上不存在（无 UPDATE、无结构化抽取）；**必须在 G2 之后开**，否则 user 行落在同一个塌桶上 |
| G10 | `governed_memories` 无读取点；`MemoryRetriever` 疑似未注入 semantic | `query_router.py:255-277` 仅赋值；`main.py:159`（待核） | 记忆治理"有实现、无装配"；属阶段 5，排在身份后 |

### P2（收敛债/口径债，不阻塞功能但持续产生误判）

| # | 缺口 | 证据锚点 | 说明 |
|---|---|---|---|
| G11 | 两套 fork 门卫未收敛（KS `TenantHeaderMiddleware` / exhibition `X-Execution-Context` DEV 档不验签） | P13 归属表已记在册债 | 收敛改响应形状与开关名 ⇒ 需拍板；**前置**：KS 镜像重建（AGENTS.md §62：线上 `import_router.py` 缺 `resolve_server_tenant` 修复）——租户注入修复在线上没生效，这是比收敛更前的动作 |
| G12 | `QueryRequest.tenant_id` 契约语义未降级 | `shared_schemas/query.py:18` | ~~A5 双读过渡未做~~ ⇒ **2026-10-23 随 D20/D3 改判：过渡期取消（不等即 403）**。本缺口的待办因此从"实施双读"换成"**先审仓外消费方**"——没有缓冲期兜底，这项审计是上线前置而非过渡期作业（消费方=全部 6 服务 + 仓外客户端，**仓外至今未审**）；升 `CONTRACT_VERSION` 仍要做（这是语义变更，不是字段增删）。缺口本身**未闭合**，档位不变 |
| G13 | `skill_loader/app.py` 无租户校验端点 | 6of6 方案 §5.3 | exhibition 内部端点收敛，随 fork 决策 |
| G14 | A1 审计脚本未在目标库执行；A6 enforce 未现网取证 | `scripts/audit_tenant_access.py` 只产出未跑 | 待环境；A1 必须早于新机制上线（否则取证基线被改变） |

---

## 4. 分批次计划（含依赖；工时量级为单人日，非承诺）

```
T0 拍板 ──┬─→ T1 默认分支止血 ─→ T2 来源收口(+nl2sql 语义) ─┬─→ T3 横切归属
          │                                                  ├─→ T4 user/画像
          └──────────────────────────────────────────────────┴─→ T5 fork 收敛+enforce → T6 治理闭环
```

## 4. 统一与解耦的划界（批次的归属判据）

> 触发：用户提出"终态要统一，但复杂功能不能耦合在一起"。这不是新原则，是平台成文原则的复述——
> AGENTS.md §90「架构决策原则（横切关注点全局优先）」三条：**单一实现**（逻辑收敛 kernel，不在各 app 复制）/
> **全局装配**（由构造保证不可漏接，接线散落=反模式）/ **强制门禁**（lint 拦截漂移）。
> Plan-F 的形状即范本：**单 Runtime + 多 Planner**——Runtime 中间件统一，编排/领域各自独立；
> 其 K1 修正（boolean 开关 → Planner 策略接口）是"统一做粗了"的学费：一个开关承载不了三组差异。
> 本计划所有批次按三层划分归属，不属于这三层的条目需单独论证。

| 层 | 统一什么 | 本计划对应项 | 为什么必须在这一层 |
|---|---|---|---|
| **L1 内核统一**（原语/契约/协议） | 身份断言原语（签验/绑定）、隔离谓词语义（fail-fast 契约）、传播协议（`X-Internal-Tenant`）、隔离维度模板（ADR-0006 D3） | T1.1/T1.2（谓词语义）、T2.1–T2.5（来源收口）、T2.4（传播协议）、T5（实现收敛） | 安全边界的可信性不能有六种解释：一家 fail-open 即全局击穿——6/6 装配前的"2/6"正是这个风险形状 |
| **L2 装配分散**（实现唯一+装配点分散+门禁） | `mount_identity_gate` 一个实现、六服务各调一次、P13 存在性门禁 | T5 收敛后归属表全 shared | 统一而不耦合的机制：服务间不互相 import，只依赖 runtime 内核；漏装由 CI 而非自觉保证 |
| **L3 领域独立**（数据/逻辑/降级） | 各服务存储 schema、业务谓词、召回逻辑、降级策略 | T2.3 的 nl2sql meta 谓词、KS 的 Milvus/Mongo 过滤、exhibition 的 scopes/execution context | ADR-0009 判例：两套向量存储并存是**功能选择**不是疏漏；硬统一功能选择 = 把复杂功能耦合在一起 |

**判据（未来每一项"要不要统一"都问这三句）**：
1. 各做一遍会让**安全边界出现解释分歧**吗（一家漏 enforce 就击穿）？⇒ 统一到 L1；
2. 各服务做法不同是**功能选择**吗（Milvus sparse vs pgvector BM25）？⇒ 保持 L3 独立，只统一 L1 契约；
3. 统一它需要把 A 领域概念塞进 B 领域吗（如把 execution context 语义塞进共享身份门）？⇒ 不做整体替换，做"契约统一 + 本地组合"。

**据此修正 D4 的推荐答案**：exhibition **部分收敛**——tenant 断言走 L1 共享原语，`X-Execution-Context` 的 operator/scopes/`enforce_scope_filter` 保留为 exhibition 自有 L3 结构，二者在该服务内部组合而非融合。整体替换（选项 b）违反判据 3。

**据此修正终态表述**（取代"六个服务共用一套身份门实现"这一易被读成耦合的说法）：终态是**一套身份内核（L1）+ 六个装配点（L2）+ 六套领域实现（L3）**。

---

### T0 拍板批（零代码；不拍板则 T2/T4/T5 均无法开工）

| # | 决策 | 我的建议 | 不决定的代价 |
|---|---|---|---|
| D1 | **nl2sql 的"租户隔离"隔离什么**（G4） | 三层全做、分批落地：① meta 语义层（列/指标/取值/别名/码表）按 `(tenant_id, workspace_id)` 隔离，**schema 出生即带两列**（照 `schema_store.py` 形状，边际成本≈零）；② 生成的 SQL 谓词下推（P1-1 已立案，复用 ADR-0006/0007）；③ 结果集不另设（② 已覆盖） | T2 无法验收；meta 表后补列=全库重灌（embedding 维度都可能跟着变） |
| D2 | cache 选项 D 是否独立于来源收口先做（G1） | **先做**。它是默认分支上的 fail-open，与 A/B/C 无依赖；且 10-10 方案自己就是这么建议的 | 现网每天继续走全表匹配分支 |
| D3 | `QueryRequest.tenant_id` 契约变更范围（G12） | ~~双读过渡（信断言、body 仅审计比对），一个版本后 403~~ ⇒ **2026-10-23 用户裁定改为"当场 403"**（见 §9.1 D20：不等即拒，**不承认"静默覆盖/忽略"**——那会让调用方以为自己填的值生效）。~~先审仓外调用方~~ 的**审计本身不撤**，但性质变了：过渡期取消 ⇒ 没有观察期兜底，这一项从"过渡期前置"升为**上线前置**（仓内已审：只有控制台页面与测试，页面不发该字段；**仓外未审**）。字段暂留在契约里仅作比对输入，不是备用身份通道 | ~~契约改一半，新旧口径并存期无限拉长~~ ⇒ 代价换成新的两条：① 仓外若有按老写法填字段的调用方，**首次调用即失败**（原先靠一个版本缓冲，现在没有）；② `T2.5` 的写法必须同步改（已同批改，见该条），否则 §4 内部自相矛盾 |
| D4 | KS/exhibition fork 收敛选项（G11） | KS 先收敛（exhibition 逐端点覆盖另行）；**前置=KS 镜像重建分发** | 「6/6 覆盖」继续是"可审计的一半" |
| D5 | `SINGLE_TENANT` / `DEFAULT_TENANT_ID` / `KNOWLEDGE_DEFAULT_TENANT_ID` 口径统一 | 钉死为同一默认值并在清单/手册明示；多租户部署必须显式配非 default | 10-10 已证：改非 default 即"入库了却检索不到且不报错" |
| D6 | **两条执行链路的轨迹归属**（G8 新增 scope）：① 联邦链路是否补轨迹持久化（现为零，B-3 未修）；② `trajectories` 表补 `tenant_id` 列（主链 store 层丢字段）还是维持白名单"轨迹不带租户" | 两条都补：联邦在 agentic 边界补 `_persist_trajectory` 等价物（B-3 修复的范围，hooks 接入一并做）；`trajectories` 加列（迁移顺延 013 之后，与 nl2sql meta DDL 同批审查），store 写+按租户查。理由：判定 6 的"调用"一问对联邦链路整段不成立，而联邦恰是多租户请求的主入口；白名单"轨迹不带租户"与 memory_sink 已按 tenant fail-fast（`episodic_memory.py:316`）自相矛盾 | 联邦执行永久不可追溯；租户审计能查会话查不到执行；memory_sink 的 tenant 断言与轨迹存储的无租户状态长期不一致 |

### T1 默认分支止血（1-2 人日；不依赖 T0 除 D2）

- **T1.1** cache 空租户 fail-closed（G1）：删 else 分支；用例钉"`tenant_id=''` 不得命中任何行"（10-10 §6 已给判据）。
- **T1.2** `/session/revert` 走 `resolve_thread_id` + operator 与 thread 归属比对，激活 `FORBIDDEN`（G3）。
- **验收**：两条反证各一条红→绿用例；`tests/governance` 不劣化。

### T2 来源收口 + nl2sql 语义落地（5-8 人日；依赖 T0-D1/D3/D5）

- **T2.1** agent_server `/query` 10 处 `req.tenant_id` → `server_tenant_id(settings.default_tenant_id)`，body 与断言不符记 WARNING（10-10 选项 A）。
- **T2.2** kefu 2 处同款收口（G6）。
- **T2.3** nl2sql 租户体系（G4，按 D1）：
  - meta DDL 入 VCS（`(tenant_id, workspace_id)` + 复合索引，照 `schema_store` 形状；幂等迁移编号顺延 013）；
  - 三路召回 + meta CRUD 谓词带 tenant（漏传 fail-fast，抄 `_tenant_gate`）；
  - 契约消费 `request.tenant_id` 的来源从 body 改断言（与 T2.4 联动）；
  - 验收判据（建议）：tenantA 构建的元知识，tenantB 提问召回=0；漏传 tenant 的召回请求直接报错而非静默全量。
- **T2.4** 联邦出站向 nl2sql/kefu 附 `X-Internal-Tenant` 签名头（G5，A4 补完）；观测期软模式（缺头审计不拒）。
- **T2.5** 契约收口（D3，**2026-10-23 随 D3 改判，原写"双读：字段保留、服务端覆盖、不符记审计"**）：字段保留但**只作比对输入**；服务端**不覆盖、不忽略**——与断言值不符 ⇒ **当场 403**。验收即 §5-1 那条伪造反证（断 `status_code==403` 且该请求一行都不落）。
- **验收**：① 伪造 `tenant_id` 请求读不到他租户数据；② 不发 tenant 不退化成全局匹配（缓存+检索两路各一条）；`grep -c "req.tenant_id"` 归零（注释除外）。

### T3 横切归属补齐（5-8 人日；依赖 T2 的可信 tenant；联邦轨迹项另含 B-3 修复范围）

- checkpoint tenant 维度（G7，加列或前缀契约化二选一，随 T3 设计定）；
- `cost_records` 写入点（或按 §28 选项把表与 ADR 表述改"预留未启用"——**必须二选一，不能继续零读写+文档说已支持**）；
- **轨迹双链路**（G8/D6，二选一或全做，随 D6 拍板）：主链 `trajectories` 补 `tenant_id` 列 + `store_pg` 写/查（`list_by_tenant`）；联邦链在 agentic 边界补持久化（B-3 范围，`post_execution_hooks` 接入一并做）——**注意顺序**：联邦补持久化依赖 T2.4 签名头（联邦出站已有，但 agentic 边界的 tenant 取值要先有可信来源），故本项排在 T2 后；
- forensic `external_inputs` 三字段写入点（判定 6 第四问）。
- **验收**：判定 6 四问各取一次写入点证据（"载体在位≠字段被填"的教训来自 §529，本轮不重犯）。

### T4 user 维度与画像（5-8 人日；**必须晚于 T2**）

- `user_id` 作为 JWT claim 同期落地（A5 已定"不再列开放项"）；
- `MEMORY_DUAL_SCOPE=true` 打开 + 存量抽样 pre-flight（T13 §8.4 的两个 SQL 必跑，禁盲目回填）；
- 画像 UPDATE 路径 + 去重键 + `memory_extraction_enabled`（阶段 3）。
- **验收**：同一事实问两次 ⇒ 一行且 importance 变；user 画像跨 workspace 可召回、workspace 语料不互串。

### T5 fork 收敛 + enforce 灰度（5-8 人日 + 待环境；依赖 T2.4 签名头全覆盖）

- KS 镜像重建分发（AGENTS.md §62，**置于收敛之前**）；
- KS 收敛共享实现；exhibition 逐端点收敛（DEV 档不验签的去留随拍板）；
- 灰度顺序不可倒置（ADR-0007 §7.2）：签名头全量上线 → 观测覆盖率 100% 且 ≥7 天无异常 → 翻 `TENANT_JWT_ENFORCE`/`TENANT_HEADER_ENFORCE`；
- A1 审计脚本在目标库执行（**必须在新机制上线前**，否则取证基线被改变——G14）。
- **验收**：无头请求 403；现网按启动留痕行核对档位；审计报告五排查点各有结论。

### T6 治理闭环（3-5 人日）

- `governed_memories` 读取点 + 注入前预算/脱敏；`MemoryRetriever` 注入 semantic（先核 `main.py:159` 待核项）；
- trace 回读"哪些记忆被治理丢弃、为什么"。
- **验收**：一次请求的 trace 能指出治理结论。

---

## 5. 三条总反证（任何批次都不得破坏；演示与对外话术按 plan-memory-identity-workspace §4 口径表执行）

> **2026-10-23 破例改动（经用户分两次显式批准：先批 §5 一处，再批 D3 原文"一样修改"）**：原节题"两条"与实际条数不符——第三条（缺用户反证）此前只写在 §9.6-③，只读本节的人会少防一条。改动三处：① 节题 两条→三条；② 补第 3 条；③ 第 1 条里"**或 403**"的"伪造被忽略"一支划掉，因 D20 裁定"不等 ⇒ 当场 403"已否定"静默忽略"这一形状。
> **同批因 D3 改判而就地改的 §0–§8 行**（共 3 处，全部带 dated 批注、原文用 `~~删除线~~` 留痕不抹）：`§3 G12` 说明列、`§4 D3` 行、`§4 T2.5` 行。**其余 §0–§8 未动。**

1. **伪造反证**：携带合法凭据但 body 自报 `tenant_id=<他人租户>` ⇒ **当场 403**（~~伪造被忽略~~——静默忽略即"覆盖"语义，客户端会以为自己填的值生效，D20 已排除）。
2. **缺省反证**：完全不发 `tenant_id`（控制台默认行为）⇒ 不得退化成跨租户全局匹配（重点盯 `semantic_cache` 与 RAG 召回两条路径）。
3. **缺用户反证**（2026-10-23 由 §9.6-③ 同步入本节）：`conversations` 已有 `(orgA,userA)` 登记的 `thread_id`，`userB` 续聊或调 `/history`/`/session/revert` ⇒ **拒绝**。本条是 D7 三级（租户>用户>空间）落地后的最小可验形态；`conversations` 表落地前它**不可能被满足**，故不得在任何批次合入陈述里宣称"会话按人隔离已具备"（见 §9.8"中间态要标"）。

---

## 6. 明确不做（及理由）

- ❌ 不引入外部 IdP（ADR-0007 已决：RS256 自签起步，验签层隔离）。
- ❌ 不做 workspace 服务端签发令牌（ADR-0006 D4 方案 C 已否决）。
- ❌ 不把 `procedural_memories`/共享知识做成跨租户（ADR-0006 D3 修订：跨租户共享即泄漏+投毒面放大）。
- ❌ 不重命名内核 `user_id` 形参/列（TD-13：用 `scope` 列消歧）。
- ❌ 本轮不动 nl2sql 的 answer 断链、连接池之外的 nl2sql 改造（另案：plan-nl2sql-meta-lifecycle 的 I0 批次）——但 **T2.3 的 meta DDL 与召回谓词是租户体系的一部分，两案在 DDL 顺延编号上要对表**（nl2sql 侧迁移编号建议 013 起，避开 agent-runtime 的 012）。

---

## 7. 与其他文档的关系（防重复立案）

| 问题 | 归口 |
|---|---|
| 隔离维度契约、workspace 归属表、memories 双 scope | ADR-0006 + plan-isolation-hardening（已实施部分）/ T4 未完部分 |
| tenant 来源、令牌体系、内部签名头、fail-closed | ADR-0007 + plan-tenant-identity（A1-A6） |
| `/query` 客户端 tenant、缓存默认分支 PoC | plan-query-tenant-from-client-not-server-asserted-2026-10-10（本文 T1.1/T2.1 即执行它） |
| 身份门 6/6、fork 收敛、nl2sql 租户语义 | plan-identity-gate-6of6-2026-10-16（本文 T2.3/T5 即执行它） |
| 记忆质量/画像/治理五阶段 | plan-memory-identity-workspace-2026-10-14（本文 T4/T6 即执行它） |
| nl2sql meta 生命周期、取值解析、探针 | plan-nl2sql-meta-lifecycle-2026-10-17（与本文共享 T2.3 的 DDL/召回改动面，**实施时需对表**） |

---

## 8. 本方案自身的验收（写完计划怎么知道计划是对的）

1. **矩阵可复现**：任取一格，按锚点能读到代码；读不到即本矩阵该格作废。
2. **批次可反证**：任取一批次删掉其前置（如 T4 早于 T2），应能说出会打破哪条总反证——说不出即该批次排序无依据。
3. **不重复立案**：T1-T6 每一项都能在 §7 表格里找到归口；找不到即它是本方案新创的，需单独论证。

---

## 9. 2026-10-23 拍板更新（隔离粒度取证轮 → D7–D13 用户拍板 + D15–D23 分级定档 + 五处更正；第二/三轮见 9.11/9.12）

> **依据**：AGENTS.md §129「所有代码优化/重构必须先制定方案……方案需包含目标、影响面、迁移策略、验收标准，并在文档/issue 中记录」。本节即该记录的落点，**就地扩写本文件、不另立案由**（§7 的"防重复立案"原则）。
> **纪律**：本轮全程只读取证；本节只**追加**，未改动 §0–§8 的任何判定行与头部状态行（台账单写者）。所有锚点按 rev `b0da729` 复取。
> **命名撞车提示**：§4 有两个 `## 4.`（"分批次计划"与"统一与解耦的划界"），本节按 T/D/G 编号引用时以**编号**为准、不以节号为准。

### 9.1 决策表（D7–D13 由用户拍板；D15–D19/D21–D23 标 `·AI默认` 者由本轮按 D0/D1 判据自行定档、**可推翻**；标 ⚠ 者**反转**本文件既有建议）

| # | 决策 | 结论（未标记者=用户拍板；`·AI默认` 者=本轮按 D0/D1 自定，可推翻） | 与本文件原建议的关系 |
|---|---|---|---|
| **D7** ⚠ | **workspace 的归属层级** | `租户 > 用户 > 工作空间` 三级；**workspace 严格属用户，不跨用户共享** | 反转 ADR-0006 D2「workspace 是客户端传入的归属维度」与 ARCHITECTURE.md:158 同一句复述 ⇒ 见 9.5/9.9 |
| **D8** ⚠ | **G4/D1「nl2sql 隔离什么」的答案** | 元数据（列/指标/取值/别名/范例）**全企业同一套，不随空间因人而异** ⇒ 走"共享行 + 摘掉自然键里的 `workspace_id`（摘键留列作溯源）"，**不是** D1 推荐的"按 `(tenant_id, workspace_id)` 隔离、每空间一份" | 直接反转 D1 的 ①；D1 的 ②（SQL 谓词下推）不受影响，仍按原样排 T2 |
| **D9** | 一人只属一个企业 | `users.org_id` 直挂，**不建 `memberships`**；角色降为 `is_admin` | 新增。反转代价小（将来加 `memberships` + 从 `users.org_id` 回填 = 纯 expand） |
| **D10** | 用户体系数量 | **一个**，表进 `agent-runtime` 迁移链。取"共享 claim、不共享存储"形状 ⇒ 下游只验签消费 ⇒ `knowledge-service` **无需**新增 `agent-runtime` 依赖 | 新增，补 T0 空白 |
| **D11** ⚠ | G7 的二选一（加列 vs 前缀契约化） | **都不选**，走第三条：旁置 `conversations` 归属表 + `thread_id` 转不透明 uuid | 新增选项 C 并选定；原二选一均否决，理由见 9.4 |
| **D12** | 行级安全（RLS） | **先不上**；走"仓储收口 + lint 拦裸 SQL" | 新增。RLS 结构上只能覆盖 PG 一侧（`checkpoints` 表由 `saver.setup()` 外部建、`main.py:59`；KS 在 Milvus） |
| **D13** | 砍掉清单 | 归档 / 分享链接 / 草稿持久化 / `client_ref` / `grants` / 元数据 overlay / 空间级 `allowed_tables` / 一人多企业 / RLS —— **对应列一并删，不留空壳** | 补 §6"明确不做"，七项新增 |
| **D20** ⚠ | 身份**怎么送**（(a) body 必填 vs (b) 凭据携带） | **选 (b)**：租户/用户以凭据（JWT claim / 签名头）携带，服务端断言；body 里的 `tenant_id`/`user_id` **降为可选**，一旦携带就必须与断言值等值，**不等 ⇒ 当场 403**（用户 2026-10-23 裁定，**推翻** §4 第 138 行 D3 的"双读过渡、一个版本后 403"） | 反转 D20 之前的默认（"body 必填即合规"）；并把 `capabilities.py:16-17` `_sanitize_identity` 的"**覆盖**"语义排除在 HTTP 入口之外——覆盖会让客户端误以为自己填的值生效。D3 被推翻后**过渡期不存在** ⇒ D3 里"先审仓外调用方"从"过渡期前置"变成**上线前置**（无观察期兜底，填错的调用方直接吃 403）。后果清单见 9.11-① |
| **D15** ·AI默认 | A1 越权审计要不要抢在 T1 前跑 | **不抢跑**。D17/A1 的先后只影响**增量证据**，不构成推迟 T1 的理由 | 外部评审 N-3 提出的"矛盾"经复看非矛盾；代价是 T1 前那段窗口的增量串访证据永久不可取（§9.10 的 A1 增量维度因此在 T1 后不可取） |
| **D16** ·AI默认 | `budget_usage`/`budget_limits`/`cost_records` 的配额维度是否下到自然人 | **维持 org 级聚合，不加 user 列**。判据 = D13 已裁画像/配额的用户级细化，本条不属"先做核心能力" | 与 `001_baseline:239-246` 现 PK `(tenant_id, dimension, bucket_index)` 相容（评审 N-4 把它读成 2 列，实为 3 列）。**注意本条不对称**：将来翻成人级要改 PK，属"成本随时间上升"那类，翻之前须重开 |
| **D17** ·已由 D20 关闭 | 写侧遇空租户的策略（跳过 vs fail-fast） | **不再是决策**：(b) 之下六个空租户场景全部变上游 401/403，缓存侧只剩理论上不可达的纵深防御；纵深防御形态按 §9.11-②（跳过 + 独立计数 + WARNING，断言在同步入口） | **理由要更正（结论不变）**：本行原写"`except Exception` 会吞 ⇒ 测不到"作为拒绝 fail-fast 的理由，**被自己的落点设计消解了**——§9.11-②(i) 规定断言必须在 `try` 之前/同步入口，那个位置 fail-fast 是可测的。成立的理由是另两条：① 缓存是优化不是正确性依赖（`cache.py` docstring 自认）；② `cache_store` 在 `query_router.py:318` 被调时答案已在流式返回，抛出会把一次已成功的回答打成失败。**对方复评判我"答的是 fail-fast"系记错**——本行一直是跳过 |
| **D18** ·AI默认 | workspace 注册入口：显式端点 vs "首次引用即注册且归属当前断言 user" | **后者**：保留 `resolve_workspace`（`:118-133`）的自动注册，但 owner 绑服务端断言 user；**不做**独立管理页/端点 | 前提是把 `:164-169/:190-191` 的 `42P01` fail-open 翻成 fail-closed（§9.7-②），否则"自动注册"与"静默共用一个桶"在同一段代码里并存 |
| **D19** ·AI默认 | 不可逆迁移的 down 纪律 | **空 `.down.sql` + 文件头登记不可逆理由**，不强制成对可执行 | 已有先例：`001_baseline` 本就**没有** `.down.sql`（评审"001–012 全部成对"经复看为不确）。措辞要点：登记的是"有意不提供回退"，不是"尚未编写"——后者会被下一个人当 TODO 补掉 |
| **D21** ·AI默认 | #133 联邦 L2 无租户谓词的出口（A 声明 silo / B 补过滤） | **A**：显式声明"联邦 = 一部署一租户，L2 无租户谓词属设计意图" + docstring + 断言 + 口径行 | B 的前提是**请求级**身份先进联邦（今天只有进程级 `TENANT_ID`，`config.py:35`）⇒ 属 P-2 落地之后的批，不是本批的取舍 |
| **D22** ·AI默认 | ADR-0006 §D2 被 D7 反转后，supersede 的时机 | **随第一个落地批改**，§9.9 已留触发条件；不静默改、不新开 ADR（§7 防重复立案） | 评审 N-8 关于"口令轮换无机制"的 overstated 部分已驳回：`load_public_keys` kid map + `verify_token` 拒旧 kid 即轮换面已存在 |
| **D23** ·AI默认 | P-2 issuer 落哪个进程 | **agent_server 自签**（RS256 + kid 轮换复用现成 `load_public_keys`/`verify_token`），下游只验签消费 | 与 D10"一个用户体系、表进 runtime 链"相容：表与内核在 runtime，签发点在 app。**待办但不属本条**：`Authorization` 进 `/query` 契约会影响下游消费者 ⇒ 按 AGENTS.md 边界条须先审计消费者再另行拍施工批 |


### 9.2 对既有 G/T 契约行的五处更正（按 rev `b0da729` 复取；第四处于 2026-10-23 由 D20 裁定引出；第五处于同日由第三轮评审补网——批次表 T2.5 行与 D3 同源、同被 D20 推翻，此前漏登记）

| 项 | 原述 | 更正 | 影响 |
|---|---|---|---|
| **G4** | "meta 表零租户维度"，锚点 `server.py:25` 注释 | **在当前 rev 作废**：`001_meta_schema.up.sql` 由 `ce312b24`（2026-10-18，与本 plan 同日）加入，8 处 `UNIQUE` 均含 `(tenant_id, workspace_id, …)`，召回谓词实测带三列（`meta_repository.py:155/167`）；`git grep tenant -- nl2sql_service/server.py` 命中 0（该文件存在性本次未单独确认） | "零维度"不再是 T2.3 的前提；**真正待做的是 D8 的反向动作——摘键**，而非加列 |
| **G2** | "10 处 `req.tenant_id`（`grep -c`=10）" | 数字对，但口径要分：`git grep -c` = 10，其中 **`:50` 是注释行** ⇒ 可改代码站点 **9 处**（`:53 :95 :109 :163 :238 :265 :274 :318 :364`） | T2.1 的验收"`grep -c` 归零（注释除外）"本来就写对了，无需改；仅提醒引用者勿把 10 当代码站点数 |
| **§6 末条** | "nl2sql 侧迁移编号建议 013 起，避开 agent-runtime 的 012" | **与实际计数不符**：nl2sql 链实有 001–005 连续 ⇒ 下一号 **006**；013 是 **agent-runtime** 链的下一号（现有至 012） | 见 9.5 的两链编号分配表——否则文档里出现两个"013"，引用即歧义 |
| **§4-D3**（`:138`，T0 拍板批） | "`QueryRequest.tenant_id` 契约变更范围：双读过渡（信断言、body 仅审计比对），**一个版本后 403**；先审仓外调用方" | **被 D20 推翻**（用户 2026-10-23 裁定"当场拒绝"）。**原文已就地改**（批准路径：先批 §5 一处，再答"D3 原文 一样修改"），改法 = 删除线留原文 + dated 批注，不抹历史 | 连带改了同族两处：`§3 G12` 说明列（"双读过渡未做"→"过渡已取消，待办换成先审仓外"）、`§4 T2.5`（"服务端覆盖、不符记审计"→"不覆盖不忽略、不符即 403"）。⇒ D3 原第 3 句"先审仓外调用方"从"过渡期前置"升为**上线前置**；§9.6-② 判据同步升级为"断 403 且零落库" |
| **§4-T2.5**（`:159`，批次表） | "T2.5 契约双读（D3）：字段保留、服务端覆盖、不符记审计" | **同被 D20 推翻**（2026-10-23 第三轮评审指出该行漏出 :138 的更正网）：批次表是施工者直接照做的指令层，"服务端覆盖 + 不符记审计"与 D20"不等 ⇒ 当场 403、`_sanitize_identity` 的覆盖语义被排除在 HTTP 入口之外"直接矛盾 ⇒ 按 :159 施工即违反 D20。**本行未就地改**（同上，§4 未获批破例），此处作 dated 记录；正确施工口径 = 字段保留为可选自述、携带即须与断言等值、不等当场 403 | 连带效果：T2.5 的验收判据不再是"审计里有 WARN 记录"，而是 §5-① 伪造反证（当场 403）；与待拍板⑤合并裁决（:138/:159 两行要不要一并就地改） |

### 9.3 目标（AGENTS.md §129 要素一）

把隔离粒度从当前的**「租户级、且租户值在 HTTP 入口由客户端自报」**提升到**「`(org, user, workspace)` 三元作用域、全部由服务端断言」**，并使"同租户内多自然人"这一已确认的业务现实（D7）在存储、缓存、会话、审计四面都可归因。

### 9.4 影响面（要素二）

- **新增对象**：`organizations`/`users`（runtime 链）、`conversations`（runtime 链）、`workspaces` 加 `owner_user_id`+`visibility` 并改 PK。
- **改谓词/改来源**：`/query` 9 处入口取值（G2）、`semantic_cache`（G1）、`resolve_workspace`/`assert_workspace_access` 签名、nl2sql 8 处 `UNIQUE`（G4/D8）。
- **导入写侧的归属（2026-10-23 补，此前 §9.4 漏项）**：`/import`（KS 侧）与 nl2sql 的元知识构建面今天**只断言租户、无人认领到 user/workspace**。D7 之后"新导入的文档算谁的"必须有答案，否则导入就是"客户端自报 workspace_id ⇒ 谁先引用谁认领"的第二现场（与 §9.7-① 的哨兵坑同族）。**已由用户裁定**：先建 租户/企业/用户，**导入的数据归属该创建用户** ⇒ 落点 = 导入写侧要取服务端断言的 `(org,user,workspace)` 三元组而非请求体值；`chunks` 需补 user 维（当前无 user 列）。执行前置与"老数据删了重灌"同批，见 **9.8.1**（013 前三张表还不存在，"先创建"今天是 SQL 手插）。
- **退役**：`resolve_thread_identity` + `THREAD_ID_PREFIX`（`guardrails/auth.py:43/56-84`）连同 `scripts/migrate_thread_identity.py`、`tests/governance/test_auth.py`、`test_thread_identity_migration.py`。**不留兼容壳**。
- **选项 C 的否决理由（D11）**：A（加列到 `checkpoints`）不可行——表由 `saver.setup()` 外部建（`main.py:59`）、`INSERT` 由 LangGraph 持有，新列只能靠默认值/触发器，而触发器取"当前身份"的唯一通道是 `set_config` GUC，等于把 D12 刚推掉的连接池改造请回来；且 checkpointer 是三分支可插拔（`memory/__init__.py:70-82`，Mongo 分支标"生产推荐"），绑 PG 表 = 钉死一条刻意解耦的路径。B（前缀契约化）撞 `_PRINCIPAL_RE` ≤64（`guardrails/auth.py:50`）vs workspace id ≤128（`workspace_registry.py:103-104`）⇒ `tenant-<t>-<u>-<ws>` 拼接天然非法。
- **顺带闭合的已登记缺陷**：G3（`/session/revert` 跨用户回退未禁、`FORBIDDEN` 死码，README.md:58）由 `conversations` 归属断言覆盖——T1.2 的修法可升格为"同一张归属表 + 同一处断言"，不必各写一遍。

### 9.5 迁移策略（要素三）

| 链 | 现最大号 | 新号 | 内容 |
|---|---|---|---|
| `agent-runtime` | 012 | **013** | `organizations` / `users` / `conversations`（`user_id` **先可空**） |
| `agent-runtime` | — | **014** | `workspaces` 改 PK `(org_id, id)` + `owner_user_id` + `visibility`；`conversations ALTER COLUMN user_id SET NOT NULL` |
| `agent-runtime` | — | **015** | `trajectories` 补 `org_id`/`user_id`（D6/§91 同题） |
| `nl2sql-service` | 005 | **006** | 8 处 `UNIQUE` 摘掉 `workspace_id`（**留列**作溯源） |

三条硬纪律：① **不回改已应用文件**（checksum 钉住，`012_receipt_generation_fencing.up.sql:19-20` 原文），新库与升级库形状必须一致（`011` 登记的分叉教训）；② 改唯一键复用 `005` 的 DO 块配方，**按 `pg_constraint` 实际列集合判等**、不判约束名是否存在（`005:20-36` 原文警告）；③ **005 那条"键变宽不破坏存量 ⇒ 无数据迁移"不可照抄**——摘列是变窄，原本合法的多行会瞬间重复 ⇒ `ADD CONSTRAINT` 直接失败。故 `006` 须带"先查重、有重复即报错退出"前置，**不许自选留存**。⇒ 这条决定了 **006 的排期要早**：今天所有行 `workspace_id` 同值 ⇒ 摘键零冲突；等人数进来，就变成"30 份可能已漂移的注释选哪份"的人工裁决。

批次对齐：`G1+G2` → T1.1/T2.1（不变，**不等 D7–D13**）；`D10` 的表 → T2 前置；`conversations` → T3 内新增项；`D8` 的摘键 → 新批次，与 T2.3 同号段但对撞 D1 原建议，**须先改 D1 再施工**；`MEMORY_DUAL_SCOPE` 翻开仍在 T4（G9 的顺序约束"必须晚于 G2"继续成立）。

### 9.6 验收标准（要素四；隔离类用例一律挂 `requires_pg`，禁 `InMemorySaver`/`_FakeRecord`）

1. ~~缺省反证（§5-2 的具体化）：`semantic_cache` 空/漏传租户 ⇒ `pytest.raises`，不得命中任何行。~~ **本条在 rev `b0da729` 不可实现，已由 §9.11-② 替换**：`cache_lookup` 的 `except Exception`（`cache.py:69-70`）会把任何 raise 吞成"降级为未命中"，`cache_store` 的 `_guarded`（`:105-106`）同理 ⇒ 断言落在 `try` 内或 `spawn_background` 之后，就永远测不到"抛"。
2. 伪造反证（§5-1）：合法凭据 + body 自报他租户 ⇒ ~~落在断言租户~~ **当场 403**（D20 裁定后本条判据由"值仍正确"升级为"请求被拒"；反证写法 = 断 `status_code==403` 且**该请求一行都不落**）。
3. **第三条总反证——缺用户反证**：`conversations` 已有 `(orgA,userA)` 登记的 `thread_id`，`userB` 续聊或 `/history`/`/session/revert` ⇒ 拒绝。（**已于 2026-10-23 同步进 §5-3**，经用户批准破例改 §5 节题；本条保留作实现细节，引用以 §5 为准。）
4. round-trip：写线程后 `SELECT` 读回 `org_id/workspace_id(/user_id)` 与请求作用域等值（打"填了但静默丢"，G8 同族）。
5. 抢注与并发双写：单语句 `ON CONFLICT (thread_id) DO UPDATE … WHERE 归属匹配 RETURNING 1`，**返回 0 行 ⇒ 拒绝**；禁止"先 SELECT 判断再 INSERT"（TOCTOU）。
6. 空会话语义：打开不发言 ⇒ 零请求零行，且**不存在** `POST /conversations` 端点。
7. 包装器接口面：与真实 saver 的公开属性差集为空。
8. 反证（非空转）：注掉归属断言 ⇒ 第 3/5 条必红。按 `docs/operations/evidence-format.md` 的字段与分档写。

### 9.7 四个实现陷阱（评审必须逐条拍住，都是本轮实测出来的）

1. **`'default'` 字面已名花**：既是今天的"全租户共享桶"（PG 侧 `'default'`，`schemas.py:87`/`002:4`/`008:15`），又将用作"每人的默认空间名"；且 nl2sql 侧的"未指定"是**空串**（`tenant_scope.py:46-47`）——两套约定并存。新默认空间 id 必须与两者字面可分；**禁止用哨兵 id 表示公共空间**（`resolve_workspace` 是"谁先引用谁认领"，`:118-133` ⇒ 哨兵会被第一个用户注册成自己的）。
2. **fail-open 要翻成 fail-closed**：表缺失即放行（`workspace_registry.py:164-169/190-191`）+ 调用点吞异常（`query_router.py:51-55`）。空间归属从"加固层"升为"正确性依赖"后，静默放行 = 全员共用一个桶。
3. **会话生命周期三语义**（写进实现，别只写进代码）：① 首条有内容的消息即创建（服务端不得提供"先建后写"端点）；② "新建"的唯一信号 = 请求不带 `session_id`，新 id 经现成 SSE `done` 帧回传（`query_router.py:329/336`，**`QueryResponse` 无需加字段**——它今天没有会话位，`shared_schemas/query.py:40-49`）；③ 未发言的界面状态不持久化（草稿明确不做）。天然可行性已验：写线程唯一入口有 `not answer ⇒ return` 前置（`thread_persist.py:78-80`）。
4. **前端不回传就静默退化**：`console.html:201` 现在把 `session_id` 写死成字面量 `"console"`、`:323` 只把 `thread_id` 显示出来 ⇒ 改造后必须改成"存服务端发的 id 并在下一轮带上"，否则表现为"每次都新开会话"。同时 `:317` 的 `history?session_id=console` 要同步。

### 9.8 对外口径与不可逆点

| 口径 | 内容 |
|---|---|
| **分区 ≠ 隔离** | `workspace` 在服务端断言落地前是"值可自报 ⇒ 是分区不是隔离"（`tenant_scope.py:19-24`、ADR-0007:117 同口径）。改造完成前对外表述必须保持这一措辞 |
| **行级隔离不承诺** | 问数四层中 workspace 只管 L1（知识可见集）与 L2（多轮状态）；**L3 一部署一 DSN 一池**（`dependencies.py:78-92`）、**L4 原样执行、仅 `SET LOCAL` 只读**（`dw_repository.py:22-38`，docstring 自认"第一道防线永远是账号 `GRANT SELECT ONLY`"）⇒ 出口在源库分账号/建租户视图，属跨团队申请 |
| **中间态要标** | `conversations.user_id` 在 014 前可空 ⇒ 读侧断言只到 org 级，不得写成"会话按人隔离已具备"（"接线 ≠ 启用"） |
| ~~不可逆 ①~~ **已降级（不再是不可逆点）** | 原判定"旧 `tenant-default` 线程的**归属永久无从重建**（`/import` 只断言租户、`chunks` 无 user 列）⇒ 处置只有不进新列表/不再可写/数据保留不删"。**2026-10-23 用户给出更干脆的出口：老数据删了重灌**（先建 租户/企业/用户，导入的数据算创建者的）⇒ 归属问题从"无从重建"变成"**不必重建**"。但**只对"有源"那一半成立**，处置明细与三条前置见 **9.8.1** |
| 不可逆 ②（**仍成立**） | `resolve_thread_identity` 删除后旧格式 thread 值不再生成 ⇒ 老数据可寻址性取决于是否留 legacy 读取通道；**建议不留，并明确否决"按 org 全量可读"**（那等于把刚定掉的会话互串写成长期特性）。**① 的"删了重灌"出口不消解本条**——重灌解决的是语料归属，不解决旧会话 checkpoint 的可寻址性；与 `DEPLOY_ENFORCE_IDENTITY` 灰度同批拍，不留兼容壳 |

### 9.8.1 老数据处置（由 ① 降级引出，2026-10-23）

**"删了重灌"这句话对三类数据的含义不同，不许混着说**：

| 类别 | 表 | 删后能否重灌 | 说明 |
|---|---|---|---|
| **有源** | `chunks`、nl2sql 8 张 meta 表 | ✅ 能 | 源文件仍在，重跑入库即重建 ⇒ 用户的方案对这类完全成立 |
| **无源** | LangGraph `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`、`memories` | ❌ **不能** | 对话历史是运行时产生的，没有"源"可再导入 ⇒ 对这类，"删了重灌"实际语义是**归零**（控制台历史面板清空） |
| **可丢** | `semantic_cache` | ✅ 删了无所谓 | 缓存是优化不是正确性依赖（`cache.py` docstring 自认） |

三条前置（缺一即不可执行）：① **建实体的入口先于导入**——013 之前 `organizations`/`users` 三张表**还不存在**，"自己先创建租户/企业/用户"今天只能执行成**用 SQL 手插一行**（够用于内部演示期，别把它读成已有创建入口；是否补管理端点属 D18 同族，本条不擅自扩）；② 现网删除走 `docs/operations/live-db-destructive-write-recipe.md` 的四步配方（备份→删→复验→声明"复验即污染"），`checkpoints` **无法按句删、只能整桶**且备份只能整桶还原；③ 本条**不是待执行项而是待授权项**——内网 126/241 通道今天不可达（本机 TUN 代理接管，读数一律标"未获取"），且属破坏性写，须单独批准。

### 9.9 文档改动面（本节之外还要动的地方）

**被 D7 推翻、必须改写结论句**：ADR-0006 §D2（`:75-78`，含 `:125` 的否决理由）；ARCHITECTURE.md `:158`、`:69`（"用户级细化仍待 A5"）、§2.3 三层表 `:57-67`；README.md `:50`；`tenant_scope.py:19-24` 与 `workspace_registry.py:4-18`、`typed.py:116-135`、`identity_middleware.py:13-16` 四段 **docstring 承诺**（最易漏，因无人当文档看）。
**待修订而非静默改**：ADR-0006 D2 的 supersede 建议**在 T/批次合入时发生**，当前只在本节留一行触发条件；不新开 ADR（§7 防重复立案）。
**要改档位**：`capability-map:164/237/408`；`.env.example:7-11`；`k8s manifest:40`（"本版单租户不暴露该问题"前提失效，且它预告的源库只读角色正是 9.8 L4 的跨团队前置）；`minimal-release-runbook.md:219` 的 S1 fail-closed 判据需重验。
**两处门禁查不到**：① `check_doc_sync.py` 只查路径存在性与命令/session 数一致性（`:7-12`），**语义反转不会报红**；② 能力图 `:237` 写"挂载 `main.py:571`"而实测在 `:707` ⇒ 改文档时"路径"与"锚点"要分两层核。
**新门禁位（补 §5/§6 的缺口）**：入口路由出现 `req.tenant_id`/`req.user_id` 而该文件未 import 服务端取值点 ⇒ 红（本轮查出的真空：`test_identity_not_in_tool_schema.py:15` 明文把 `QueryRequest.tenant_id` 排除在射程外）；P13 加第二判据"装配点存在 ≠ 断言被消费"；`conversations` 的 SQL 只允许出现在包装器模块内。

### 9.10 本节仍未取到的证据（五档口径见 `docs/operations/unconfirmed-items.md:8`）

**待环境**：现网五个身份类 env 的**生效值**（仅拿到清单声明值 `SINGLE_TENANT=default`/`DEPLOY_ENFORCE_IDENTITY=true`，而 AGENTS.md 内网第 5 条正是"清单与现网字面分叉"前例；ADR-0008:54 那条"任一生产清单未置 true ⇒ U1 必改选 A/B"的复审条件因此仍悬）；`semantic_cache` 真库跨租户命中面；`MEMORY_DUAL_SCOPE` 翻开前的 008 回填抽样（plan-isolation-hardening `:221` 自登记未执行）。
**待放行**：任何 pytest（含上述反证用例）。
**待拍板（2026-10-23 第三轮后**只剩四项**）**：
① 本节 §9 提交与推送的**授权**（提交可逆、推是共享历史；本仓规则要求合入 main 显式批示，推 feat 同批征询）；
② 跑一次 `requires_pg` 目标用例的**授权**（用户此前中止过 CI 等价 pytest ⇒ 记为持续约束，不默认执行）；
③ **006 摘键本轮排不排**（唯一"越拖越贵"项，属花不花人日的 whether 决策，非技术判断）；
④ 9.8 那两句**对外口径**能不能说（担责面）。
> **本轮已裁、不再占位**：D20 的 403 节奏 = **当场拒绝**（推翻 D3 过渡期 ⇒ "先审仓外调用方"升为上线前置）；~~`§4:138` D3 与 `§4:159` T2.5 要不要就地改~~ **已批准并已就地改**——且改前两行时做了一次 §0–§8 全量扫描，又扫出**第三处同族矛盾 `§3:92` G12**（"A5 双读过渡未做"），若只按批准字面改两行就会留这处 ⇒ 实际改了三行，连 §5 的三处改动合计 **§0–§8 内六处**，全部带删除线与 dated 批注（清单见 §5 批注段）；老数据处置 = **删了重灌**（① 号不可逆点降级，三类分法见 9.8.1）；导入写侧归属 = **归创建该批数据的用户**（§9.4 补项）；D15/D16/D17/D18/D19/D21/D22/D23 属 **D0/D1**，已按判据自定并标 `·AI默认`，**用户可直接推翻任一行**。
**他人负责**：问数行级隔离的源库账号方案（BI/DBA）。
**口径未定**：`rag/store.py:158-159`"隔离双维"与 `tenant_scope.py:19-24`"不是隔离维"两处文字仍相反——按 D7 应把前者第二维改写为 owner，不是裸 id。

### 9.11 第二轮追加（D20 落地 → P-1 收窄 → 顺带查出一处更硬的缓存面）

> 全部锚点按 rev `b0da729` 复取；本节仍只追加，§0–§8 一字未动。

**① D20=(b) 的六个后果**（身份走凭据，不走 body）

| 面 | 变化 | 站点 |
|---|---|---|
| 契约 | `tenant_id`/`user_id` 由"必填身份"降为**可选自述**；携带即须与断言值等值 | `shared_schemas/query.py:18/28` |
| 入口 | 不等 ⇒ **403 拒绝**（不是覆盖、不是忽略）；缺凭据 ⇒ 401 | 新增断言点，取代 `_sanitize_identity` 在入口的等价物 |
| 缓存读写 | 两处 `req.tenant_id or ""` → 服务端断言租户，且 `or ""` 这个兜底本身要消失 | `query_router.py:163`（读）`:318`（写） |
| 下游传播 | body 删身份，改签名头（HMAC / `X-Internal-Tenant` 那条链） | G15 的 3 处 propagation（`control_plane`/`execution_recovery`/`execution_scheduler` 收 `ExecutionRequest`，属传播非来源） |
| 前端 | `console.html` 要带 token 而非带字段；`session_id` 硬编码 `"console"` 一并解决 | `console.html:201`（body）、`:317`（history）、`:323`（展示） |
| 取证脚本 | 同上——现在的 body 里没有身份位 | `deploy/observability/langfuse_proof.py:105` |

**② P-1 收窄（由此 D20 关掉上一轮"待拍板"里的 P-1）**

上一轮列的六个"写侧遇到空租户"场景，在 (b) 下**全部变成上游 401/403**，进不到 `cache_store`。缓存侧只剩一条理论上不可达的纵深防御。⇒ 纵深防御要保留，但**它的判据不能是"抛异常"**：`cache_lookup` 的 `except Exception`（`cache.py:69-70`）把任何 raise 吞成"降级为未命中"，`cache_store` 的 `_guarded` 同形（`:105-106`）——断言写在 `try`（`:62`）内 = 测不到；写在 `_cache_write` 内 = 被吞。
**替代 §9.6-① 的两条可实现判据**：
- (i) 断言落点由实现规定：`cache_lookup` 里必须在 `:62` 的 `try` **之前**；`cache_store` 里必须在**同步入口**（`spawn_background` 之前），不得下沉到 `_cache_write`。
- (ii) 行为断言改判"结果"而非"异常"：空租户 ⇒ **一次 SQL 都不发**（`pool.connection` 调用计数 = 0）且 `get_stats()["miss"]` 不增长；写侧空租户 ⇒ `semantic_cache` 表**行数不变**（打"填了但静默丢"同族，G8）。

**③ 新发现（比 PG 那个洞更硬，此前不在任何台账）**

联邦 L2 语义缓存**没有租户谓词**：命中走向量近邻，查询串是 `Query("(*)=>[KNN 1 @query_vec $vec AS score]")`（`layers.py:169`）——`(*)` 匹配索引内全部文档、无 filter；写入的 hash mapping 只有 `query_text/intent/value_json/query_vec` 四个字段（`:209-214`），**租户根本没进 L2**。`tenant_id` 只参与 `build_cache_key`，而 L2 命中从不看 key。
今天不出事的唯一理由：`config.py:35` 的 `TENANT_ID` 是**进程级 env** ⇒ 一部署一租户（silo），不是行过滤。⇒ 这是"分区 ≠ 隔离"口径（9.8 第一条）的第二个实例，且形状更糟：PG 侧漏在"租户为空时"，联邦侧是**无条件不筛**。
~~待拍板~~ → **已按 D21 定 A**（显式声明 silo + docstring + 断言 + 口径行）；B 的前提是请求级身份先进联邦，属 P-2/D23 落地后的批。不写下来，下一个读代码的人会以为 L2 有隔离。⇒ **已立案 #133**（issue 内 A/B 两项按本档勾 A）。

**④ 两套语义缓存的处置**

两套的消费者**完全不相交**（各 2 站点，`git grep` 复核）：`agent_runtime/cache.py` ← `query_router.py:163/318`（PG+pgvector）；`agent_federation/agent/cache/*` ← `main_agent.py:484/534`（Valkey）。
来历：`refactor-plan.md:230` 那轮设计新建 L1/L2/L3 + `docker-compose` 加 valkey（`:231` 列新文件）；TB-4/M5 想统一，**收敛只停在 key 与统计接口**——`agent_core/cache/base.py:4-7` 原文"双轨各自实现该协议，但**不跨后端共享缓存数据**（向量空间/存储引擎不一致，现状保留）"。按 AGENTS.md 三层判据：**单一实现做了半层，全局装配 + 强制门禁两层为空** ⇒ "看起来已收敛、其实没有"。
能力差集（不是重复代码）：PG 侧无精确命中（`cache.py:8` docstring 自认"不使用 cache_key 列参与命中"）、无 TTL/失效（`capability-map:190` 已登记 ❌"表只增不减"）、无防穿透空值缓存；Valkey 侧有 L1/`invalidate()`/NullCache，但依赖外部服务且连不上即**静默 no-op**（`layers.py:43-48`）。
⇒ **本轮不合并（D2，且留任一单轨都有代价：留 PG 永久丢"能失效"、留 Valkey 给 agent_server 加外部依赖并重做现网演示链路——`minimal-release-runbook.md:237` 明写问答走 pgvector、Milvus 不在这条路径上）。先还三笔便宜债**：
1. 一个 env 名只允许一个默认值：`CACHE_ENABLED` 当前两 app 相反（`agent_server/config.py:44` True vs `cache/config.py:16` False），且检查点也不同层（`query_router.py:161` 在路由 vs `semantic_cache.py:68/113` 在类内）；
2. `main_agent.py:481/511/531` 三处直接 `os.getenv("CACHE_ENABLED","false")` 绕开 config 对象 ⇒ 改回读 `get_cache_config()`；
3. PG 侧的 TTL/失效缺口保留登记（`capability-map:190` 那条 ❌ 继续算未达，不因本节而升档）。

⇒ 三笔债**已立案 #134**（含计数判据与非空转反证要求）。

**⑤ 落点与复审触发条件**（本节的债登记在哪、出现什么证据就回来重看）

| 债 | 登记处 | 为何不落 `docs/TODO.md` | 复审触发条件 |
|---|---|---|---|
| 联邦 L2 无租户谓词 | issue **#133** + 本节 ③ | TODO 处于**两条链分叉**（§0 索引表由 `scripts/evidence/recount_todo_index.py` 的 `DECLARED_TOTAL` 做 fail-closed 校验），在 feat 线加开项必然与 main 线的声明值打架 | 联邦 `/invoke` 出现**请求级**租户（或 `TENANT_ID` 不再是进程级）⇒ #133 的 A 选项作废，只能走 B |
| `CACHE_ENABLED` 一名两默认值 / 三处绕 config / 死锚 | issue **#134** + 本节 ④ | 同上 | 任一 app 的缓存默认值被翻转，或 `capability-map:408` 那串「insecure 态」清单被重新生成 ⇒ 回查 #134 第 1 项是否已被顺手做掉 |
| PG 轨无 TTL/失效 | **不另立案**，沿用 `capability-map:190` 的 ❌ | —（登记≠立项，这条本来就没立项） | 现网 `semantic_cache` 行数进生产量级，或有人开始用"缓存脏答案"解释线上现象 |

**一句不粉饰**：#133/#134 是**登记**，不是**排期**。这仓的排期唯一真相源仍是 `docs/TODO.md`（`reference-gap-and-coverage-ledgers` 那条口径：capability-map 管现状、tech-debt-audit 管识别、TODO 管排期）⇒ 本批有意不动 TODO，等 feat 合入 main、两链对账（现值 27/12 与 25/14 收敛）之后，由 TODO 台账写者把这两条补进 §0 分组并同步 `DECLARED_TOTAL`。

### 9.12 编号补齐：G15 定义行 + G16 定性改判（第三轮，2026-10-23）

> 起因是一处我自己的死引用：§9.11-① 的"下游传播"行写了 `G15`，而 §3 缺口清单最大只到 `G14`（`:94`）⇒ **我造了一个没建条目的编号**，下一个人照编号去找只能猜。修法是在 §9 内补定义（§3 属 §0–§8，本轮只获批对 §5 破例，未扩到 §3）。

| 编号 | 定性 | 内容 | 收口范围与判据 |
|---|---|---|---|
| **G15** | **缺口（P1）** | `req.user_id` 全仓取值面：按"是真实来源还是只往下转发"分开数——**origin 5 处**（HTTP/入口把请求体值读出来用）、**propagation 3 处**（`control_plane`/`execution_recovery`/`execution_scheduler` 收的是 `ExecutionRequest`，属传播非来源）。此前把两类混计成"6+"，并把 runtime 内部请求对象的 `request.user_id`（`memory_types.py:141` 一类）也算进通道 | ⇒ 真正要收口的只有 **5 个 origin**，T4 的"来源收口"按 5 计（不是 8、不是 6+）。范围比原报更小 ⇒ 对施工有利，不是让步 |
| **G16** | **~~缺口~~ 死代码清理项（P2）** | 联邦 `api/monitor.py:44` 的 `build_thread_id(user_id, sid)` 产出 `user-<uid>-session-<sid>` 形态 | **降级理由（已复验）**：`build_thread_id` 全仓命中 = 定义 `monitor.py:44` + docstring `:5` + `__all__` `:65` ⇒ **零调用**；`extract_thread_id_from_scope` 同样零外部调用；联邦真实链路走 `api/server.py:45/204-211` 的 `resolve_thread_id` → 内核 `resolve_thread_identity`（`tenant-` 形态），`:242` 用的就是它；`user-{uid}-session-{sid}` 形态 grep 不落任何存储。**且这事实仓库早就写明**：`scripts/migrate_thread_identity.py:18` 原话"零调用者的兼容符号"、`tests/governance/test_thread_identity_migration.py:213` 同标 ⇒ 我把它升格成"更重的发现"前**没查自己的迁移脚本** |
| G16 的清理尾巴 | — | 删两个符号**不是一个文件**：按名字引用共 **4 处** = `monitor.py:5`（docstring）+ `:65-66`（`__all__`）+ `scripts/migrate_thread_identity.py:18`（说明行）+ `docs/operations/audit-operator-principal-runbook.md:56`（把该形态归进"人工核实名单、不动"）。~~`CHANGELOG.md:533/537`~~ **该锚点系误记**（2026-10-23 第三轮评审实测：`applications/agent_federation/CHANGELOG.md` 全文 `grep build_thread_id` / `user-…session` **零命中**，533/537 行为空）——本条属"声称查过某文件并给出行号、实际不存在"的同型失误（与 plan-memory D6 的 metadata 表同款），记为纪律：**引用锚点须附可复取命令** | 判据：删后全仓 `git grep build_thread_id` **零命中**（CHANGELOG 本就无引用；runbook `:56` 是描述性提及非代码引用，若同批清理则一并核） |

**它不牵动什么（避免下一个人重新升格）**：不影响 §9.8 不可逆②（那讲的是 `tenant-` 前缀生成器，与此符号无关）、不影响 §9.5 的迁移编号假设。⇒ 也不构成"重取全链来源"的取证任务。

### 9.13 首批执行记录（T1.1/T1.2/T2.1/T2.2/T2.4，2026-10-23，分支 `feat/tenant-t1-cache-hardening`）

> 台账纪律：本节为 dated 执行记录，防止"文档说未执行而代码已执行"的 staleness。跳过项与原因一并登记。

| 批次 | 提交 | 内容与验收 | 状态 |
|---|---|---|---|
| T1.1 | `6381b70` | 读侧删 else 全表分支、写侧同步入口跳过+`skipped_no_tenant` 独立计数+WARNING（§9.11-② 落点 (i)/(ii) 均实现）；反证 3 条（零 SQL/零后台任务/计数可 reset） | ✅ |
| T1.2 | `8886033` | `RevertHandler` 归属断言（`tenant-` 前缀异租户 ⇒ FORBIDDEN，死码激活）+ `session_router` 走 `resolve_thread_id` 归一化；handler 层 4 条 + router 层 3 条 | ✅ |
| T2.1 | `edc4a7a` | `/query` 9 处收口到 `server_tenant_id()`，入口统一取值一次 + mismatch WARNING（软模式）；源码判据：`grep req.tenant_id` 仅剩比对+日志 2 处 | ✅ |
| T2.2 | `77531bd` | kefu `_run_kefu` 同款收口（IdentityMiddleware ContextVar 断言源）；`/api/messages` 构造值随之无害化 | ✅ |
| T2.4 | `b0b8dd0` | 联邦 httpx 回退路径出站附 `X-Internal-Tenant` 现签（每请求新鲜，TTL 300s）；**deepagents 主路径不注入**——其 headers 为构造期静态 dict，签名会过期，登记为上游能力缺口（当前 .venv 未装该包，生产走 httpx 回退） | ✅（含 1 登记局限） |
| T2.3 | — | **跳过**：依赖 D1 被 D8 反转后的改写（§9.2），须"先改 D1 再施工" | ⏸ 按前置 |
| T2.5 | — | **跳过**：D20=(b) 的"先审仓外调用方"是上线前置（§9.2 第四处），审计未做 | ⏸ 按前置 |

**连带处置**（核验轮发现，非本批引入）：
- `5b4416a`：两条 revert 治理用例断言对齐 T1.2 新契约（归一化线程值）；恢复被 cleaned history 误删的 `docs/operations/env-126-inventory.md`（734 行，自 `company-snapshot/fe22794` 原样恢复，消除 AGENTS.md:99/106/113 三处悬空引用——`test_doc_sync_file_refs` 基线红修复）。

**统一核验读数（2026-10-23）**：根套件 1314 passed / shared-schemas 28 / agent-runtime 693 / agent_server 131 / 联邦 179 / kefu 49 / exhibition 377 / knowledge 412 / otel 18（全部 passed，skip 为环境条件项）；eval 门禁 15/15=100%；`lint_architecture` 通过；全仓 ruff 通过；`check_doc_sync` 通过。**唯一残留**：nl2sql 2 条（`test_cached_when_unchanged` NTFS 纳秒精度 / `test_cache_expires` TTL=0 时 `elapsed > ttl` 边界）——**预存在平台特异性失败**（基线 a0e7b8e 即红、本批对该服务零改动、与租户语义零交集），登记待 nl2sql 侧拍板（TTL 语义撞"exceeded 用 >"的既有偏好，不擅自改）。**requires_pg 级判据**（伪造反证数据面、A1 增量维度）按 §9.10 待放行，未跑。

### 9.14 R-3/R-4 细化（D8 读写语义 + 014b 时序拆分，2026-10-23 用户拍板一后、006 施工前置）

> 取证基线 rev `d6d3014`（本分支）。本节解决第三轮评审 R-3/R-4：拍板定了方向（D8 摘键），施工前必须画清第一步。

**① 范围修正（比 §9.5 更准）：8 处生效 UNIQUE 中只摘 7 处，`session_state`（002:33）不摘。**
002 的 `UNIQUE (tenant_id, workspace_id, session_id, datasource_id)` 是**会话数据非元知识**——多轮四元组/已确认问答对属 D7 归属域（未来 conversations/014 域），与"元知识全企业共享"（D8）是两个语义层。§9.5 的"006 摘 8 处"系过度概括，照做会让会话状态从"每空间一份"变"全企业共享一份"（多轮状态互串，反向违反 D7）。006 实摘清单（按列集判等、沿用 005 DO 块配方）：
| 表 | 现行键（含 ws） | 摘后键 |
|---|---|---|
| column_info（001:62） | t,ws,ds,table,column | t,ds,table,column |
| metric_info（001:83） | t,ws,ds,metric | t,ds,metric |
| value_info（005 重建键） | t,ws,ds,table,column,value | t,ds,table,column,value |
| relation_info（001:148） | t,ws,ds,lt,lc,rt,rc | t,ds,lt,lc,rt,rc |
| alias_info（001:167） | t,ws,ds,kind,name,alias | t,ds,kind,name,alias |
| table_stats（002:96） | t,ws,ds,table | t,ds,table |
| example_info（004:15 建表；**文件名 `004_example_corpus.up.sql` ≠ 表名**，本行初版正是照文件名写成 `example_corpus` ⇒ 006 抄它后真 PG 42P01，见 §9.16 B-1） | t,ws,ds,question | t,ds,question |

**② 写入侧语义：留列 = 首灌来源，零额外代码。**
`_upsert`（meta_repository.py:347-367）的形态是 `ON CONFLICT (key_cols) DO UPDATE SET {updatable}`，且 updatable 恒不含键列。摘键后把 workspace_id 放在"键外、非 updatable"位置 ⇒ INSERT 首次写入当时的空间值，此后冲突更新永不覆盖 = 天然首灌溯源。`_SCOPE_COLS`（:24）从三元组改二元组 `(tenant_id, datasource_id)`（prune 扫描范围同步收窄，否则按 ws 清理会漏删共享行）。

**③ 读取侧：元知识谓词全摘、方法签名不动。**
list_* 7 处 WHERE、find_* 2 处、upsert_table_stats 的 ON CONFLICT、recall 节点 filters（recall_column.py:60 摘 workspace_id 项）——全部去 workspace_id。**方法签名保留 `workspace_id` 形参**（上游 6 个 recall 节点的传参成为无害透传，改动面从"9+14 处"收窄到"仓储层 SQL + 1 处 filters"）；pgvector `column_repository` 的 filters 序列摘 workspace 项。`get_session`/`upsert_session` 保留三列谓词不动（会话域，见 ①）。

**④ 验收（无库可跑部分本批完成，requires_pg 部分待环境）**：
- 单测级：仓储 SQL 形态断言（新键列集 / 无 workspace_id 谓词 / session 两方法保留）；"不同 workspace_id 请求召回同一行"的 mock 级用例。
- requires_pg 级（待放行）：真库建两空间导入同元知识 ⇒ 一行；跨空间召回等值；session_state 仍按空间隔离。

**⑤ R-4（014b 时序）**：§9.5 的 014 拆两行——**014a**（T3）：workspaces 改 PK + owner 列 + conversations 加列；**014b**（T4 后半）：`conversations.user_id SET NOT NULL`，前置 = A5 JWT claim 绑定落地 + 全写入点 user 可得性探测用例通过（挂 requires_pg）。否则 T3 末尾施工 014 会因取不到 user 值写炸或造哨兵债（9.7-① 禁令）。

**⑥ 执行登记**：006 于 2026-10-23 在分支 `feat/nl2sql-ttl-and-006-slim` 施工（用户拍板一选 A：零冲突窗口内做）。线上真库执行与 requires_pg 判据按 §9.8.1/§9.10 待环境待授权。

**拍板执行追加（2026-10-23 晚，用户三项批示均按建议执行）**：
- **拍板二（合入）**：首批 8 提交已 fast-forward 合入 `feat/nl2sql-meta-build-recovery`，短命分支已删。
- **拍板三（TTL/精度）**：`d6d3014`——ProbeCache 过期判定 `>`→`>=`（到期即过期，与预算超限的严格大于偏好不冲突）；prompt 缓存测试改真实 stat 身份回填（NTFS ns 取整平台失败）。nl2sql 由 187+2 红转 190 全绿。
- **拍板一（006 摘键，选 A）**：§9.14 细化随批落档（R-3/R-4 闭合）；`311fd6b` 施工——范围修正 **8→7 处**（session_state 是会话数据非元知识，保留三元组隔离，防与 D7/conversations 撞车）；前置查重 DO 块（有重复即中止不许自选留存）+ 7 处换键（005 列集判等配方）+ 空 down 登记；代码侧读谓词全摘/签名不动/`_upsert` 补 workspace_id 进 insert_cols（键外非 updatable ⇒ 首灌来源不覆盖）；4 recall 节点 filters 摘 workspace；fake 升级忠实 `DO UPDATE SET` 语义；新增 D8 正证用例。`3a1cb4d` 根套件 scope 期望同步。**线上真库执行与 requires_pg 判据待环境待授权**（§9.10），当前窗口价值已锁定为"SQL+代码+单测备妥，环境一通即上线"。
- 统一核验：根 1314 / nl2sql 190 / ruff / lint_architecture / check_doc_sync 全绿。

### 9.15 第四轮执行（T2.3 关闭判定 + T2.5 前半审计 + G16 清理，2026-10-23，分支 `feat/nl2sql-ttl-and-006-slim`）

**① T2.3 正式关闭**（此前标"⏸ 待 D1 改写"，经核对四个子项全部有着落）：
| 子项 | 落点 |
|---|---|
| meta DDL（013 加列） | **作废**（§9.2 G4 更正：001 已存在）+ 被 **006 反向动作**取代（摘键，D8）✅ |
| 三路召回 + CRUD 谓词 | 006 完成（保留 tenant 两列过滤，摘 workspace）✅ |
| 契约消费来源 body→断言 | `query_service.py:59-68` 的 `resolve_scope` 三级优先级（**服务端断言 > 请求体 > default**，`tenant_scope.py:10-14` 注释明示）+ T2.4 出站签名头补完链路 ✅；`query_router.py:26` 传 body 值但被 resolve_scope 断言覆盖，属 observe 档知情降级（#102/#103 既定设计），mismatch WARNING 属 T2.5 域统一件非关闭条件 |
| 验收判据 | tenantA 元知识 tenantB 召回=0：由保留的 tenant 谓词保证（requires_pg 级待环境实测）；漏传 fail-fast：enforce 档已实现（`_TENANT_UNSET` 触发）✅ |

**② T2.5 前半（仓外调用方审计）结论：D20 翻 403 零破坏**。
agent_server `/query` 的"携带 tenant_id/user_id 且与断言不符 ⇒ 403"规则，实跑审计全部直接调用方：
- `console.html`：不传身份字段（grep 零命中）→ 不断；
- `deploy/observability/langfuse_proof.py:107`：body 仅 query+session_id → 不断；
- `scripts/audit_tenant_access.py`：直连 DB 不走 HTTP → 不受影响；
- 仓内传播链（联邦→kefu `/invoke`、agent_server→nl2sql `/api/query`）：全为软模式（WARNING）+ T2.4 签名头，且 kefu/nl2sql 的 403 硬拒不在本批 D20 范围；
- exhibition `/api/query` 的 `self_reported_tenant_id`（server.py:140）是 ExecutionContext 另一套显式设计（X-Execution-Context 头），非 D20 射程。
⇒ **T2.5 的上线前置（先审仓外调用方）已满足**，403 硬拒可随契约批实施。审计基线 rev `b5fb61a`。

**③ G16 死代码清理完成**（判据达成：代码引用零命中）：
- 删 `monitor.py` 的 `build_thread_id` + `extract_thread_id_from_scope`（docstring/`__all__`/`Any` import 同步）；
- `migrate_thread_identity.py:18` 与 runbook `:56` 的**判定逻辑保留**（数据面该形态仍可能出现，进人工核实名单），仅来源说明改为"该符号已于 2026-10-23 G16 删除"；
- 遗留命中均为历史性说明文本（monitor docstring 清理备注、plan 登记、脚本/Runbook 来源行），符合判据"代码引用零命中"。
- 验证：联邦全量 179 passed；`test_thread_identity_migration.py` 49 passed；ruff clean。

**④ 下一步**：013/014a/015 迁移施工（T3 域，按 §9.14-⑤ 时序：014b 等待 T4 后半 A5 claim 绑定）。

**⑤ 013/014a/015 施工（T3 域迁移批，同日晚）**：
- **013**：organizations/users/conversations 三表（D9 org 直挂+is_admin；D11 旁置表，user_id 先可空）+ organizations 自 workspaces.tenant_id 回填。**同值域决策（D0 可逆）**：org_id=tenant_id 值域，现有 WHERE tenant_id 谓词零改动；将来一 org 多 tenant 另立迁移重映射。
- **014a**：workspaces 加 org_id（backfill 自 tenant_id + NOT NULL）+ owner_user_id（NULL=存量无主过渡态，D18 的 user 绑定等 T4/A5）+ visibility（默认 private，D7）+ PK 换 (org_id, id)；**兼容性发现**：保留 UNIQUE (tenant_id, id) 使 register_workspace 的 ON CONFLICT 在 007-013 与 014a 后两阶段均合法（否则渐进窗口报 42P10）。
- **015**：trajectories 补 tenant_id/org_id/user_id 三列——**施工实锤**：`TrajectoryRecord.tenant_id` 字段在 models.py 存在但 store_pg 列清单与 001 DDL 均无它 ⇒ 租户字段从未落库（G8 缺口的物理证据），本批一并补齐。
- 代码接线：`conversations.py` 包装器（§9.6-5 单语句 upsert 判据：`ON CONFLICT ... WHERE 归属匹配 RETURNING 1`，0 行即拒；user_id NULL 行 org 级放行=中间态）；`workspace_registry.register_workspace` 写 org_id/visibility + **42703 精确降级**（014a 未应用时按 007 旧形态重写，真故障照抛）；`store_pg.save` 三列写入 + 42703 降级。
- 隔离门禁：三表进 `SYSTEM_TABLE_WHITELIST` 登记理由（身份域本体，org_id 归属维在表内）——`test_isolation_dimension_contract` 由红转绿。
- 测试：`test_conversations_ownership.py` 14 条（首认领/跨 org 拒/跨 user 拒/中间态放行/42703 降级×2/真故障照抛/三列写入）。核验：根 1314 / runtime 707 / agent_server 131 / ruff / lint_architecture / check_doc_sync 全绿。
- **014b 未做**（按 §9.14-⑤ 时序，等 T4 后半 A5 claim 绑定）；requires_pg 级判据（真库并发双写/迁移回放）待环境。

### 9.16 分支返工批（2026-10-24）：三个阻塞项修复 + 盲区门禁

**背景**：`feat/nl2sql-ttl-and-006-slim` 评审报出 B-1/B-2/B-3 三个"真 PG 上必炸"的阻塞项，
全部在单测全绿下存活。本批按"先复现再修，修完当场验"的次序做，不复述评审结论。

**① 前提订正：本机拿得到真 PG**（旧口径"Windows 开发机无 PG ⇒ requires_pg 只能等环境"作废）
- 实测：`uv run --no-sync --with pgserver` 起 PostgreSQL 16.2 **且 wheel 自带 pgvector**，
  配 `WindowsSelectorEventLoopPolicy` 后 `create_pool` 直连可用。配方已入
  `docs/operations/testing-playbook.md` §3.4。`tests/ha/conftest.py` 在 win32 skip 的是**事件循环**，不是 PG 可达性。
- 判据形状：探针脚本落 `.evidence-out/`（gitignored），不改工作树。

**② 三阻塞项的真库读数**（取证脚本已入库：`scripts/evidence/nl2sql_real_pg_probe.py` +
`scripts/evidence/migration_gate_mutation_probe.py`；修复前的复现形态是同一脚本在缺陷代码上的读数，见下表左列）

| 项 | 修复前实跑 | 修复后实跑（`temp_pg_verify_fix.py`，走 `init_meta_schema.apply` 生产入口） |
|---|---|---|
| B-1 006 引用不存在的 `nl2sql_example_corpus` | `UndefinedTable`；回滚后 public 表数 **0**（连带吞掉 001-005） | 六份迁移全部应用 + 对账零差异 + **第二遍重跑仍零差异**（幂等） |
| B-2 `workspace_id` 空值时交出 None | `NotNullViolation` 23502（`nl2sql_column_info.workspace_id`） | 作用域列落 `''` 而非 NULL；绕过 `_stamp` 的直接仓储写入同样通过 |
| B-3 未应用 006 的库上跑新代码 | `InvalidColumnReference` 42P10 | 同形状复现（**发布顺序约束未被"修掉"，是被 B-1 解锁**：先迁移后发代码现在走得通） |

D8 语义反证同批取到：跨空间同问法两次写入 ⇒ 第二次是更新（`inserted=0, updated=1`），
库里仅一行且 `workspace_id` 停在首灌值 `w-a`；006 后唯一键实测 = `(datasource_id, question, tenant_id)`。

**③ 评审报告两处证据要订正**（结论不变，证据链有错，记此防照抄）
1. B-2 归因"ingest_service.py L172 构造点根本不传 `workspace_id`"**错**——该处传了。真正触发条件是
   **值为空**：`_stamp` 非空才写键 + `_upsert` 恒把该列进 INSERT 列表。确实"不传参"的是
   `scripts/discover_relations.py:135`（tenant/datasource/workspace 三个都不传）。
   ⇒ 修法覆盖"值为空"，光补传参救不了 discover_relations 那条链。
2. "CI 无 PG service"**不准**：`ha.yml` 起的就是 `pgvector/pgvector:pg16`，缺口是**覆盖面**——
   该 job 只跑 `tests/ha`（agent-runtime），nl2sql 的迁移与写入从未进过任何自动真库门禁
   （nl2sql 唯一真库用例是手挡 `DW_DB_DSN` 的 `test_golden_seed_real_pg.py`，Makefile 那条 session 不带 `-m requires_pg`）。

**④ 改动清单**
- `006_meta_unique_drop_workspace.up.sql`：6 处表名 → `nl2sql_example_info`，并在换键块注释"文件名≠表名"的来历。
  改写已应用迁移的顾虑不适用：nl2sql 侧无 checksum 版本表（每次全量幂等重跑，见评审 C-8），
  且 006 因 B-1 从未在任何库上成功应用过。
- `meta_knowledge_service._stamp`：三个作用域列**无条件写键**。
- `meta_repository._upsert`：作用域三列（含 `workspace_id`）恒以 `''` 兜底，**不依赖调用方是否写键**；
  `embedding` 不兜底（vector 列，`None` 才是正确语义，`''` 会让 PG 转型失败）。
- 新增 `scripts/lint_migration_refs.py`（进 `make lint` ⇒ 进 `make ci`），零基建：
  - **M-1 引用闭包**：迁移 SQL 引用的关系名必须在"到该文件为止的累计建表集"内（B-1 类）；
  - **M-2 冲突键命中**：生产代码的 `ON CONFLICT (cols)` 必须被迁移链最终态某唯一键覆盖
    （PG 语义按 covered-by 允许子集）；动态表名走弱通道（只验"全链存在此键集"），`_upsert`
    的常量键走 spec 通道——B-3 类因此静态可见；
  - **M-3/M-4 登记表双向对称差**：外部关系登记表、抽取盲区登记表，条目未命中即红、
    新盲区未登记即红（防白名单无声扩大，同 `lint_architecture.py` 的自检口径）；
  - **枚举口径 = `git ls-files`**（本机 FS 不作数），取不到清单退出码 2 fail-closed，无旁路开关；
  - **非空转证据**：`--selftest` 用合成违规样本逐条咬（空转即红）；另有临时副本变异反证
    `scripts/evidence/migration_gate_mutation_probe.py`：注入 B-1 错表名 ⇒ M-1 报红；摘掉 006 ⇒ M-2 视角
    目标键消失 ⇒ 报红；原样副本 ⇒ 两项零违规（阴性对照）。HEAD 正式跑读数：
    迁移目录 2 个、M-2 校验 25 处、盲区文件 1（已登记理由）、违规 0。
- `test_meta_knowledge_build.py`：fake 池 `_upsert` 增加 **NOT NULL 拒收**（除 `embedding` 外任何列为
  None 即 AssertionError）——B-2 全绿活过去的直接原因就是替身不校验 DDL 约束；
  并加 `test_default_scope_write_path_stamps_empty_string_not_null` 钉住默认路径与绕过 `_stamp` 的直接仓储写入。

**⑤ 仍悬（本批未做，别当已做）**
- 评审 H-1…H-7、C-1…C-8 **未动**（口径更正、runbook 前置检查、`organizations` 运行期回填排 016、
  `X-Internal-Tenant` 软模式与出站 payload 等）；
- nl2sql 真库冒烟进 `ha.yml`（路线 C）未接——本机已能自证，但自动门禁仍不覆盖 nl2sql；
- `session_leases` 全仓无 CREATE TABLE 属**既有待拍板项**（`plan-unfinished-completion-schedule` §3 第 22 项），
  本批 M-2 只是把它显式暴露成"未识别表名"，不另立登记。

**⑥ 测试面读数（2026-10-24 实跑，用户放行范围=仅 nl2sql session）**

| 命令 | 读数 |
|---|---|
| `uv run pytest applications/nl2sql-service/tests -q` | **191 passed, 4 skipped**（评审记录的基线是 190，本批 +1 = 新回归用例） |
| `uv run --with ruff ruff check .` | All checks passed |
| `uv run python scripts/lint_architecture.py` | 全条通过（P13 6/6 等，与本批无交集） |
| `uv run python scripts/check_doc_sync.py` | 通过，1 警告（既有项 `.codeartsdoer\temp\wt-meta-review`，非本批引入） |
| `uv run python scripts/lint_migration_refs.py --selftest` | 违规 0，M-2 校验 25 处，`rc=0` |

**反证（判据不是装饰，四形各一）**：
1. 变异反证·新用例：把 `_stamp` 与 `_upsert` 同时改回缺陷形态 ⇒
   `test_default_scope_write_path_stamps_empty_string_not_null` **精确报红**
   `AssertionError: nl2sql_column_info 的 NOT NULL 列 workspace_id 收到 None（真 PG 会 23502）`；
   恢复后复跑 191 passed，工作树无 `MUTATION-PROBE` 残留（`grep -rn MUTATION-PROBE applications/ packages/` 零命中）。
2. 变异反证·门禁：`scripts/evidence/migration_gate_mutation_probe.py` 三形——注入 B-1 错表名 ⇒ M-1 报红；
   摘掉 006 ⇒ M-2 的目标键集退化成含 `workspace_id` 的旧键（会报红）；原样副本 ⇒ 两项零违规（阴性对照）。
3. 门禁自检：`--selftest` 的合成违规样本若不被咬到即自行报红（含"登记表有项却判不出过期"这一形）。
4. 真库反证：`scripts/evidence/nl2sql_real_pg_probe.py` 11 项断言全 PASS，其中第 6 项**故意**在未应用 006 的库上
   跑当前代码，取到 42P10——即"发布顺序约束仍在，只是被 B-1 解锁"，不是被代码绕过。

**未取的读数（不得当作已做）**：根 session / agent-runtime session 等其余 8 个 session 与 `make eval`
未跑（放行范围只覆盖 nl2sql session）；本批改动面经判断不触及其断言，但该判断本身未取证据。

**⑦ 证据件的入库位置与一次顺带取到的读数**
- 两份取证脚本按 `scripts/evidence/README.md` 的收录判据（「会不会被下次必须重跑引用」）入库，
  并在 `ARCHITECTURE.md` 登记；台账与用例里的引用一律改指这两个仓内路径（`.evidence-out/` 里的
  一次性副本已删——那里的路径新克隆上不存在，判据等于不可复取）。
- 顺带取到 **`check_doc_sync` fail-closed 的一次真报红**：登记 ARCHITECTURE 行后、脚本尚未入库时，
  它精确报出 3 条「本机存在但未入库」⇒ 判定基准确实站在 `git ls-files` 而不是文件系统
  （AGENTS.md 记的 2026-10-04 那次翻车不会再从这条缝里漏过去）。`git add` 三个新脚本后转绿。

**⑧ 公开镜像防泄门禁（同日晚，用户批示"装上"）**
- 新增 `scripts/lint_public_mirror.py`，registry 模式进 `make lint`（⇒ 进 `make ci`），publish 模式推镜像前跑。
- **为什么必须两模式**：内网分支携带真实网段/主机名是工作产物（`env-126-inventory.md` 就是干这个的），
  单模式零容忍会让门禁在内网侧永远红 ⇒ 下一步一定是被人关掉，比没有更糟。故 registry 用登记制 +
  P-4 双向对称差（新命中未登记即红、登记项零命中即红），publish 模式只看 `base..ref` 新增行且
  **登记台账在此不生效**。
- 两类假阳性当场修掉并写进 `--selftest`（防再次出现时静默放行）：① flannel pod CIDR `10.244/16`
  在仓内文档已公开且无主机名时不定位 ⇒ 放过；② `uv.lock` 里的**四段版本号**与 10/8 地址同形
  ⇒ 按文件类豁免**只放 10/8 与 172.16-31**，`192.168` 段与私钥/token 类在锁文件里照判（selftest 钉住
  豁免不得越界）。测试目录同理：合成 fixture 豁免网段与主机名，密钥类不豁免。
- **检测器自身是泄漏面**（本门禁最容易被绕过的一处）：门禁脚本会随分支推到公开镜像，而它的签名、
  `--mask-plan` 建议表、`--selftest` 样本天然要"长得像"被拦的东西。初版给它自己开了路径豁免
  ⇒ 等于从检测器身上把闸打开（同一文件写真地址也合法）。改成：敏感整串一律 `_asm()` 运行时拼接，
  粗筛 ERE 用 `[x]` 单元素字符类打断源码文本（语义不变），**删掉路径豁免**，并新增
  `_self_source_clean()` —— `--selftest` 直接扫本文件文本，写进一条真地址当场判红。
  该条判据当场就咬到了自己：docstring 里按 CIDR 全写形态写的私有网段基址（四段地址形状），
  改成只写 `192.168/16` 这类前缀形态才既不匹配、又不丢含义。
- **拆片段会不会把检测能力拆没**：单独立探针（本机 .evidence-out 下的一次性脚本，**故意不入库**——它
  必须用真实整串才不循环，而真实整串一旦入库就从"被拦对象"变成"仓库公开内容"；不入库的代价是换机器
  要重写，故此处只留判据与读数，不留路径引用）打 11 个样本 ⇒ 首轮 `10/11`，抓到一个真漏：细粒度
  PAT `github_pat_11xxxx_yyyy` 中段是下划线，字符类 `[A-Za-z0-9]{20,}` 匹配不到（`_` 不在类内）
  ⇒ 精确式与粗筛 ERE 同批补 `_`，复跑 `11/11`，`mask_content` 对真实整串残留 0。
  结论：**豁免可以自我证明，能力必须外部反证**。
- 枚举口径 = `git ls-tree`/`git grep <ref>`（版本控制清单，非本机 FS）；`git grep` 无命中 rc=1 与
  "空 ref"不可区分 ⇒ `_tracked()` 取清单、空清单直接 raise（外层 exit 2 不判通过，同族坑：空目录冒充
  rc=1）。补一道基线守卫：`--base` 与 `--ref` 的文件清单**完全不相交**即判红，因为那时 diff 退化成
  "全量新公开"，读数看着很大但其实什么都没判。
- **登记失效必须分流**（这一条是被"公开镜像自己的 CI"逼出来的）：初版把"登记项零命中"一律判红，而
  镜像里那份 inventory 恰恰**已经遮干净**⇒ 公开仓跑 `make lint` 会永远红，红到一个没人看的仓上等于
  没有门禁。现分两支：路径不在清单里（幽灵登记，给未来的泄漏点预先授权）= 硬红；文件在、命中没了
  （已脱敏）= `[WARN]` 不计违规。
- **镜像形状：单提交、树先遮好**（差点自己造出第二次泄漏）：上一版镜像分支是"squash 未遮内容 → 再补
  一个脱敏提交"两个提交。它没推上去，所以什么都没泄；但一旦推送，**第一个提交的树就在公开历史里**，
  而公开历史改不回来。取证实数：中间提交 `b9deace` 里仍带 **1 处**内网标识（内网 GitLab 组路径那行，
  正是后来 `6ac7659` 补漏遮掉的），而 publish 模式只看 `base..ref` 的**最终** diff ⇒ 看得见 HEAD、
  看不见中间提交。⇒ 这条只能靠分支形状防，不是靠门禁防；重建为单提交（plumbing：临时 index
  `read-tree` 内网 tip → `update-index` 换成已遮的 blob → `write-tree` → `commit-tree -p <公开基线>`，
  全程不动工作区，避开共享 worktree 的并行提交风险），并写进 `AGENTS.md` 分支卫生第 5 条
  （"四条纪律"改五条）。
- 镜像侧读数（新单提交 `4303372`，树 = 内网 tip `2d95436` 减去被遮的 2 个文件）：publish
  `73090d0..mirror/*` **新增命中 0 处 `rc=0`**；registry @ 镜像 tip **命中 0 处 / 违规 0 / 警告 1**
  （警告就是那条"文件在、已脱敏"⇒ 分流生效，公开仓的 `make lint` 不会因此永远红）。
- 反证读数：registry @ HEAD `rc=0`（携带内网标识 1 个文件 / 26 处命中，已登记——签名拆片段后计数不变，
  证明没把检测面拆窄）；`--selftest` `rc=0`（含 `_self_source_clean` 与登记分流三支断言）；独立探针 11/11；
  publish @ 未脱敏工作树 `rc=1`（26 处，全部落在待遮的那一个文件里 ⇒ 门禁源码/plan/AGENTS/README 自身
  零命中）；两条**新增守卫的变异探针**：给一个与公开基线不相交的 ref ⇒ `rc=1` 并报"清单完全不相交"，
  给一个空树 commit ⇒ `rc=2` 并报"枚举失效不等于无需检查"（都不是通过）。
- 口径落到既有条账：`AGENTS.md` 分支卫生加第 4、5 条（"三条纪律"改五条）、`README.md` 的
  `public-mirror-notice` 补门禁指针，均不新开文档。
