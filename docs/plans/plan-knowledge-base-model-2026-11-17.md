# 多知识库数据模型方案（2026-11-17）

> 状态：**已实施（2026-11-17，工作区未提交）**。最终落点与 §2 选项制的关系见 §7（L1 按用户拍板走了第三条路：协议统一，非 L1-A 双路合并、非 L1-B 双写）。
> 触发：用户问「知识库 ID 是填的还是选的 / 一个租户几个知识库 / 搜索要不要选库」。
> 本方案基于代码实取（非猜测），并遵循既有决策 `plan-dual-vector-store-criteria-2026-10-19.md` §1.6 的 **C 按服务收敛**（Milvus 只服务 KS，不做双库统一）。

## 0. 先说三个实取事实（推翻了几个想当然）

| # | 事实 | 证据 |
|---|---|---|
| F1 | `workspace_id` 是**客户端传入的归属维**，不是身份 claim、不是安全边界。安全边界始终是 `tenant_id`（签名断言）。token 不签 workspace；前端硬编码 `'default'`。 | `agent_runtime/workspace_registry.py:32,65,173`；`identity.py:177-198`；`web/src/stores/conversations.ts:64-66` |
| F2 | **两份 RAG 完全独立**：UI 上传只写 KS 的 Milvus；平台对话 `/query` 的 RAG 只读 agent_server 自己的 pgvector `chunks`，前端没有写后者的任何入口。**即：从 UI 上传的文档，对话检索目前根本读不到。** | `web/src/api/kb.ts:74` → `kb_router.py:136` → KS `/upload`（无 `add_document`）；`subagents/rag.py:12-24` → `rag/store.py:106`；`add_document` 生产调用仅 `agent_server/api/import_router.py:51`（前端无调用） |
| F3 | `knowledge_id` **从没写进 Milvus chunk**：schema 只有 `tenant_id`/`scope_type`，`_enrich_chunk_metadata` 也不补它。它只活在 Mongo `kb_documents` 注册表 + LangGraph state + 生命周期里。 | `node_import_milvus.py:150-174,331-356`；`milvus_filter_utils.py:29-64`；`kb_registry.py:56-57` |

**推论**：本次改动里「知识库 ID 用于后续检索」的文案是错的（已在任务清单待修）。真正的断裂不是"过滤维度不够"，而是 **F2——上传与对话检索之间根本没接上**。多知识库方案必须建立在这个事实之上，否则是给一条不通的链路加选择器。

## 1. 产品决策（已与用户对齐的方向）

- **一个租户多个知识库**：成立。登记层唯一键 `(tenant_id, knowledge_id)` 已支持，无数量上限。
- **问数时不选库**：默认自动检索租户全部知识库；选库是可选高级能力（默认「全部知识库」）。
- **knowledge_id 与 workspace_id 不合并**：workspace 已被 memory/planner/nl2sql 多处当作作用域，且非安全边界；强行统一波及十余子系统，风险远大于收益。两者各管各的——workspace 管"会话/记忆作用域"，knowledge_id 管"KS 文档集"。
- **租户断言不动**：`tenant_id` 是唯一安全边界，签名头链路已正确，不改。

## 2. 方案（分三层，按依赖顺序）

### L0 — 修正错误承诺（立即，与后续无依赖）

把 KS `/upload` 的 422 文案、agent_server 代理文案、前端 `KbUpload.vue` 提示里的「用于后续检索」改为「**用于文档登记与发布管理**」。
knowledge_id 当前真实角色 = 登记分组 + 发布锚点 + 审计字段，文案必须与之相符。

### L1 — 让上传的文档能被对话检索到（**前置阻塞项**，必须先于 L2）

这是 F2 的直接后果，不做则 L2 无意义。

**选项 L1-A（推荐，最小接通）**：让平台对话的 rag 能力在查自有 chunks 之外，**并发查 KS 的 `/api/v1/retrieve`**，两路结果合并进 evidence。
- 改动点：`agent_server/capabilities.py` 已有的 `knowledge_retrieve` 远端能力（`:269-321`）现成可用；在 `subagents/rag.py` 或 graph 的 rag 节点加一路调用 + 合并。
- 租户口径：沿用 `_internal_headers()` 签名断言（已实现），不新引入 tenant 传参。
- workspace 口径：KS 没有 workspace 维度；合并时把 KS 结果的"来源"标为 KS，不伪造 workspace。
- 默认范围：**不传 knowledge_id = 全部库**（与 L2 兼容）。
- 风险：两路 evidence 的 citation 格式要统一；KS 不可达时降级（不能拖垮对话）。

**选项 L1-B（不推荐）**：把 UI 上传同时双写 agent_server 的 `chunks`（`add_document`）。会让同一份文档进两个存储、两套切片/embedding 口径，运维与一致性成本大；除非已决定 L1 之外还要统一双库，否则不做。

**需用户拍板**：选 L1-A 还是 L1-B（或明确暂不接通，接受"上传的文档只在 KS 自己的 /query 里可查"）。

### L2 — 多知识库做实（依赖 L1-A）

| 层 | 改动 |
|---|---|
| **知识库实体** | 用现有 Mongo `kb_documents` 作为"知识库"的登记源（按 tenant 列 distinct knowledge_id），**不新建关系表**——KS 无迁移链，Mongo 已是持久化锚点。新增 `GET /kb/knowledge-bases`（agent_server 代理 KS `GET /documents` 聚合）返回 `{knowledge_id, doc_count, status}` 列表。 |
| **前端下拉** | `KbUpload.vue` 的 knowledgeId 从自由文本 → **可搜索下拉**：从 `/kb/knowledge-bases` 拉已有库供选，同时允许输入新 ID 创建（首次上传即建库）。保留"必选"。 |
| **chunk 写入** | `node_import_milvus.py:331-356` 的 `_enrich_chunk_metadata` 增加 `knowledge_id`；schema 加对应 scalar field（Milvus dynamic field 已开，优先用动态字段避免改 collection schema/重建索引）。 |
| **检索过滤** | `milvus_filter_utils.py` 的 `build_retrieval_filter` 增加可选 `knowledge_id` 参数；`query_router.py` 的 `/query` 与 `/api/v1/retrieve` 请求 schema 增加 `knowledge_id: str = ""`（空 = 全部库）。**默认行为不变**。 |
| **RAG 接通** | L1-A 的合并调用默认不传 knowledge_id；用户在对话页选库时才透传（前端"知识范围"选择器，默认「全部知识库」）。 |
| **兼容** | 历史 chunk 没有 knowledge_id 字段 → 过滤时`knowledge_id in [选中值] OR NOT EXISTS knowledge_id`，保证老数据在全库模式下仍可召回；选库模式下老数据不召回（诚实行为，UI 标注"旧文档未分库"）。 |
| **发布** | `/reimport` 已按 `(tenant, knowledge_id)` 定位，无需改；DRAFT 未发布的既有问题独立处理（本次不改默认发布）。 |

## 3. 明确不做

- 不统一 workspace 与 knowledge_id（风险大、收益低，且 workspace 不是安全边界）
- 不统一两份向量库（遵循 `plan-dual-vector-store-criteria` C 方案）
- 不改 tenant 断言/签名头链路
- 不把 authority/effective_from 等生命周期字段塞进上传表单（它们属于发布时）
- 不改历史迁移文件（既有 checksum 钉死）

## 4. 验收判据（每层的"可核对"标准）

- L0：三处文案无「用于检索」字样；单测断言文案。
- L1-A：在 UI 上传一份 PUBLISHED 文档 → 平台对话 `/query` 问其内容 → evidence 里出现该文档的 citation；KS 不可达时对话仍返回（降级不崩）。
- L2：同租户建 A/B 两库各传一份文档 → 不选库提问，两库都能召回；选 A 库提问，只召回 A；老文档在全库模式下仍可召回。
- 全程：租户隔离测试（跨租户同名 knowledge_id 互不可见）必须通过。

## 5. 待用户拍板的三个点

1. **L1-A vs L1-B vs 暂不接通**（最重要——决定 L2 是否有意义）
2. L2 的知识库实体是否接受"用 Mongo kb_documents 聚合、不建关系表"（推荐接受）
3. 历史文档回填策略：是否批量给老 chunk 补一个 `knowledge_id='default'`（推荐补，让选库模式行为一致）

## 6. 与本轮未提交改动的关系

本轮工作区有 7 个未提交文件（知识库 ID 必填 + 多轮历史修复）。其中 KS/agent 的 422 文案属 L0，会在 L0 一并修正；其余改动与本方案正交。建议顺序：先提交本轮改动 → 再按 L0/L1/L2 分阶段实施。

## 7. 最终实施形态（2026-11-17 已实施，工作区未提交）

> 用户拍板结果：L1 既不选 A（对话检索并发查 KS、双路合并）也不选 B（上传双写两份存储），
> 走第三条路——**协议统一**：抽一份「文档向量检索」契约 `DocumentStore`，两个可切换后端，
> 上传与检索经同一个 `DOC_BACKEND` 开关落到**同一个后端实例**。断链的根因是「写 A 查 B」，
> 协议统一比 A 少一路远端依赖与合并逻辑、比 B 少一份存储与两套切片口径，且从此接口只有
> 一个（与 ADR-0009 三选项的关系定性与「禁止第三套」不变量的衔接，见该 ADR §6 后记）。

### 7.1 五个步骤与落点（全部完成）

| 步骤 | 内容 | 关键文件 |
|---|---|---|
| 1 协议 + 双后端 | `DocumentStore` 协议（add_documents / retrieve / delete_document 三件套，tenant_id 必填 fail-fast）+ Milvus（混合检索 dense+sparse）/ pgvector（同库同事务）双实现 + `DOC_BACKEND` 工厂；`DocumentStoreUnavailable` 异常（配置了但运行时不可用，与工厂返回 None 同一降级语义的两个入口） | `packages/agent-runtime/agent_runtime/document_store.py`；`applications/agent_server/rag/backend.py`、`rag/pg_backend.py` |
| 2 检索切换 | `subagents/rag.py` 改调协议工厂；降级链四支：工厂 None→「知识库未启用」；Unavailable→同句；Exception→`KNOWLEDGE_UNAVAILABLE`（「知识库检索失败」，不进 EMPTY_EVIDENCE_MARKERS，与问数不可达同口径）；空结果→`KNOWLEDGE_NO_HIT` | `applications/agent_server/subagents/rag.py`、`subagents/degradation.py` |
| 3 上传分流 | `/kb/uploads` 按 DOC_BACKEND 分流：pgvector→本地直写（同步完成，返回 `task_ids=[]` 无轮询）；milvus→照旧转 KS 管线；未知值→500 当场暴露。KS schema 升 v2（`+knowledge_id` / `+workspace_id`，17 字段两侧逐字段镜像）；检索过滤加 knowledge_id；422 文案改「用于文档登记与发布管理」 | `api/kb_router.py`；KS `node_import_milvus.py`、`milvus_filter_utils.py`、`api/import_router.py`；`scripts/reimport_kb_to_milvus.py`（dry-run 默认，本批不执行） |
| 4 多知识库 | `GET /kb/knowledge-bases`（代理聚合 KS `/documents`，feature 门 chat.run）；`knowledge_id` 贯穿 QueryRequest / AgentState / Plan / PlannerContext / capabilities RAG schema（空 = 全部知识库，默认行为不变）；pgvector 谓词 `_scope_predicate` 动态拼 WHERE；前端：对话页「知识范围」选择器（默认全部）+ 上传页知识库 ID datalist 可搜索下拉 + pgvector 响应（`task_ids=[]`）成功读数 | `api/kb_router.py`、`rag/store.py`、`planner/protocol.py`、`schemas.py`、`agent/state.py`、`agent/graph.py`、`web/src/*` |
| 5 默认切换 + 文档 | `DOC_BACKEND` 默认 `milvus`（pgvector 为本地降级备选）；根 `.env.example` 补齐段加 `DOC_*` 8 键（值与代码 Field 默认逐键对码，钉桩 `tests/governance/test_agent_server_env_template.py`）；ADR-0009 §6 后记；ARCHITECTURE.md §2.1 agent-runtime 行补 DocumentStore | `applications/agent_server/config.py`、根 `.env.example`、`docs/adr/0009-vector-store-selection.md`、`ARCHITECTURE.md` |

### 7.2 关键口径（对 §2/§5 的回应与偏差）

- **§5 三个待拍板点均已有落点**：① L1 走协议统一（见上）；② 知识库实体 = KS Mongo `kb_documents` 聚合、不建关系表（接受，`GET /kb/knowledge-bases` 即其只读视图）；③ 历史回填**不做**——pgvector 老 chunk 的 `knowledge_id` 为 NULL，全库模式照常召回（谓词对 NULL 兼容）、选库模式不召回老数据（诚实行为，与 §2 L2 兼容行一致），不造 `'default'` 假数据。
- **租户断言零改动**：`tenant_id` 仍是唯一安全边界；`_scope_predicate` 只拼 `workspace_id` / `knowledge_id` 两个归属维，不碰签名头链路。
- **集合拓扑（部署侧硬约束）**：默认集合 `platform_doc_v2_bge_m3`，不复用 KS 旧集合 `product_manual_v1_bge_m3`（缺 v2 字段、老数据未分库）；**部署侧 KS 的 `CHUNKS_COLLECTION` 必须与平台 `DOC_MILVUS_COLLECTION` 指到同一集合**——上传由 KS 管线写、检索由平台读，两侧集合名不一致 = 断链复活。存量 PUBLISHED 文档迁移用 `scripts/reimport_kb_to_milvus.py`。
- **维度对齐**：bge-m3 = 1024 维（`DOC_EMBED_DIM=1024`）；`DOC_EMBED_API_KEY` 未配时回退 app 主 embedder，工厂 warning 维度不一致——部署侧须自行保证 `EMBEDDING_*` 与集合对齐。

### 7.3 验收读数（2026-11-17 本机实跑；判决绑当天 HEAD 工作区）

- web 门禁 6/6 rc=0：`pnpm typecheck` / `pnpm lint` / `pnpm check:tokens`（定义 123/引用 123）/ `pnpm check:events`（端点成对性 11 消费 0 缺）/ `pnpm verify:sse`（150 条断言失败 0）/ `pnpm verify:markdown`。
- Python 侧：`uv run pytest applications/agent_server/tests -q` 与 `uv run pytest tests -q` 结果见完成报告（本节不抄数，防「读数搬进账面」）；`tests/governance/test_agent_server_env_template.py` 3 条已实跑通过（DOC_* 8 键对码）。
- **本批不做**：`scripts/reimport_kb_to_milvus.py` 执行、KS 镜像重建 + 集合重灌（均属部署/运维动作）；全部改动不 commit（用户铁律）。
- **复审触发条件**：若后续有人把 `DOC_BACKEND` 默认改回 pgvector 或改集合名，须同步本节 7.2 第三条与根 `.env.example` 对码，否则模板钉桩用例会红。

### 7.4 根套件 6 项红的定性（2026-11-17，逐条复跑后收口）

首次 `uv run pytest tests -q` 出 6 failed / 1124 passed / 35 skipped；逐条单独重跑 + 定位后：

| # | 失败项 | 定性 | 处置 |
|---|---|---|---|
| 1 | `test_get_owner_expiry`（durability） | **flaky**：`asyncio.sleep(0.02)` 对 0.01s TTL，并发负载下时序抖动；单独重跑即过 | 不改产品代码；并发跑套件时偶发，非本批引入 |
| 2 | `test_rag_insert_carries_workspace_id`（workspace_isolation） | **本批引入**：`add_document` 的 INSERT 把 knowledge_id 加在了 workspace_id 之后，破坏「末位 = workspace_id」既有契约 | 产品代码改回 workspace_id 末位、knowledge_id 倒数第二；同时**撤销**此前对 `test_corpus_tenant_isolation.py` 的同类断言改动（不得为过测试而改断言），两测试现在共享同一末位契约 |
| 3 | `test_p8_current_tree_has_zero_violations`（exception_echo） | **HEAD 遗留**：KS `import_router.py` 既有 `str(e)` 进 task result / 上传历史（经 /status、/history 回前端），因本批改了该文件才进入扫描面 | 按 P8 改生产代码：异常原文只进日志（`exc_info`），API 可见面给类名 + 导向日志 |
| 4 | `test_repo_is_clean_and_enumeration_is_not_vacuous`（graph_state_boundary） | **本批引入**：KS `_enrich_chunk_metadata` 从 state 读 workspace_id，属「有读无写」 | 在 `lint_graph_state_boundary.py` 的 `UNDECLARED_READS` 登记并写清理由 + 复审触发条件 |
| 5 | `test_every_business_table_declares_tenant_id`（isolation_dimension） | **HEAD 遗留**：018 `agent_sessions` 用 org_id 做断言值、无 tenant_id 列，白名单登记了同型 conversations 却漏了它 | 在 `SYSTEM_TABLE_WHITELIST` 补 agent_sessions + 同型理由 |
| 6 | `test_p15_current_tree_is_clean_and_really_judged`（role_feature_gates） | **本批引入**：重灌脚本 `scripts/reimport_kb_to_milvus.py` 新增签发位未登记 | 在 `lint_architecture.py` 的 `_SIGN_SITE_ALLOWED` 登记 + 理由（与 kb_router 出站同形、role 不签）；`lint.main()` 直接调用 RC=0、P15/P16 通过 |

> 收口复跑：根套件全量 **1130 passed, 35 skipped, 0 failed**（427s，原 1124 passed + 6 failed ⇒ 6 项全转绿）；相关 governance 子集 + agent_server 全套 = **318 passed, 1 skipped**；KS 单测全套 = **438 passed, 7 skipped**；web 6 门禁全 rc=0；ruff 全仓通过；doc-sync 通过（0 警告）。

## 8. 真环境端到端取证（2026-11-18，内网 126/241；判决绑 rev）

> 部署 rev = `aee36f9a`（2026-11-17 commit）。两镜像构建：`agent-platform:dev`=`23ed9b01`（含 pymilvus 3.0.3）、`knowledge-service-web:latest`=`e9fe23cc`，经 registry 通道（`192.168.100.241:5000`）分发到 125/126/241 三节点并校验 digest 一致。上线后 Pod GIT_REV 回读 = `aee36f9a`，/health 200。

### 8.1 A 项（milvus 模式断链修复）—— ✅ 通过

- 上传：KS `/upload` 传含验证盐 `ZephyrVault Capacitor Calibration 7Q3X torsional damper serial TQ-7749` 的 Markdown，knowledge_id=`verify-kb-final`，经 DRAFT→REVIEWING→PUBLISHED 合法迁移写进 `platform_doc_v2_bge_m3`。
- 集合实证：pymilvus 查询 `knowledge_id=='verify-kb-final'` → 1 实体，`tenant_id=default, workspace_id=default`，字段含 dense_vector(1024 维)/sparse_vector。
- 对话取证（2026-11-18T10:54:57+08:00，平台 Pod `agent-platform-67f77c9bf8-7g96w`，rev=aee36f9a）：中文问「减振器的零件编号是多少？请引用校准证明原文。」→ 答案逐字引用 `ZephyrVault Capacitor Calibration 7Q3X torsional damper serial TQ-7749`，来源「证据 1（Zephyr Calibration Record）」。`hit=true, degraded=false`。
- 反证：这正是旧代码（上传写 KS Milvus、对话读 agent_server pgvector）必然失败的场景；命中即证明断链修复。

### 8.2 部署期发现并修复的配置缺口（非产品 bug，逐项拍板后处置）

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | milvus 集合无健康端点、KS readiness 503 | ks-milvus 旧 Pod 重启 33 次崩 + 新副本 ImagePullBackOff（三节点 containerd 无 milvus 镜像） | 从 126 moby 的 `milvusdb/milvus:v2.5.10` import 进 containerd-k8s；新副本 Ready、endpoints 恢复 |
| 2 | 对话「知识库未启用（DOC_BACKEND 未配置）」 | 平台 ConfigMap/deploy env 未注入 `DOC_MILVUS_URI`，工厂返回 None | patch ConfigMap `DOC_MILVUS_URI=http://milvus:19530` + deploy env valueFrom；rollout |
| 3 | 对话「知识库检索失败（No module named 'pymilvus'）」 | **产品构建缺口**：平台 Dockerfile 只装 `agent-core[memory-embed-local]`，Milvus 实现需要 pymilvus | **产品代码修复**：根 Dockerfile 加 `RUN pip install pymilvus==3.0.3`（与 KS 对齐）；增量重建平台镜像 23ed9b01、重分发 |
| 4 | 对话「向量维度不匹配」 | 平台 DOC_EMBED_API_KEY 未配 → 回退主 embedder bge-small-zh 512 维，集合 dense_vector=1024 维 | 从 ks-secrets 复制 SILICONFLOW_API_KEY → 平台 secret `DOC_EMBED_API_KEY`；env 注入 `DOC_EMBED_*`（base=api.siliconflow.cn/v1, model=BAAI/bge-m3, dim=1024）；Pod 实读 doc embedder dim=1024 |
| 5 | 检索 0 命中（所有降级串消失） | 租户域不一致：平台 SINGLE_TENANT=default，KS KNOWLEDGE_DEFAULT_TENANT_ID=exhibition，文档登记为 exhibition 被租户隔离拦截 | patch KS ConfigMap `KNOWLEDGE_DEFAULT_TENANT_ID=default` + 重启 KS；重传文档 tenant=default；A 项通过 |

> 复审触发条件：换 rev / 换集合名 / 换租户域 / 换 embedder 后，8.1 的对话取证必须重跑；`DOC_MILVUS_URI`/`DOC_EMBED_*`/`KNOWLEDGE_DEFAULT_TENANT_ID` 三处部署配置任一漂移都会让断链复活，需绑 rev 复取。

### 8.3 B/C/D 项取证（2026-11-18，均绑 rev=aee36f9a）

- **B 项 pgvector 降级自洽** ✅：切 `DOC_BACKEND=pgvector` 后工厂返回 `PgVectorDocumentStore`（协议可切换性实证）；**上传侧**：直接调 `_local_ingest` 返回 `{"backend":"pgvector","task_ids":[],"chunks":1,"message":"已写入本地文档向量库（无需轮询进度）"}`，PG chunks 表 `count=1` 且含验证盐 5566；**检索侧**：对话问「福尔康继电器本地入库验证编号」→ 命中 5566，来源 falcon_relay.md，无降级串。验证后切回 milvus。
- **C 项选库隔离** ✅：同租户建 `verify-kb-C-libraryA`（盐 8812）/ `libraryB`（盐 4477），全库提问两盐都召回（证据1=B、证据2=A）；选库A只召回 8812（B 的 4477 未泄漏）、选库B只召回 4477（A 未泄漏）；`GET /kb/knowledge-bases` 返回 4 库含 A/B 的 doc_count/status。
- **D 项跨租户隔离** ✅：集合里两份同内容文档（TQ-7749），`verify-kb-final`=tenant default、`verify-kb-A-7Q3`=tenant exhibition；default 用户提问命中 TQ-7749 但来源只显示 default 那份，exhibition 文档零泄漏（`tenant_id` 谓词生效，签名头链路零改动）。

### 8.4 收尾状态

- 线上后端已恢复默认 `DOC_BACKEND=milvus`。
- 重灌脚本 `--yes`：dry-run 实测 PUBLISHED 存量 = 0 条（本次验证文档走新管线直写，无需重灌）；未真跑 `--yes`。
- commit：`aee36f9a`（业务改动）已部署并验证；真环境发现的**平台镜像缺 pymilvus** 构建缺口已修到根 Dockerfile（`pymilvus==3.0.3`）+ pip 国内源固化（清华源 + 超时重试），并在后续 commit `8835c88f` 入库（仅构建配置 + 文档，不改运行时代码，线上无需因它重部署）。
- 复审触发条件：换 rev / 集合名 / 租户域 / embedder / DOC_BACKEND 后，A/B/C/D 取证必须按绑 rev 复取。
