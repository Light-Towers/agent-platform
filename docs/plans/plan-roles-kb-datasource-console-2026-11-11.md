# 方案：角色可见性 + 知识库上传配置 + 问数数据源配置（三块管理面）

- 状态：**已外部评审（2026-11-11，模式 R）并按其 6 条必改项修订；第二/三轮评审结论已并入**（N-1~N-4、出站签名单入口、瘦身项、P9），台账见 §11 末行与 §12。**第四轮审核（本文自审，非外部评审）订正了 3 处承重面事实错误 + 4 处自相矛盾，台账见 §14**。**未动一行代码**，未建表；判据改动仅 §12/§14 所列各条（均带理由与恢复触发）。❗ **2026-11-11 拍板：P1=viewer 兜底、P8=(a) viewer 兜底、P9=最小闭环（§13）；P3(a)=Mongo collection、P4=部署级、P6=必做边界 ADR、P7=A 表为准 YAML 下线。剩 P3(b) 未定（刀 2 前必拍，且必须同时消解 R-11）；P2/P5 施工时再定**。❗ **「刀 1 前置清零」是 overclaim（第四轮订正）**：拍板格已清，但 **1c 仍被两项实物阻塞**（现网 YAML 取证本机不可达 126 + 在途收敛件冲突规避）；**刀 2 仍缺 P3(b)/边界 ADR/KS 镜像重建**
- 评审基线：判定当时 HEAD 仍为 `d9fa8eaa`，评审方 16/16 复取相符、无 P0 基线缺陷 ⇒ 本件的锚点面**无需重取**（除下列新补的 F17/F18）
- 日期：2026-11-11
- 取证 rev：**`d9fa8eaa`**（§1 每条事实绑这一棵树。换 rev 后须按 §1 右列命令复取，**不得引本文读数当现值**——《观测面硬规矩》第 3/9 条）
- ⚠ **基准 = HEAD 树，不是工作区**：本文落件时工作区有 **8 个未入库文件**（`git diff --stat` = 148+/45-），内容是「入站错误收敛到 `AppError` + `request_id` 信封」，**与本方案射程直接重叠**：`identity_middleware.py`（D2 的 claims 消费点）、`query_router.py`（§4 `chat.run` 守卫落点）、`shared_schemas/error.py`（§4 拒绝响应的信封形状）、`web/src/api/errors.ts`（前端渲染面）。⇒ **评审方按本文命令复取得到的是 HEAD，与当时屏上内容不同**（《观测面硬规矩》第 6 条：「git 看到的」与「我看到的」不是同一个东西）。本文不代那件在途工作做判断，只在 D10/R-8 里声明依赖。
- 分级：**T2**（3 刀，跨 `packages/agent-runtime` + `applications/agent_server` + `applications/nl2sql-service` + `applications/knowledge-service` + `web/` + 部署清单六面）
- 决策边界：角色码上令牌 = **D2**（改 claims 形状 + 对外契约字段集被在册用例钉住）⇒ 单独 `docs/adr/0015-*.md`；feature 清单与表形状 = **D1**（本文给结论，人批）；「口令不进库」= **D2**（安全档位声明，见 D6）
- 用户原话（需求来源，2026-11-10，三条逐字）：
  1.「我现在想加上角色，不同角色看到的功能是不一样的。」
  2.「知识库：能支持上传文档，上传文档的配置也需要有界面单独处理。」
  3.「智能问数：得有界面支持配置数据源。」
- **评审方读法**：§1 = 可复核事实（每条带命令）；§2 = 射程边界；§3 = 决策本体（含放弃项与理由）；§4 = feature 枚举，是三刀的射程定义而非装饰；§6 = 刀次 + 八条反证；§10 = 给评审方的提问。**讨论过程不复述**，被否掉的方案压缩进 §3 的「放弃」列。

---

## 1. 现状事实（逐条可复核，不是推测）

> 共 **23 条**（F1–F23）。❗ **行序说明**：F16 因编辑顺序落在 F19 之后，**按编号读、不按行序读**（不重编号是为了不弄断 D11 / R9 / P7 / §11 里已有的指向）。F17–F19 是第一轮评审后新补、F20–F21 是第三/四轮新补、**F22–F23 是第四轮补充取证新补（用户质疑「文档存哪」引出）**，**均经本文自己复取**（不是转述评审读数，口径见 §11 首行声明）。❗ **第四轮订正**：F20 原写「发送方 5 处」经复取为 **9 处**（漏 exhibition / KS 两处 / federation `knowledge_tools`），且 `sql_router.py` 服务归属写错；F21 为随之新增的施工陷阱格。**承重面订正，不是措辞润色**——D11 升级点 1 的射程依它。

| # | 事实 | 证据 / 复取命令（rev `d9fa8eaa`） |
|---|---|---|
| F1 | 角色位 `users.is_admin` 存在但**后端零端点消费者**（❗ 第五轮订正：原写「零消费者」且「命中面只有 py 件」——**搜索面只盖 `*.py`，漏了前端**） | `git grep -nE "\bis_admin\b" -- "*.py"` ⇒ 命中面只有 `auth_users.py`（写记录/读记录）、`auth_router.py`（返回体）、tests。**没有任何后端端点据它放行**。❗ **补（评审 #1）**：另命中 `tests/deploy/test_k8s_manifest_wiring.py:412` `_ASSERTION_FIELDS = ("access_token","tenant_id","user_id","is_admin")`（`:507` 遍历断言存在）——加 `role` 不破它，但这条「不随动」的判定要写进 §7。❗ **第五轮补（前端面，原漏）**：`web/src/api/auth.ts:59`（`AuthSession.isAdmin: boolean` 接口字段）、`:220`（`const isAdmin = json.is_admin === true`）、`:222`（返回进 session）；但 `git grep -c -F "isAdmin" -- web/` ⇒ **全 web 面只有 auth.ts 这 3 处** ⇒ **解析了但零 UI 消费（死字段，与 F2「引擎在、声明面空」同型）**。另 `web/scripts/verify-sse.mjs:519` fixture 带 `is_admin: true`。⇒ **随动件见 §7 新行**；且 `auth.ts:213` 注释自陈「`is_admin` 缺失按 false（不是 fail-open 的 true）」——**这是前端已有的同型纪律，可作 D9 兜底（缺 role → viewer 而非 admin）的在册依据** |
| F2 | 权限引擎在位，但**声明面为空** ⇒ 填上 `caller_permissions` 也不会拦任何东西 | `packages/agent-runtime/agent_runtime/skills/registry.py:78`（`permissions: frozenset[str] = frozenset()`）、`:312-337`（`s.permissions <= allowed` 过滤）；`planner/policy.py` 第 5 条同源；`git grep -n permissions -- applications/agent_server/capabilities.py` **零命中**；None 跳过由 `tests/planner/test_policy_validator.py::test_validate_permissions_none_skips_check` 钉住。**这是本方案最容易被读成「已具备」的一格** |
| F3 | nl2sql 有整条角色消费链，但**值是配置常量** | `query_service.py:117 "user_role": settings.default_query_role` → `agent/state.py:91-94`（`user_role` / `admin_roles` 字段声明）→ `agent/nodes/execute_sql.py:145 is_masked_role(role, admin_roles)`（**全路径，评审 #F3**）；`conf/settings.py:146 admin_roles=["admin"]`、`:149 default_query_role="analyst"`，其注释自陈「L3 角色来源（服务端断言，非客户端请求体）：未接 ADR-0007 身份门前…接入身份门后改为从断言身份取」 |
| F4 | claims 形状闭合、**无 role 位** | `identity.py:61-67` `@dataclass(frozen=True) TokenClaims(tenant_id, user_id=None, jti=None, exp=None, iat=None)`（❗ 第六轮订正：原写 :62-68，实际 :61-67）、`:162 mint_token` / `:192 verify_token`，payload 固定；`verify_token` docstring 自陈「强制 exp/iat/sub…必须含非空 tenant_id claim」。❗ **第六轮正面事实（H9）：`TokenClaims(` 全仓构造点只有 1 处**（`git grep -c -F "TokenClaims(" -- "*.py"` ⇒ 仅 identity.py；测试不直接构造、走 mint_token）⇒ **加 role 字段影响面极小，1a 体量可控** |
| F5 | `is_admin` 只在登录响应体，`/auth/me` 不回读 ⇒ **刷新即失** | `auth_router.py` 的 `MeResponse` 仅 `tenant_id/user_id`；前端恢复路径只走 `/auth/me`（`web/src/stores/session.ts` probe 分支）。两体字段集被 `tests/governance/test_login_no_secret_leakage.py` 钉**三格**（评审 #3 纠正本文原来的“两处”）：`:68 UserRecord`、`:75 TokenResponse`、`:76 MeResponse` |
| F6 | 令牌 TTL 上限 3600 已在册（不是待发现的坑） | `auth_router._issue` 注释自陈 `AUTH_TOKEN_TTL=28800` 签出的令牌被 `TENANT_JWT_MAX_TTL_S`（默认 3600）当场拒，因此「签完自验一次」 |
| F7 | 身份门 **4/6**，两个服务跑各自 fork | `docs/plans/plan-identity-gate-6of6-2026-10-16.md` §2 表；共享实现 = agent_server（直挂 `IdentityMiddleware`）/ federation / kefu / nl2sql；**knowledge-service 与 exhibition-agent 各一套**，KS 零依赖 agent-runtime |
| F8 | KS 上传能力**已在**：多文件 + 10 余个 metadata Form + 任务状态 + 自带页面 | `applications/knowledge-service/knowledge_service/api/import_router.py:143 @router.post("/upload")`、字段集 `:148-160`（`scope_type/tenant_id/tenant_type/effective_from/effective_to/version/authority/status/constraint_kind/enable_item_name_recognition/venue_id`，评审 #F8 补）+ `knowledge_id/exhibition_id`（见 `scripts/import_exhibition_corpus.py:96-108`）；`GET /status/{task_id}`；页面 `knowledge_service/import_process/page/import.html` |
| F9 | KS 那套 fork 门卫有**实踩过的 fail-open 形** | `utils/tenant_identity.py`：`enforce=True` 且 HMAC key 未加载时 `hdr and key` 短路为 False ⇒ 伪造头透传（在册 pitfall 记忆同条） |
| F10 | 数据源 = 单源 + DSN 在 Secret，**没有 datasources 表** | `services/datasource.py build_default_registry`（docstring 自陈「只覆盖当前一个业务数仓 DSN 的现实部署」）；`api/dependencies.py:73-129` lifespan 按 `settings.dw_db_dsn` 建单个 `dw` 池；`api/routers/meta_admin_router.py` 只有 `POST /refresh`；迁移止于 `006_meta_unique_drop_workspace` |
| F11 | 「口令单一来源」是**已在册的设计不变量** | `deploy/k8s/05-secrets.yaml:29`「口令的**唯一来源就是这两个 DSN**：`deploy/data/nl2sql_dbsql.sql` 从 DSN 解析 user/password…**仓内不存在第二份口令材料**」；`nl2sql_dbsql.sql:17-18,91`「轮换后重跑本 Job 即收敛，不必进库手改」+ 三条 fail-closed 断言（`:63/70/76`） |
| F12 | 前端**零路由、零 pinia** | `web/package.json` deps = `vue@3.5.44` + `eventsource-parser@4.1.3` 两项；`web/src/App.vue` 两个 `<main>` v-if/v-else 切「登录面 / 对话面」 |
| F13 | agent_server 对外端点面 = feature 枚举的靶面 | `git grep -hE '@router\.(get\|post\|patch\|put\|delete)\(' -- applications/agent_server/api` ⇒ `/query`、`/history`、`/session/revert`、`/import`、`/sql/train`、`/task/{task_id}(/approve|/reject)`、`/console.html`、`/health`、`/auth/*`；控制面 `/{execution_id}` + `cancel/pause/resume/retry/requeue/recover/terminate`（`api/control.py`） |
| F14 | 迁移下一可用号 = **017** | `packages/agent-runtime/agent_runtime/migrations/` 实测最新为 `016_user_credentials` |
| F15 | 身份类参数剔除面现值 = `tenant_id/user_id/api_key` | `applications/agent_server/capabilities.py _sanitize_identity`，三条不变量钉在 `tests/test_capabilities_identity.py` |
| **F17** | **内部签名头已经是 JSON payload，加键是向后兼容的扩展方向**（⇒ D11 的承载因此成立） | `packages/agent-core/agent_core/internal_header.py:66` `payload = {"t": tenant, "u": user, "ts": ts}`；`verify_internal_header` 在 `:88-…` 用 `data.get("t")/get("u")` 取值 ⇒ **未知键被忽略**；签名覆盖整个 payload ⇒ 旧钥签不出新头。KS 的 fork **复用同一个原语**（`knowledge_service/utils/tenant_identity.py:93 verify_internal_header(hdr, key=…)`）且只读 tenant ⇒ **给它不用的键不会伤它** |
| **F18** | **未断言调用方这一格不只影响 role，它今天已经由客户端自报值定 `user_id`**（评审 #24 的核实结果，本文复跑） | `applications/agent_server/capabilities.py:110` `user_id = server_user_id(kwargs.get("user_id", "default"))`；`workspace_registry.py:77-82` docstring 自陈「**ContextVar 优先，其次显式 default；两者都缺 → 抛错**」⇒ 已绑定时客户端值被忽略（**不是注入面**），**未绑定时客户端值直接成为属主/分桶值**（降级面）。另：`:85 asserted_user_id()` 的 docstring 有「⚠ 不得拿它当随便兜个默认值的入口」的在册警告 |
| **F19** | skill 级权限过滤的**接线点不在本轮射程内**（评审 #2 指出，本文复跑确认） | `caller_permissions` 在全仓只有**默认 `None` 的逐层透传**：`planner/agentic_bridge.py:33/44/87/93`、`planner/execution_graph.py:539/574`、`planner/policy.py:45/72`；非 None 的调用只在测试里（`packages/agent-runtime/tests/test_policy.py:106` 的 `test_validate_permission_denied`，**同文件 `test_validate_permission_granted` 等也传非 None**；❗ 第四轮订正：原写「唯一非 None 的调用是 :106」不准确，属「只有 N 处」型断言）；真正的应用侧入口在 **`applications/agent_federation/planners/agentic_runtime_bridge.py:98`**（第二个应用）。⇒ 刀 1 的十个守卫是**端点级**，不是 skill 级；两者不同物（见 N7） |
| **F16** | **数据源与角色脱敏已有一份 YAML 配置源**（不是“从零建”） | `applications/nl2sql-service/nl2sql_service/conf/app_config.yaml:58 datasource:`（`id: "dw"` / `label:` 口径标签 / `dialect:` 空=scheme 探测）、`:87 data_permission:`（`sensitive_columns` / `result_masking_enabled` / `mask_keep_chars` / `admin_roles: ["admin"]` / `default_query_role: "analyst"`）；消费路径 `conf/settings.py:248 _load_yaml(app_config.yaml)` → `:290-291 overrides["admin_roles"/"default_query_role"]`。**⇒ G3 要的“配 label/方言/默认源”今天已存在，只是在文件里不在库里；F3 那两个常量的真值来源是这块 YAML，不是 settings 默认**。❗ **补（评审 #22 + 本文复取）**：`Dockerfile.nl2sql-service:30-33` 只 COPY packages + applications ⇒ `app_config.yaml` **烘在 nl2sql 独立镜像里**，`deploy/k8s/` 无该文件的挂载通道（仅 `00-config.yaml:75` / `36-…:89` 两处注释提及）⇒ **P7-A 的“一次现网配置变更”实际是一次 build+distribute 发布列车**。❗ **第三轮订正（边际成本）**：刀 3 本身就改 nl2sql 代码（`services/datasource.py:87` + `api/dependencies.py:122`）⇒ 镜像重建是刀 3 的**内在成本**，不构成 P7 A/B 的差异项（见 P7） |
| **F20** | **出站发送方全清单 = 9 处（❗ 第四轮订正：原写「5 处」漏 4 处，且把 agent_server 的件误挂 nl2sql 名下）**；其中 HMAC 内部头签发 **3 处**、静态 Bearer **2 处**、裸无凭据 **4 处** | **HMAC 已签 3 处（均无 `r`）**：① `applications/agent_server/api/sql_router.py:61`（`/sql/train` 转发；❗ 原 F20 写成 nl2sql 侧 `api/sql_router.py` —— **该路径在 `d9fa8eaa` 不存在**，`git show` 报 `fatal: path does not exist`；nl2sql 侧对应件是 `api/routers/ingest_router.py`，它是**接收方**不是发送方）；② `agent_federation/agent/async_subagents.py:87`（`sign_internal_header(tenant, None, …)` ⇒ 无 `u`/`r`；私有包装 `_internal_tenant_header` 在 `:56-91`，warn-once 软模式）；③ ❗ **原 F20 完全漏掉**：`agent_federation/tools/knowledge_tools.py:145`（经 **runtime 包装**签，无 `u`/`r`）。**静态 Bearer 2 处（不是 HMAC，原 F20 未区分）**：`capabilities.py:261`（KS `/query`）、`:286`（KS `/api/v1/retrieve`），headers = `Authorization: Bearer {KNOWLEDGE_SERVICE_KEY}`。**裸无凭据 4 处**：`capabilities.py:313`（nl2sql `/api/query`）、`:339`（kefu `/invoke`）、❗ **`:366`（exhibition `/api/query`，原 F20 漏）**、`subagents/sql_agent.py:66`（nl2sql `/api/query`）——四者 `client.post(...)` 均无 headers 参数。`as_remote_skill`（`skills/remote.py:14-27`）只包 invoke **不拥有 HTTP 出口** ⇒ 无现成单点 |
| **F21** | ❗ **新增（第四轮）：D11「出站单入口」的两个施工陷阱，均在 F20 清单之外** | ① **runtime 层有同名委托包装**：`packages/agent-runtime/agent_runtime/identity.py:261 sign_internal_header(...)` → `_core_sign(...)`，其上方注释自陈「签名/验签原语**单一实现于** `agent_core.internal_header`」⇒ **它不是第二实现**（ADR-0015 §6.8 那条风险今天不在 runtime 层成立），但 `knowledge_tools.py:145` 正是 `from agent_runtime.identity import … sign_internal_header` ⇒ **新增 `build_internal_headers` 若只改 agent-core 不同步这层包装，该路径拿不到 `role` 通道**（静默失效，与 N-1 同族）。② **`knowledge_tools.py:140-147` 是比 warn-once 更弱的静默不签标本**：`try: … if _hk: headers[…] = sign(…) except ImportError: pass` ⇒ 无 key 或 import 失败时**不签头也不记日志**，请求照发（F9 同族 fail-open 形）。⇒ 收编进单入口时这处必须**改为具名失败或 warn-once**，不能原样搬 |
| **F22** | ❗ **新增（第四轮补充取证，用户质疑「文档存哪」引出）：KS 是四套存储各有其责，且今天没有「文档级元数据表」**。❗ **本条订正 N-4 的「KS 只有 Mongo+Milvus」（漏了 MinIO 与 Neo4j）** | **MinIO = 原文对象**（PDF/图片）：桶 `kb-import-bucket`、目录 `pdf_files`/`images`（`README.md:179`、`.env.example:70`；`clients/minio_utils.py` 负责建桶 + 公网只读策略 `MINIO_PUBLIC_READ`）。**Milvus = chunk 向量 + 标量元数据附在向量行上**：`node_import_milvus.py` 的 `kb_chunks` schema = `chunk_id`(PK) / `content` / `title` / `parent_title` / `part` / `file_title` / `item_name` / **`tenant_id`** / **`scope_type`** / `created_at` / `source_doc` / `sparse_vector` / `dense_vector`，由 `extract_tenant_scope_for_chunk(state)` 从 state 透传。**Neo4j = 知识图谱**。**MongoDB = 只存会话历史**：`clients/mongo_history_utils.py` 是 `agent_core.memory.mongo.MongoHistoryStore` 的**兼容 shim**（docstring 自陈「过渡期保留」）。⇒ `clients/` 四件 = milvus_utils / minio_utils / mongo_history_utils / neo4j_utils；**上传配置模板是全新实体，今天无任何存储位置**（既不是文档也不是 chunk） |
| **F23** | ❗ **新增（第四轮）：`scope_type` 不跨租户，但与检索侧必须同源** | `utils/milvus_filter_utils.py:build_tenant_filter` = `tenant_id == "…"` **and** `scope_type == "…"`（**等值 AND，PUBLIC 不跳过租户谓词**）⇒ 模板把 `scope_type` 设 PUBLIC **不会**造成跨租户泄露（本文一度怀疑会，**取证后收回**；R-11 定性仍为配置污染）。但同件 `build_retrieval_filter` **全空返回 None = 全库检索**、`if tenant_id:` 空则**不做租户隔离**（docstring 自陈）⇒ KS 既有 fail-open 形（F9 同族；N5 不收敛 KS fork ⇒ **不在本轮射程，仅登记**）。**新风险**：检索侧 `query_router.py:71/:80 scope_type = Field("")` 默认空（不过滤），若调用方显式传 PRIVATE 而模板设 PUBLIC ⇒ **上传成功但检索不到**（静默失效）⇒ 见 **R-12** |

---

## 2. 目标 / 非目标

**目标**（每块按「用户屏上能看见什么」写，不按「建了什么表」写）：

1. **G1 角色**：登录后，viewer 看不到也调不动上传/配置/控制面；editor 能问数、能上传（落 DRAFT）、能改上传配置；admin 额外能发布、能配数据源、能操作执行控制面与人工审批。角色由服务端断言，前端隐藏只是体验。
2. **G2 知识库**：在 `web/` 里上传文档 + 选一份**可复用的上传配置模板**（把 F8 那一堆 metadata 从「每次手填 / 脚本写死常量」变成「配一次、多处复用」），上传后看得到任务进度。**浏览器不直连 KS。**
3. **G3 问数**：在 `web/` 里看到有哪些数据源、改名称/方言/口径标签、**设默认源**、把元数据绑定到某个源。口令**不在**这一面。

**非目标**（本轮明确不做，每条带升档触发条件；「不做」不是遗漏，是射程边界）：

- **N1 口令不进库、不做 KEK/DEK 信封加密**。触发条件 = 出现「外部租户自己在网页填自己数仓口令」的真实需求，届时**先答**「内网有没有 KMS/Vault」再谈形状。理由见 D6 + F11（这条不是「以后再说」，是「做了会撞在册不变量」）。❗ **措辞订正（评审 #12 接受）**：理由不是抽象的「档位不变」——对**仅拖库**（拿到数据文件、拿不到 Secret）的对手，密文 + 库外 KEK 的档位**确实更高**。准确说法是：**在本部署当前的威胁模型下（Secret 与库同域、运维同权）档位不变、复杂度净增**。威胁模型变了，本条触发条件即提前。
- **N7 skill 级权限过滤本轮不接线**（评审 #2 逼出来的新格，防「端点级守卫」被读成「引擎已启用」）。触发条件 = 多 Planner 收敛那一刀真要给不同 skill 定权限时。届时的**最小前置**已在 F19 量好：接线点是两个应用的装配层（`agentic_runtime_bridge.py:98` / `execution_graph.py:539` 的调用方），不是 runtime 内部。本轮**不做**的理由：刀 1 交付的是端点级守卫，与 skill 级过滤不同物；把接线塞进刀 1 会同时把第二个应用（federation）拉进射程。
- **N2 不做自定义角色、不做 `role_permissions` 入库、不做多角色 `memberships`**。触发条件 = 第一个真实租户要求「和别家不一样的角色」。⇒ 届时**必做前置** = §4 的 feature 判定已就位（见 D5），否则脱敏按角色名匹配会在自定义码出现后静默失效。
- **N3 不做权限吊销面**（`jti` deny list）。后果必须写进界面与本文：**改某个人的角色 = 他下次登录才生效**（最长一个令牌 TTL，F6 上限 3600s）。触发条件 = 第一次真实的「需要当场剥夺」事件。
- **N4 不做多源池热加载**。界面写期望态，生效走重启/reconcile，屏上标「已保存·未生效」。
- **N5 不翻** `DEPLOY_ENFORCE_IDENTITY` / `TENANT_JWT_ENFORCE` 默认值（ADR-0008 U1 保持现状 C），**不**收敛 KS/exhibition 两套 fork 门卫（属 `plan-identity-gate-6of6` §5 待拍板件）。
- **N6 不动 workspace 隔离维**（ADR-0007 §8 知情降级保持）。

---

## 3. 设计决策（D1–D11；「放弃」列即被否方案登记。行序上 D11 列在 D10 前，因 D5/D9 均引用它）

| # | 决策 | 选定 | 放弃 | 理由（绑事实） |
|---|---|---|---|---|
| **D1** | 角色粒度 | **内置 3 角色 + 一人一角色**（`users.role`，值域闭合） | 角色表 + 自定义角色界面；多角色 `memberships` | F1 `is_admin` 零消费者 ⇒ 需求原话「不同角色看到的功能不一样」用 3 个码即闭合；D9(2026-10-23)「不建 memberships」**无需翻案**，只把「角色降为 `is_admin`」升级为角色码 |
| **D2** | 角色码承载位置 | **RS256 JWT claim**（与 tenant/user 同源同签发点，服务端断言） | ① 每请求回库查角色；② body/query 传 role | ①建不起来：F7 身份门只 4/6 且 KS 零依赖 agent-runtime；②撞 D20（body 不是断言源）。claims 只带**码**不带权限集 ⇒ 「改权限」与「重签令牌」解耦。⇒ **ADR-0015** |
| **D3** | `role → features` 放哪 | **agent-runtime 一处常量表**（`agent_runtime/authorization.py` 新文件） | 入库 `role_permissions`；YAML 配置 | 改映射 = 发版（可审计、可 lint、可 blame），不引入缓存 TTL 与跨实例失效；将来迁库是**纯 expand**（claims 形状不变、消费点不变） |
| **D4** | feature 值域 | **代码枚举，界面只读**；硬要求：**每个 feature 至少一个后端消费点**。❗ **第四轮订正（与 R7 缓建对齐）**：本轮该要求**由专属反证逐格承担**（R3/R4/R5/R10 等，见 §4 反证列），**不是由 lint 承担**——feature↔消费点自检 lint 已缓建至 P2（R7 / §12 瘦身 2）。原写「否则门禁报红」指向一把**本轮不存在的尺**，与 R7 缓建自相矛盾，现删 | 可录入的权限字符串（RuoYi `sys_menu/perms` 形状） | 可录入 = 「配了代码里不存在的点」⇒ 静默失效。此即《观测面硬规矩》#8「新判据必须当场自证能咬」+ #7「量具瞎与账面被抓要在读数上分开」。**缓建不等于放弃**：恢复触发 = 第一个新 feature 入枚举（届时必携 `<<< FEATURE-LINT-UNPARSED` fail-closed） |
| **D5** | 脱敏判定口径 | 本轮就改成**按 feature 判**：`is_masked_role(role, admin_roles)` → `has_feature(role, "data.unmasked")`；**旧函数不留空壳**（D13「不留空壳」同源），它的两组用例随产品代码同批改写（见 §7）；退役 `default_query_role` / `admin_roles`（**含 F16 的 YAML 键 + `state.py:94` + `query_service.py:120` 透传链**） | 「先按角色名匹配，等自定义角色再改」 | F3 那两处现在是「配置常量冒充断言」（值来自 F16 的 YAML）。若延后，N2 触发时脱敏随角色名漂移静默关闭——那是安全门不是体验门，不留地雷。❗ **评审 #4 复现**：`tests/nl2sql_service/test_result_masking.py` 整篇钉的是角色名语义 + `execute_sql` 的 `admin_roles` 透传，本文初版漏列 ⇒ 已补进 §7 |
| **D6** | 数据源凭据 | 库里只存 **`credential_ref`（Secret 里的 key 名）**，口令不进库、不进界面；加新口令 = 运维 `kubectl patch secret`（`05-secrets.yaml:8` 已写此路径） | 库存密文 + KEK/DEK 两层信封 | F11 那条不变量：库一存口令就有**第二份口令材料**、`nl2sql_dbsql.sql`「重跑即收敛」被架空；且 KEK 仍来自 Secret ⇒ **本部署威胁模型下**档位不变、复杂度净增（措辞见 N1 订正）。名字不是秘密，值才是。**三条边界句（评审 #12 要求补，本文接受）**：① 保存时**无法验**任意 ref 是否存在（应用读不到 Secret 对象），首发现 = 下次启动 reconcile ⇒ **界面文案照写「保存不校验，启动才验」**；② 对 `META_DB_DSN`/`DW_DB_DSN` 两个**固定键**可以在保存时就验（清单里键名闭合）⇒ 列为刀 3 的廉价增强；③ `nl2sql_dbsql.sql` 那个 Job **只认两个固定角色** ⇒ 第二个源的 DB 账号 / L1 GRANT / 脱敏视图**没有自动化通路**，已写进 N4 与刀 3 边界 |
| **D7** | 上传通道 | **agent_server 代理一跳**：服务端断言 tenant → 内部 HMAC 签名头 → KS | 浏览器直连 KS | F8 的 `tenant_id` 是 **Form 字段**，直连会把 F9 那个实踩过的 fail-open 面暴露到浏览器侧；代理点可复用 `internal_header.py`（kefu/nl2sql 转发同手法） |
| **D8** | 生命周期接不接 | 接：`kb.upload`（落 DRAFT）与 `kb.publish`（→PUBLISHED）**分属不同角色**，是 feature 门的第一个真实用例 | 只做上传表单，不碰生命周期 | 否则「上传配置」页面与角色体系是两块互不相干的贴图，G1 的真实收益无法验收 |
| **D9** | 缺 role claim 的存量令牌 | **按 `viewer` 兜底** + 首次 WARNING（最小权限，不是拒 401）；❗ **计数口径按评审 #6 订正**：WARNING 按 `(tenant, user)` **首次**记一条，**另走可聚合计数**（metric 或日志计数均可）——因为「per-process 只记一次」会让条数封顶 1，而 R-1 的触发条件「条数 > 0 持续超一个 TTL 周期」**永不可评**。落点：`verify_token` 后的消费侧（`authorization.py` 入口），不是中间件里。❗ **第六轮补（H6）：兜底逻辑只住一个函数**——`authorization.py` 提供单一 `resolve_features(claims: TokenClaims | None)`，**JWT 路径（D9）与 API_KEY 路径（P8，不经 verify_token）均调它**；否则两处各写一个兜底就会漂（P8 说的「不新造第二条口径」靠这个单一实现位兼现，不靠约定） | 直接 401 | N5 之下 enforce 未开，401 会把「升级后旧令牌全失效」变成生产事故。**代价**：必须在读数上能看见「还有多少请求走兜底」，否则兜底会掩盖私钥/公钥配错——与 F9 同族风险，见 §10 Q3（评审 #3 已答：差别在 F9 是**放行**高权限，D9 是**降级**到低权限；方向相反，但同为「静默」） |
| **D11** | **role 进子服务的承载**（评审 #5 指出的真空白，本文初版确实一个字没写；现按本文复取结果定死） | **`X-Internal-Tenant` 内部签名头的 v1 payload 增键 `r`**（= 断言角色码）；**解释只一份**：映射表住在 `agent_runtime/authorization.py`，nl2sql 作为 application 层 **import 它调 `has_feature`**，不得自写 `if role == "admin"`；**头里无 `r`（旧调用方 / API_KEY）⇒ nl2sql 无条件脱敏**（fail-closed）。**签发侧形状（第三轮升级点 1）**：**出站签名单入口**，三层齐备——① 单一实现：agent-core `internal_header.py` 增 `build_internal_headers(tenant, user, role=None, *, soft=False)`，收编 federation `_internal_tenant_header` 的 warn-once 软模式（其私有实现原地退役）。❗ **第四轮补（F21，两个必做项）**：**(i)** 必须同步 `agent_runtime/identity.py:261` 那层**委托包装**（`knowledge_tools.py:145` 经它签）——只改 agent-core 不改包装，该路径**拿不到 `role` 通道**且不报错；**(ii)** 收编范围不止 warn-once，还包括 `knowledge_tools.py:140-147` 的 `except ImportError: pass` **静默不签**（比 warn-once 更弱，须改具名失败或 warn-once，不得原样搬）；② 全局装配：出站收敛 `post_remote(...)`，**F20 九处发送方 + D7 代理全走它**。❗ **第四轮订正（射程）**：原写「agent_server 出站收敛…F20 五处」两处都窄了——**(i)** 发送方实为 **9 处**（漏 exhibition `capabilities.py:366`、KS `:261/:286`、federation `knowledge_tools.py:145`）；**(ii)** **单入口不止 agent_server**：F20 有 2 处在 federation（`async_subagents.py:171` / `knowledge_tools.py:145`），只收敛 agent_server 会让「lint 禁裸 httpx」在 federation 报红、或被迫白名单豁免（= 单入口被绕开，ADR-0015 §6.8 那条）⇒ **两个应用各一个装配点、共用 agent-core 同一实现**；kefu/exhibition 同刀顺手闭环。❗ **与 N7 不矛盾（第四轮澄清）**：N7 不拉进 federation 的是 **skill 级权限接线**（`planners/agentic_runtime_bridge.py:98` 的 `caller_permissions`），本条拉进的是 **出站签名**（`agent/async_subagents.py` / `tools/knowledge_tools.py`）——同一应用内不同件，不得混读；③ 强制门禁：❗ **已拍（2026-11-11 P10=甲：窄门禁）**——不钉 httpx 语法（子服务与外部 API 出站语法不可区分），改钉**签发符号调用点**：`build_internal_headers(` / `sign_internal_header(` 只准出现在两个装配点文件 + agent-core 本体（白名单=装配点本体，非逐项登记制）；盲区「新出站不签」由 R4 E2E（行为级）+ ADR §6.8 复审触发 8 兜住。❗ **第六轮（H1）：原形状（禁裸 httpx 语法）扫描边界未定，照写会大量误报**——applications 下 `AsyncClient(` 实有 **33 处**（22 处测试 + 生产面约 5 处非子服务出站：warehouse/search/skill_loader/evaluation）⇒ **必须先拍 P10 三条边界规则（排除 tests/evaluation、非子服务白名单、子服务出站识别判据），不拍则本条 lint 不得开工** | ① body 透传 role/布尔（撞 D20「body 不是断言源」）；② 只传布尔结论给 nl2sql（把判定权从声明源搬进应用，且仍要选一个传输载体）；③ 转发/重签 JWT 到子服务（要动转发凭据形状 ⇒ 撞 ADR-0008 U3 未决项，比加键重一个量级）；④ ❗ **逐发送方各补一行签头**（第三轮 N-1）——「每处各自实现」反模式（federation 的 `_internal_tenant_header` 就是实物），新服务每接一个就再抄一份 warn-once/每请求现签逻辑 | F17 是这条能成立的根据：payload 已是 `{"t","u","ts"}` JSON、验签用 `.get()` ⇒ **加键向后兼容**（旧验签方忽略新键，签名覆盖整 payload ⇒ 旧钥签不出新头）；KS 的 fork **调同一个 `verify_internal_header`** 且只读 tenant ⇒ **KS 不改代码也不受伤**（但它「带而不用」，要写进 §7，否则将来有人在 KS 自行解释 `r` 就撞 ADR-0015 §6.5）。❗ **对评审 #5 严重级的修正**：风险不在「role 进 nl2sql」，在「role 进 nl2sql 且**各处自写解释**」；把解释收到一处 + lint 禁字面比较，两个要求同时满足 |
| **D10** | 守卫的拒绝响应形状 | 统一 `AppError(403, "FORBIDDEN_FEATURE", <可上屏文案>)`，`feature code` 只进 `details` 不进 `msg`；**不用 `HTTPException`** | 自己新建一套 403 形状；或先 `HTTPException` 后续再改 | 工作区已有一件「入站错误收敛到 `AppError` + `request_id`」在途未入库（见开头 ⚠ 与 R-8）。`feature code` 不进 `msg`：那是把能力清单外泄给未授权调用方（P8 同源）。❗ **前置语义按评审 #14 重新表述**：`AppError`/`details`/`headers` **在 HEAD 的 agent-core 已存在**（`guardrails/errors.py:85` 起）⇒ 刀 1 用它们**不依赖**在途件；所谓前置的实质是 **`identity_middleware.py` / `query_router.py` 两个文件的合并冲突规避**，不是能力缺口。三选一的代价对照已列 §10 Q9，评审选 (a)（先入库），本文接受 |

---

## 4. feature 清单（枚举本体；这 9 格就是三刀的射程定义；❗ 第七轮：kb.config 随模板层砍除移出，10→9）

消费点列**必须同批改代码**。任一格只有清单没有消费点 = 该 feature 是空转齿。❗ **第四轮订正**：本轮该格的判定**由专属反证逐格承担**（见下表「反证」列），**不是「D4 自检当场红」**——那把 lint 已缓建至 P2（R7 / §12 瘦身 2），原句指向本轮不存在的门禁。

❗ **新增「反证」列（评审 #23 接受）**：lint 只能证「feature 码在 `authorization.py` 之外也出现过」，**证不了「守卫存在但被短路」的语义空转**——所以每格必须绑到具体反证号，否则「消费点存在」这句话仍可能是空证。

| feature code | 含义 | 后端消费点（落点） | 反证 | admin | editor | viewer |
|---|---|---|---|:--:|:--:|:--:|
| `chat.run` | 发起问答（SSE 主链路） | `POST /query` 守卫 | R3, R10 | ✓ | ✓ | ✓ |
| `session.history` | 历史与回溯 | `GET /history`、`POST /session/revert` | R3, R10 | ✓ | ✓ | ✓ |
| `data.unmasked` | 问数结果**不做**列脱敏（L3 反向门） | `agent/nodes/execute_sql.py` 脱敏分支（D5 + **D11 承载**） | R4, R9 | ✓ | — | — |
| `sql.train` | 写元知识/范例（**写面**） | `POST /sql/train` | R3 | ✓ | — | — |
| `kb.upload` | 上传文档，落 DRAFT | 新代理端点 `POST /kb/uploads`（D7） | R5 | ✓ | ✓ | — |
| `kb.publish` | 生命周期提审→发布 | 新代理端点 `PATCH /kb/{knowledge_id}/status` | R5 | ✓ | — | — |
| `datasource.manage` | 数据源定义增删改 / 设默认 | 新表 CRUD（§5） | R7, R8 | ✓ | — | — |
| `execution.control` | 执行控制面 7 个动作 | `api/control.py` 各端点 | R3 | ✓ | — | — |
| `human_task.decide` | 人工审批通过/驳回 | `POST /task/{id}/approve`、`/reject` | R3 | ✓ | — | — |

- ❗ **未定义格待拍（评审 #7）**：本表全部格对**未断言调用方**（静态 `API_KEY`，`query_router.py:32` 闸门仍在位、`web` 有 `ApiKeyBox.vue`）的行为**未定义**——它无 claims、因而无 role。不得由本方案默认等效关闭旁路（那是 ADR-0008 U1 的人批范围）⇒ 列为 **P8**。❗ **已拍（2026-11-11）：(a) viewer 兜底**——与 D9 同一条「无断言→最小权限」规则，R10 依此写；现有 API_KEY 问答能力保留（chat.run 在 viewer 集内）

- 集合关系：`admin ⊃ editor ⊃ viewer`；`editor = viewer ∪ {kb.upload}`；`admin = editor ∪ {其余 6 个}`。❗ 第七轮：kb.config 随模板层砍除移出枚举（10→9）。
- `/import`（F13）本轮**不分配 feature**、不进界面：它是既有面，动它要同时改它的凭据形状，超出射程 ⇒ 登记为 §9 风险 R-4。
- 前端拿什么：`GET /auth/me` 返回 `role` + `features[]`（服务端算出，前端**只渲染、不判定**）。F5 那条「`is_admin` 只在 TokenResponse」的失效路径由此关闭。
- **拒绝响应形状**：见 §3 **D10**（守卫统一抛 `AppError(403, "FORBIDDEN_FEATURE", …)`，`feature code` 只进 `details`）。❗ 评审 #14 订正后的前置语义：`AppError` 族在 HEAD 已存在，**能力上不依赖在途件**；前置指的是 `identity_middleware.py` / `query_router.py` 两个文件的**合并冲突规避**（详 D10 / R-8 / §11）。

---

## 5. 表形状与迁移（号位 017，F14）

**runtime 侧** `packages/agent-runtime/agent_runtime/migrations/017_user_role.up.sql`（与 `.down` 成对）：

```sql
-- D1：内置三角色，一人一角色；值域闭合在库层，不靠代码约定
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'viewer';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_domain') THEN
    ALTER TABLE users ADD CONSTRAINT users_role_domain
      CHECK (role IN ('admin','editor','viewer'));
  END IF;
END $$;
-- 回填：原 is_admin 位 → admin；其余由默认值达成（一次性收敛，不双写）
UPDATE users SET role = 'admin' WHERE is_admin AND role = 'viewer';
```

- `is_admin` 列**保留不删**（F5：两处契约用例 + 前端已渲染；删列属破坏性迁移）。语义降级为 `role='admin'` 的等价物，**新代码只读 `role`**；写入点在 `auth_users.create_user` 首账号提权处**同批改**（首账号 → `role='admin'`），advisory lock 沿用 `_SEED_LOCK_KEY`，不新造锁。❗ **第六轮补（H5）：读只读 role，但写必须双写**——`is_admin` 与 `role` 保持等价（`is_admin == (role=='admin')`），因为前端 `auth.ts:220` 读的是 `is_admin`；**4 个读写点同批加 role**（`auth_users.py:248 INSERT` / `:279 SELECT` / `:101/:261/:293 UserRecord`）。**跨刀约束：刀 4 的 `PATCH /users/{id}/role` 也必须双写**（§13 护栏已补），否则两列漂移 ⇒ 屏上与权限不一致。❗ **迁移 017 可施工性已验（第六轮）**：`users` 在 `013:27` 建（`id/org_id/display_name/is_admin BOOLEAN/created_at`）、`016` 补 `password_hash/last_login_at` ⇒ 表存在、`is_admin` 是 BOOLEAN（回填 `WHERE is_admin` 合法）、无 role 列（加列不冲突）。
- **KS 侧**：❗ **模板层砍除（2026-11-11 用户拍板，第七轮）**——`kb_upload_profiles` **不建**（表/collection 均无）；刀 2 上传页的元数据**每次随表单填**（字段同今天 import.html，但收进统一界面 + 服务端断言租户）。砍除依据：用户需求原话是「知识库文档能界面上传」（kb.upload），模板（配一次多处复用 + `kb.config` 门）是方案自加层、非用户需求；F22（四套存储分工、KS 无文档级元数据表）与 F23 取证结论**保留有效**（事实记录）。**恢复触发 = 用户首次表达「不想每次重填元数据」**（纯 expand：建 Mongo collection + 加回 `kb.config` 门 + P3(a) 复活，按 (b) 三档重拍归属）。以下为砍除前的原论证，保留供恢复时复用：❗ **评审 #18（接受）：本文初版只答了「表落哪」，没答「模板属谁」**——上列字段集**无 tenant/org 列**，而 F8 的上传 Form 里有 `tenant_id`（INV-8 ACL 前置）⇒ 模板维度上的隔离语义现在是**未定义**。已并入 **P3** 一起拍（不拍则刀 2 交付一张「跨租户可见」的表）。❗ **第三轮（N-4）+ 第四轮订正（F22）**：KS 实有**四套存储**——MinIO（原文 PDF/图片）/ Milvus（chunk 向量）/ Neo4j（图谱）/ MongoDB（**只存会话历史**），**无关系库**（postgres/psycopg/alembic/migrations/`CREATE TABLE` 零命中；deploy/k8s 无 KS 清单）。❗ **关键事实（F22）：KS 今天没有「文档级元数据表」**——`tenant_id`/`scope_type` 是**附在每个 chunk 向量行上的标量字段**（`node_import_milvus.py` 的 `kb_chunks` schema）⇒ 上传配置模板是**全新实体**，不得假装有现成元数据表可挂。❗ **第四轮：P3(a) 已拍 Mongo collection + `$jsonSchema`** ⇒ 本行「落 KS 自己的库」**定为 Mongo collection，不是关系表**：上列字段集改作 document 字段（`profile_id` 作 `_id` 或唯一索引），**KS 无迁移链** ⇒ collection 名与索引定义进 KS 自己的启动装配（不得假装有迁移）。第四轮已复核零命中：`git grep -c -iE "psycopg|asyncpg|sqlalchemy|alembic|CREATE TABLE" d9fa8eaa -- applications/knowledge-service` ⇒ **rc=1**。❗ **第三轮瘦身**：上列字段集**逐字镜像 F8 Form**——`venue_id/knowledge_id/exhibition_id` 是**逐次上传参数**不是模板参数，不入模板表；`version/status` 若无编辑界面消费则为死列（F2 同族）；模板字段集改「**有消费点的列**」（D4 同纪律），恢复触发 = 第一个模板消费者要它。
- **nl2sql 侧** `datasources`：`id` PK / `label` / `dialect` / `scope_label` / `credential_ref` NOT NULL / `is_default` / `status CHECK IN ('active','saved-not-applied')` / `updated_by` / `updated_at`；默认源用**部分唯一索引** `WHERE is_default` 保证至多一个。**本表不存任何口令形状**（D6），列名上也不得出现 `password` / `dsn`。
- 三条硬纪律（沿用 013/016 文件头既有要求）：幂等 `IF NOT EXISTS` / 不回改已应用文件 / 不可逆项在文件头写「**有意不提供回退**」而不是「尚未编写」（D19 措辞要求）。

---

## 6. 刀次、验收与反证

| 刀 | 内容 | 主要落点 | 体量（估） | PR 切法（<400 行） |
|---|---|---|---|---|
| **1a** 断言源 | `authorization.py`（FEATURES 枚举 + ROLE_FEATURES 常量表 + `has_feature`）；`TokenClaims`/`mint_token`/`verify_token` 加 `role`；登录/注册签发带 role；`/auth/me` 返回 `role+features`；D9 兜底 + **可聚合计数**（D9 订正）；迁移 017；`test_login_no_secret_leakage` **三格**随动 + `test_auth_users` 首账号语义随动 | runtime + agent_server（auth 面） | ≈ 230 | 与 1b/1c 同分支顺序提交，单独可验（R1） |
| **1b** 消费点守卫 | §4 九个端点守卫（统一 `AppError`，D10；**实现形状 = 单一 `require_feature(code)` FastAPI dependency，第三轮升级点 2**——不是逐端点 inline if，漏接 = 无守卫 = R3 反证红）；`_sanitize_identity` 加剔除 `role/features/permissions`（F15）；新 lint 齿（出站单入口禁裸 httpx + 「不接线」机检；feature 自检缓建见 R7 第三轮）；R3/R5/R10 | agent_server | ≈ 170 | 不碰 runtime 契约，可单独回滚 |
| **1c** nl2sql 判定与承载 | **D11 承载**（payload 增键 `r` + **出站签名单入口三层**（D11 第三轮升级点 1，❗ 第四轮射程订正为 **F20 九处**）；发送方清单全改，含 kefu/exhibition/federation 同刀闭环；**F21 两个必做项**：同步 runtime 委托包装 + 收编 `knowledge_tools` 静默不签）；nl2sql import `has_feature`；`is_masked_role` 退役 + `test_result_masking.py` 两组用例改写；F16 四处透传链（YAML 键 / settings 字段 / `state.py:94` / `query_service.py:120`）下线；给 `data_permission:` 段补**未知键 raise**（把 `pool:` 段 `settings.py:222-240` 的既有纪律推广过去） | agent-core + runtime + nl2sql + **federation**（❗ 第四轮：原列三面漏了 federation，而 F20 有 2 处在它里） | ≈ 200（含用例改写；❗ **第四轮预警：九处发送方 + 两应用装配点 + F21 两项 ⇒ 本估值偏乐观，开工前须重算**） | **开工前置 = 现网 YAML 取证（Q6/#25）**，本机不可达 126 ⇒ 该格阻塞时如实标阻塞 |
| **2** 知识库上传面 | agent_server 两个代理端点（`POST /kb/uploads`、`PATCH /kb/{id}/status`，服务端注 tenant + HMAC 转发；❗ **不得挂 console_router**，H3）；`web/` 上传页（❗ **2026-11-11 拍板：模板层砍除**——元数据每次随表单填，无模板页无模板 collection） | agent_server + KS + web | ≈ 340（模板 CRUD + 模板页砍除后重估） | 可拆 2a/2b。**三前置：KS 镜像重建+分发（在册首要待执行项）+ P6 边界 ADR + N-2 三齿随动（C5 ⇒ 2a 先于 2b；新 router 须进 main.py 装配链且 git add，H4）**（P3(b)/R-11 随模板砍除消解，不再前置）。❗ **第六轮发布成本订正（H2）：2b 改 web ⇒ 必须重建 agent_server 镜像**（web 产物经两阶段构建进该镜像，`Dockerfile:12/:29/:81`）⇒ 刀 2 共 **两个镜像**（KS + agent_server），不是只 KS。❗ **第八轮 2a 设计注记**：流式透传（httpx stream，不整体缓冲进内存）+ 显式超时；**大小校验落 KS 侧 100MB（P11 已拍）**，代理层不重复设限（单一真相源）；2b 页面**不含切片配置面**——切片 = `node_document_split.py` 代码常量（`DEFAULT_MAX_CONTENT_LENGTH=2000` / `MIN_CONTENT_LENGTH=500` / `chunk_overlap=0`），调参走 golden 集工程闭环（触发条件见 §14.9 K2） |
| **3** 数据源配置面 | **P7 已拍 A（表为准、YAML 下线）**：`datasources` 表（**部署级，P4 已拍**）；`build_default_registry` 改为按表逐行建注册表（F10）；lifespan 按 `credential_ref` 从 Secret 投影取 DSN 建池；GET/POST CRUD + 设默认；未知 ref / 未知 datasource_id **fail-fast 不静默回落**；F16 的 `app_config.yaml datasource:` 块**退役 + 启动期残留块具名 raise**（R8 单一形状）；`web/` 数据源页 | nl2sql + web + 清单 | ≈ 420 | 可拆 3a/3b。**前置：P4 + P7 已拍毕 ⇒ 拍板格清零**；但 **YAML 下线须与 Q6 现网取证同批**（本机不可达 126 ⇒ 阻塞）。❗ **第六轮发布成本订正（H2）：刀 3 共两个镜像**——nl2sql（代码+YAML）+ **agent_server（3b 改 web）**；另改 web 依赖须同批更 `pnpm-lock.yaml`（`--frozen-lockfile` 是判据） |

❗ **体量账实订正（评审 #15 接受）**：刀 1 原写 ≈380 **不成立**——按本表重拆后三片合计 ≈ **600**（+40 是 D5 透传链，+评审 #3/#4 的四件判据随动，+D11 承载）。原切法（1a/1b）会把四处判据随动与新拍板格堆在同一张 PR 里 ⇒ 必破 400。**不拆到 1c 单独成刀的话，刀 1 会在评审外先红一轮，再把「修红」混进功能 diff**。

**交付价值排序（第三轮，优先保证核心功能）**：增量 1 = 1a+1b（角色断言 + 端点守卫 + `/auth/me` features——用户三条原话第一条的屏面价值）；增量 2 = 1c（**修复今天就坏的核心行为**：F3 现值下所有问数按 `analyst` 掩码 ⇒ admin 经 web 问数也被脱敏；1c 交付「admin 终于看到不掩码数据」+ 出站签名单入口）；增量 3 = 刀 2（2a 代理端点 → 2b 页面，C5 顺序硬约束；模板层砍除后无 KS 存储定案项）；增量 4 = 刀 3。四个增量各自独立可验，不新增拍板格。

**每刀的验收陈述**按 `docs/operations/evidence-format.md` §1 五字段写（rev / 命令 / 读数+分母 / 未跑 / 前置）；**本文不预填任何通过数**（该文件 §1 末尾：“方案文档不欠读数”）。

❗ **1a 施工登记（2026-11-11，HEAD=`5b87f463`）**：
- **改动面**：与 1a 行一致（authorization.py 新建 / identity 五处 / workspace_registry role 上下文 / identity_middleware 三元组 / auth_users 双写 / auth_router 三模型+me / 迁移 017 up+down / 六件测试随动），15 件 +635/−42。
- **计划外随动（如实登记）**：① `test_auth_router.py` UserRecord 位置构造补 `role` + `/auth/me` 端到端断言按 §6 新契约随动（旧钉子是契约变更的必随面，非收窄）；② `agent_federation/api/identity_bridge.py` `_apply` 签名对齐中间件三元组契约（联邦 role 先接住不承载，1c 再接——否则中间件传 3 参即 TypeError）；③ lint 收尾 `730282a5`（上批 `e782db22` 死 import 清除，当时漏跑全仓 ruff）；④ 迁移 017 加 COMMENT（照 016 惯例，§5 语义不变）。
- **验证（rev=5b87f463）**：ruff 全仓 rc=0；`pytest packages/agent-runtime/tests -q` 922 passed, 2 skipped；`pytest tests/governance -q` 521 passed, 1 skipped；agent_server 定向 `-k "auth or identity or login"` 48 passed；federation unit 148 passed；kefu/nl2sql identity 装配 12 passed；`check_doc_sync.py` rc=0。
- **未跑**：agent_server 全套（183 项，仅定向 48）；shared-schemas / nl2sql / knowledge-service / exhibition 套件（本轮无触碰面）；**迁移 017 未在真 PG 上应用**（本机无 DATABASE_URL——SQL 为 §5 原文，runner discover 形状已对齐 016 惯例，126 部署时按 nl2sql-release-checklist 流程验收）。
- **前置**：无（1b 可开工；其九个端点守卫的消费点清单见 §4）。

❗ **1b 施工登记（2026-11-11）**：
- **读数基准**：`git rev-parse --short HEAD` = **`4d2fd313`**；本批读数取**未提交工作区**（HEAD + 13 件 M + 1 件未跟踪新增，`git status --short` 可复核）。按《观测面硬规矩》#6，这属「提交前」读数，**提交后须按 (b) 复取**；不得把本块读数冒充 HEAD 树的判决（#9）。
- **改动面**：agent_server 侧 **14 处**端点守卫（§4「后端消费点」列逐格展开：query 1 / session 2 / sql 1 / control 8 含 `GET /{execution_id}` / human_task 2 写面，两个 GET 读面不挂）；`_sanitize_identity` 剔除面扩为 6 键（F15）；`scripts/lint_architecture.py` 新增 **P15 窄门禁棘轮 + P16 不接线机检**两齿并接入 `main()` 判决；新增 `tests/governance/test_role_feature_gates.py`（18 项反例）；错误码按 §3 D10 定案为 `FORBIDDEN_FEATURE` + `details={"feature": code}`。
- **口径订正（如实登记）**：§6:144「九个端点守卫」/ §12:325「十个守卫」是 **feature 格数**（第三轮 10、第七轮砍为 9）误记为端点数 ⇒ 挂载清单以 §4 消费点列为准 = 14 处，F13:36 的控制面 8 个路径含 GET 读面。§11:297 / §13:353 / §8:204 的「P10 未拍 / 1b lint 齿待 P10」是第六轮拍板前旧注记，按 §8:202「P10=甲」作废；两齿另起 ID **P15/P16**（不撞现有 P10 `from tools.*` 直引齿；R2 是反证编号不是齿 ID）。R7 feature↔消费点自检**缓建至 P2、本批未建**；出站签名单入口三层本体属 **1c**、本批未夹带。P15 基线按现状 5 位钉成棘轮，注记写明「为什么不绑 0」及 1c 收编时的收紧口径。
- **计划外随动（如实登记）**：`test_human_task_api.py`（6 项）与 `test_v3_wiring_assembly.py`（6 项）的裸 `FastAPI()` 最小 app 无 `IdentityMiddleware` ⇒ `asserted_role()` 为 None ⇒ viewer 兜底 ⇒ 12 项在册用例红。按 §7 随动纪律补 `_AdminRoleMiddleware` 断言 admin（**生产装配的等价前置**），断言逐字不变，不删用例 / 不收窄 / 不放宽；`test_capabilities_identity.py` 与 `tests/governance/test_identity_not_in_tool_schema.py` 扩期望集到 6 键（扩集合不是松）。另如实登记：control / human_task 两组端点**未补** `verify_api_key`（避免夹带行为变更），故 `auth.py:85-86`「401 先于 403」的顺序纪律在这两组无载体；R10 默认档按 P8 (a) 为 403，三种例外（enforce 档 / X-API-Key 错 / JWT 验签失败）在反证用例中单列。`_view()` 读面回传 `resume_payload` 等审批载荷，登记为 §9 风险（复审触发 = 出现第二个真实租户或读面需要分级）。
- **验证（命令原样可复制；读数含分母与口径）**：
  `uv run --with ruff ruff check .` → rc=0；`uv run python scripts/lint_architecture.py` → rc=0（20 齿全通过，含 P15/P16）；`uv run python scripts/lint_migration_refs.py` → rc=0 / 违规 0；`uv run python scripts/lint_public_mirror.py` → rc=0 / 违规 0、既有警告 1（P-4 登记项零命中）；`uv run python scripts/lint_graph_state_boundary.py` → rc=0 / 违规 0；`uv run python scripts/check_doc_sync.py` → rc=0 / 0 警告。
  `uv run pytest tests/governance/test_role_feature_gates.py -q` → **18 passed**；`uv run pytest tests/governance -q` → **539 passed, 1 skipped**；`uv run pytest applications/agent_server/tests -q` → **183 passed**；`uv run pytest packages/agent-runtime/tests -q` → **922 passed, 2 skipped**；`uv run pytest -q -m "not requires_pg"` → **1581 passed, 1 failed, 10 skipped, 29 deselected**（唯一红见下）；其余 session：`packages/shared-schemas/tests` 31 passed、`applications/agent_federation/tests` 192 passed/1 skipped、`kefu-service` 49 passed、`exhibition-agent` 381 passed/11 warnings、`knowledge-service` 416 passed/7 skipped、`nl2sql-service` 235 passed/8 skipped、`uv run --extra otel pytest tests/observability -q` 18 passed。合计覆盖 Makefile `test` 的 9 个标准 session + 1 个 otel session。
  新门禁非空转自证（硬规矩 #8）：P15/P16 各带「真树零违规 + 下限断言（真面参与判决）／合成违规能咬／解析失败或扫描空报 `<<< SIGN-SITE-UNPARSED`、`<<< NO-WIRING-UNPARSED` fail-closed／`main()` 被 monkeypatch 成违规时 rc=1」，18 项全过。
- **既有红（不得读成已验证、不得越界修）**：`tests/api/test_query_error_sanitization.py::test_stream_error_frame_is_sanitized` = `KeyError: 'error'`。定性：HEAD 的 `stream_error_frame` 返回 `{type, code, msg, request_id}`（`packages/agent-core/agent_core/guardrails/errors.py:145` 起），该用例 :114 仍断言 `data["error"] == SANITIZED_5XX_MSG`，是 `e782db22`「入站错误信封收敛」批未随动的遗留；本批对 `errors.py` 与该测试件 **零改动**，`query_router.py` 仅加 import + `_feature` 两行（`git diff` 可复核），且请求返回 200 + error 帧（守卫已放行，`chat.run` ∈ viewer）⇒ 与 1b 守卫无关。按红线不删用例 / 不收窄断言凑绿，登记为既有债交错误信封批后续轮处理。
- **体量账实订正（如实登记）**：`git diff --stat`（13 件 M）= **+394/−26**，另有 `tests/governance/test_role_feature_gates.py` 新增 **292 行** ⇒ 实物约 **686 行新增**，超 §6:144 的 ≈170 估值与「PR <400 行」切法建议。成因是两条 lint 齿（176 行）+ 反例单测（292 行）+ 12 项在册用例随动。本批尚未提交，若守 400 行约束可拆成「守卫本体 + 随动」与「两齿 + 反例单测」两个连续 commit；**不预填通过数**，由提交环节拍。
- **入库态（硬规矩 #11/#13）**：`test_role_feature_gates.py` 当前 `??` 未跟踪 ⇒ 作为判据本体**现在还不能当批准依据**；提交时须精确 `git add` 全内容（不得 `git add -N` 空 blob），并当场 `git cat-file -s` 复取非空。`scripts/lint_architecture.py` 已入库、门件调用点只指该入库件，无「入库≠被读」分支。
- **未跑 / 前置**：`make eval` 未跑（启发式评测非本批改动面）；迁移 017 未在真 PG 应用（沿用 :159）；126 现网取证、KS 与 agent_server 两镜像构建分发不可达 ⇒ 1c / 刀 2 / 刀 3 的阻塞**未解除**。本批读数所需前置仅 `uv sync --all-packages --extra dev`，无外部服务。
- **交 1c / 后续（本批未修，不得当作已具备）**：`authorization.py` 的 `has_feature` 对未知/None 返回空集且不触发 D9 WARNING/计数（与 `effective_role` 两套兜底口径；1b 路径先过 `effective_role` 故正常，1c 直调须统一）；`editor` 值域当前无产生路径（刀 4）；D9「可聚合计数」仅进程内 int、无 metrics 导出面（R-1 复审条件暂无采集面）；P6 边界 ADR 与 ADR 索引的处置见下方「1b 后续补记」，2a 的 KS 镜像重建+分发硬前置仍未清。

❗ **1b 后续补记（2026-11-11，同一 rev `4d2fd313` + 工作区；读数绑本条，换 rev 复取）**：
- `docs/adr/0016-roadmap-18-kb-proxy-boundary-exception.md` 已按 §8 P6 成文：逐行引 #18 原文（`docs/plans/plan-production-delivery-roadmap-2026-10-09.md:94`）、`docs/adr/0010-ui-stack-selection.md:29/:30/:52`、`docs/plans/plan-frontend-stack-selection-2026-10-27.md:14/:90/:92` 与 `docs/operations/evidence/2026-10-29-roadmap-18-console/readings.md:16`；给出豁免/修订/撤回三立场 + 消费方审计（C5/console_router 路径集/KS 入口）+ 代价 + 6 条复审触发。**边界立场待用户拍板（D2，`AGENTS.md:26`）**，本件不代拍 ⇒ 状态行标「待拍板」，拍板前不得引为「2a 已获批准」，亦不构成 2a 放行（KS 镜像重建+分发仍属 126 部署环节）。
- `docs/README.md` §2 活文档层索引已按 `:43-46` 先例补登 `0015`/`0016`（此前登记到 0014 为止）。⚠ `scripts/check_doc_sync.py` 只判三篇根文档的反引号引用路径、**不判该索引齐全**（`docs/README.md:214`）⇒ 索引完整性为人工判，不得拿门禁绿当证明。
- §8 P6（`:229`）、§11 #21（`:302`）、§13（`:411`）、§14.5（`:425`）里「第三份尚未撰写 / 本文至今未逐行读那两件」均为**本日早些时候的快照**；按本仓「原文保留 + 追加订正」惯例不改写历史行，现值以本补记与 ADR-0016 为准，引用前先复取。
- 根套件既有红 `test_stream_error_frame_is_sanitized` 已按统一错误信封**扩面随动**（`tests/api/test_query_error_sanitization.py`）：从只取 `data["error"]` 改为钉 `{type, code, msg}` 且 `msg == SANITIZED_5XX_MSG`，属契约形状变更后的判据扩面（不删用例 / 不收窄 / 不放宽）。该件此前属 `e782db22` 错误信封批未随动遗留，与本轮 1b 守卫无关；复跑读数见下。
- **新增读数（实测，非预填）**：`uv run pytest tests/api/test_query_error_sanitization.py -q` → **2 passed**；`uv run pytest -q -m "not requires_pg"` 全量复跑 → **1582 passed / 10 skipped / 29 deselected / 0 failed**（`ROOT_SESSION_OK`）；ruff / `scripts/lint_architecture.py`（20 齿）/ `scripts/check_doc_sync.py` 复跑均 rc=0。⇒ 上方 1b 登记块里的根套件读数「1581 passed, 1 failed」与「既有红」段是**当时快照**，既有红已由本补记关闭，不得当现值引。**未跑 / 前置**：`make eval` 仍未跑；126 现网取证与两镜像构建分发仍不可达 ⇒ 1c / 刀 2 / 刀 3 阻塞未解除。

❗ **1b 后续补记 2（2026-11-12；读数绑本条，HEAD 仍 `4d2fd313`，换 rev 复取）**：
- **事实订正（推翻旧结论）**：按《观测面硬规矩》#9 现取，不引 1a/1b 登记里的旧读数 —— `ping -n 2 -w 1000 192.168.100.126` = **2/2 收 / 0% loss / 1–4ms**；`…241` = **2/2 收 / 0% loss / ≤1ms**；`ssh -o BatchMode=yes -o ConnectTimeout=8 root@192.168.100.126 "hostname; echo SSH_READONLY_OK"` = **`ambari03` / `SSH_READONLY_OK`**（全程只读、零写操作）。⇒ 1a `:159`、1b `:174`/`:182` 里「本机不可达 126 / 现网取证不可达」**整条不成立**；那些行是当时快照，按「原文保留 + 追加订正」惯例不改写，但不得当现值引。
- ⚠ **可达 ≠ 可开工**：网络与 SSH 只读通道可用，只解除了「物理不可达」这一条。1c 的 **Q6 现网 `app_config.yaml` 取值**、刀 2 的 **KS 镜像重建 + 分发**、刀 3 的 **YAML 下线同批** 均**未做**，且都涉及现网写操作（build / distribute / kubectl apply）⇒ 按 `AGENTS.md` D2/D3 须人批，本轮不擅自执行；迁移 017 真 PG 应用亦未做。
- **补齐此前「未跑」格**：`uv run python eval/run_eval.py --fail-below 0.8` → **15/15 = 100.00%**（`EVAL_OK`）；`uv lock --check` → **Resolved 285 packages / `LOCK_OK`**；`uv run --extra otel pytest tests/observability -q` → **18 passed**（`OTEL_OK`）。⇒ `make ci` 的 lint / test / eval 三段加 `uv lock --check` 已全部实跑通过，`make eval` 不再是「未跑」。
- **入库态（硬规矩 #6/#11/#13）**：17 件交付物已**精确 `git add`**（逐路径显式列出，未用 `git add -A`、未用 `git add -N`）；`git status --short` 现值 = 15 件 `M ` + 2 件 `A `、**零 `??`**。两件新增 `git cat-file -s :<path>` 均**非零**（现值由该命令现取，不写死；排除 `e69de29b` 空 blob）；`scripts/check_doc_sync.py` 按**索引树**基准复跑 rc=0（#6 (a) 的合法答案）。⚠ **尚未 commit** ⇒ 新克隆仍拿不到，批准效力须提交后按 #6 (b) 复取；索引树 sha 由 `git write-tree` 现取，不写死（后续文档随动会改变它）。
- **体量订正**：1b 登记块「13 件 M / +394/−26 / 686 行」是当时快照；现值以 `git diff --cached --stat` 与 `git write-tree` 现取为准（17 件 = 15 件 M + 2 件新增，新增件全文计入）。超「PR <400 行」建议仍成立，拆两个连续 commit 的选项不变。
- **P6 裁定（2026-11-12，用户批示「全局治本，但又不过度设计，优先核心内容」）**：`ADR-0016` 取 **乙的最小形态 = 射程裁决** —— #18 结案（阶段 3 验收判据、适用期已过，不改写原文）、选型件 `:90` 的误延伸句由该件裁决覆盖而不连锁改文档、产品化边界按 D7 四条判据（服务端断言 tenant / HMAC 转发 / 不新建数据模型 / 转发既有入口），防扩张复用已有护栏（D20/R5 反证、P15、C5）而**不新增 lint 齿**。不取甲（刀 3 的 `datasources` CRUD 与刀 4 管理面会反复撞同一条纪律 ⇒ 例外清单无收口）。§8 P6 / §11 #21 / §13 / §14.5 里「第三份尚未撰写 / 立场待拍板」以本条为准。
- **仍需人做的格子（结构上不能由 AI 自动完成）**：① 提交 commit 的明确指令；② 现网写操作（镜像构建 / 分发 / apply）的人批授权；③ Q6 现网只读取证虽已无物理阻塞，仍需指定开工刀次。三者齐备后 1c / 刀 2 / 刀 3 才能按 §6 逐刀开工 —— **不得把「可达」或「ADR 已决」读成「已放行」**。

❗ **补记 3 · Q6 现网取证（2026-11-12；读数绑 Pod `GIT_REV=d9fa8eaaf241797c5dd26ead620dad7ce23dd864`）**：
- **通道**：`ping` 126/241 = 0% loss；`ssh -o BatchMode=yes root@<internal-host-126> "bash -s"` 跑两段只读脚本（`.tmp-scratch/` 临时件、取证后删除）。全程**零写操作**，只输出对象名 / 键名 / 非秘密 CM 值 / 文件哈希 / GIT_REV，**不输出 Secret、DSN 或 LLM key 的值**（照 `nl2sql-release-checklist.md` §2 纪律）。
- **现网形态（推翻 `nl2sql-release-checklist.md` §1 的 2026-10-28 快照）**：`agent-platform` / `nl2sql-service` / `postgres` / `valkey` 四个 Deploy 均 `READY=1`、Pod 全 Running（落 `ambari02`）；镜像 `agent-platform:dev`、`nl2sql-service:dev`、`valkey/valkey-bundle:9.1.2`；`agent-platform-secrets` 已有 `META_DB_DSN`/`DW_DB_DSN`/`VALKEY_URL`，`observability-keys` 已有 `INTERNAL_HMAC_KEY` ⇒ 该清单的落差 3/4/5/6 **已闭合**，**nl2sql-service 已上线**（不是「镜像从未构建」）。
- **Q6 核心判据**：现网镜像内 `applications/nl2sql-service/nl2sql_service/conf/app_config.yaml` 的 sha256 = `b60e8302d0a5f010109e38581918b2391dcbb0f8494493362146467cdec7cd72`；`git show d9fa8eaa:<同路径>` 的 blob sha256 **逐字相同**。`datasource:`（`id: "dw"` / `label: ""` / `dialect: ""`）与 `data_permission:`（`sensitive_columns: []` / `result_masking_enabled: true` / `mask_keep_chars: 1` / `admin_roles: ["admin"]` / `default_query_role: "analyst"`）两段逐字一致 ⇒ **现网 YAML 未被热改**。
- **角色值的真实来源**：CM `agent-platform-config` 现值 `NL2SQL_DEFAULT_QUERY_ROLE=analyst`、`NL2SQL_RESULT_MASKING_ENABLED=true`、`NL2SQL_SENSITIVE_COLUMNS=["users.phone"]`、`NL2SQL_DATASOURCE_ID=dw`；`ADMIN_ROLES` **无** CM 注入 ⇒ 只吃镜像内 YAML。⇒ 1c / 刀 3 下线 YAML 角色键时**必须同批处理 CM 的 `NL2SQL_DEFAULT_QUERY_ROLE`**，否则残留键变成「配了没人读」（R4 第二格 / R8 要封的形状）。
- **结论**：Q6「现网 YAML 取证」前置**已解除** —— 下线不会丢现网改过的值（现网值 = 仓库 `d9fa8eaa` 值），CM 覆盖值已取全。1a `:159`、1b `:174`/`:182`、补记 2 里「本机不可达 126 / 现网取证不可达」均为历史快照，以本条为准。
- **仍未做 / 不得读成已放行**：1c 代码、刀 3 的 YAML 下线、镜像构建 / 分发 / `kubectl apply`（D3 人批）；本轮对集群**零写操作**，亦未改任何清单。

❗ **补记 4 · 1c-a 承载层施工（2026-11-12；读数绑 `4d2fd313` + 工作区，换 rev 复取）**：
- **射程**：只做 D11 的「role 承载通道」，**不做消费侧**（签发带 role / nl2sql 判定 / F16 下线均未在本批）⇒ **接线 ≠ 启用**，不得把本条读成「admin 问数已不脱敏」。
- **改动面**（4 件产品 + 3 件判据）：`packages/agent-core/agent_core/internal_header.py` payload 增可选 `r`、抽 `_decode_payload` 单一验签、新增 `verify_internal_header_with_role`（三元组）；`packages/agent-runtime/agent_runtime/identity.py` 委托层同步 sign 的 role 参数 + 三元组验签；`identity_assembly.py` 新增 `verify_internal_header_with_role_if_configured` 并让门卫用它（**保留二元组版给存量调用方**）；`identity_middleware.py` 内部头路径宽容解包 2/3 元组，把 role 接进 1a 已有的 `_run` 三元组 ⇒ 复用 `nl2sql-service:96` 的既有装配，**不新建验签面**（符合「不过度设计」）。
- **兼容性（F17 / ADR-0015 §4.2）**：`verify_internal_header` **保持二元组不变**，KS fork 零改动；`r` 只在签发方显式给值时写入；旧验签方 `.get()` 忽略新键；无 `r` 时三元组返回 `role=None` ⇒ 消费侧按最小权限。⇒ 滚动升级窗口「新签发×旧验签」与「旧签发×新验签」两格都成立。
- **判据随动（扩断言，不删用例）**：`packages/agent-core/tests/test_internal_header.py` 加 4 格（带 r 往返 / 旧头 role=None / 旧验签方忽略 r / 篡改 r 沿用旧签名必红）；`tests/governance/test_internal_header_contract.py` 加 core↔runtime 三元组互验；`packages/agent-runtime/tests/test_identity_assembly.py` 把装配函数身份断言扩到新三元组函数，并加 role 承载 / 旧头兜底 / 撤密钥三格。
- **验证**：`uv run pytest packages/agent-core/tests -q` → **374 passed / 8 skipped**；`packages/agent-runtime/tests` → **922 passed / 2 skipped**；`tests/governance` → **540 passed / 1 skipped**；ruff、`scripts/lint_architecture.py`（20 齿）、`scripts/check_doc_sync.py` 全 rc=0。
- **下一刀 1c-b 必须整批同做，不拆**：① `capabilities.py` 问数出站签头带 `asserted_role()`；② `query_service.py` 把 role 注入 state；③ `execute_sql._apply_masking` 改 `has_feature(role, "data.unmasked")` + `is_masked_role` 退役 + 两组用例改写；④ `authorization.has_feature` 统一值域收敛与 D9 计数（1a 遗留：子服务直调会拿空集且不触发计数）；⑤ F16 四处下线（YAML 两键 / settings 两字段+override / state 两键 / query_service 两注入）+ CM `NL2SQL_DEFAULT_QUERY_ROLE` 与 `30-nl2sql-service.yaml` env 同批 + `data_permission:` 未知键 raise（照 `pool:` 段纪律）；⑥ 测试随动约 8 件。**拆开做会留下两种半成品**——「YAML 键配了没人读」与「role 到了却仍按 analyst 脱敏」，故不拆。
- **根套件复跑 + 一格 flaky 定性**：`uv run pytest -q -m "not requires_pg"` → **1586 passed / 1 failed / 10 skipped / 29 deselected**。唯一红 `tests/durability/test_pg_durability.py::TestV1FencingGeneration::test_old_generation_checkpoint_rejected`（`await own.acquire(...)` 得 `False`）：该用例用 **10ms lease + `asyncio.sleep(0.02)`** 等过期（`:424`/`:433`），与内部头 / 身份装配零关联；单独复跑 `uv run pytest tests/durability/test_pg_durability.py -q` → **23 passed**、该单用例 → **1 passed** ⇒ 定性为**时间敏感偶发 flaky**，非本批引入。按红线不删用例 / 不放宽 sleep / 不改断言凑绿，如实登记交后续轮（根治需改该用例的时序契约，属判据变更）。除该格外全量 1586 项通过。另跨服务 8 个 session 全绿：agent_server 183、federation 192/1 skipped、kefu 49、KS 416/7 skipped、nl2sql 235/8 skipped、exhibition 381/11 warnings、shared-schemas 31、`tests/nl2sql_service` 214/1 skipped。
- **仍未做**：1b 与本批的提交（均尚未 commit）、现网写操作（D3 人批）。

❗ **补记 5 · 1c-b 消费侧施工（2026-11-12；读数绑 `4d2fd313` + 工作区，换 rev 复取）**：
- **交付的核心行为**：admin 经 web 问数不再被脱敏。链路 = `capabilities.py` 问数出站签 `X-Internal-Tenant` 带 `r` → `IdentityMiddleware` 三元组断言 → `QueryService` 把 `asserted_role()` 注入 state → `execute_sql._apply_masking` 用 `has_feature(role, "data.unmasked")` 反向门 ⇒ admin 看全量、viewer / 缺 r 掩码（fail-closed）。
- **改动面（15 件）**：`authorization.py` 让 `has_feature` 统一值域收敛 + D9 计数（关闭 1a 遗留的两套兜底口径）；`capabilities.py` 问数出站签头带 role，缺 HMAC 密钥 / 签发失败 ⇒ 不带头（nl2sql 无 r ⇒ 无条件脱敏），不把问答主链路打成 503、警告按进程首次去重；`query_service.py` / `state.py` 把 `user_role` + `admin_roles` 换成 `role: str | None`；`execute_sql.py` / `result_masking.py` 判定改 feature 集、`is_masked_role` 退役（模块不再解释角色词汇表）；`app_config.yaml` / `settings.py` 下线两键 + 两字段 + 两 override，并抽 `_data_permission_overrides()` 给该段补**未知键具名 raise**（照 `pool:` 段纪律）；`deploy/k8s/00-config.yaml` / `30-nl2sql-service.yaml` 同批下线 CM 键 `NL2SQL_DEFAULT_QUERY_ROLE` 与 Deployment env `DEFAULT_QUERY_ROLE` ⇒ 无「配了没人读」残留；`scripts/lint_architecture.py` 的 P15 基线 +1 位（`capabilities.py`），注明是**收编前登记**、完整单入口收编时须收紧，第 7 位仍报红。
- **判据随动（扩断言，不删用例 / 不收窄）**：`test_result_masking.py` 两组输入从角色名改 feature 语义（`mask_value` / `mask_sensitive_columns` 两组逐字不动）并加「缺 r fail-closed」「D9 计数 +1」两格；`test_authorization.py` 未知码用例改为「原语仍空集 / 判定收敛 viewer / 计数 +2」；`test_nl2sql_service_manifest.py` 实走用例扩到钉住 Settings / CM / env 三处下线；`test_settings_precedence.py` 加 `data_permission` 合成违规（残留键 / 段非映射必红）与真面判决两格（硬规矩 #8）；`test_state_schema_wiring.py` 因 `_apply_masking` 新读未声明的 `user_id` 报红 ⇒ 改用已声明的 `tenant_id`，**判据本身不动**。
- **验证（五字段）**：rev = `4d2fd313` + 未提交工作区，提交后按 #6 (b) 复取。`uv run pytest -q -m "not requires_pg"` → **1589 passed / 10 skipped / 29 deselected / 0 failed**；其余 12 个 CI session 全绿：federation 192/1 skipped、kefu 49、KS 416/7、exhibition 381/11 warnings、nl2sql 235/8、agent_server 183、shared-schemas 31、agent-core 374/8、agent-runtime 922/2、`tests/nl2sql_service` 216/1、`tests/deploy` 79、otel 18。`uv run python eval/run_eval.py --fail-below 0.8` → 15/15 = 100%；`uv lock --check` → 285 包；ruff + `lint_architecture.py`（20 齿）+ `check_doc_sync.py` + `lint_migration_refs.py` + `lint_public_mirror.py` + `lint_graph_state_boundary.py` 全 rc=0。**未跑**：迁移 017 真 PG 应用、126 现网写入、真 nl2sql 服务的 HTTP E2E（R4 E2E 变体待环境）。
- ⚠ **部署硬前置（由补记 3 的 Q6 实取导出）**：现网镜像内 `app_config.yaml` 仍是 `d9fa8eaa` 版、**含** `admin_roles` / `default_query_role`（sha256 与仓库该 rev 逐字一致）。新代码的 `data_permission:` 未知键 raise 在旧镜像上会**启动期报错** ⇒ 1c-b 代码必须与 **nl2sql 镜像重建 + 分发**同批发布，不得单独 apply 代码或只改清单（P7「YAML 下线 = 一次 build+distribute 发布列车」的实物依据）。该动作属 D3 人批，本轮未做。
- **按「不过度设计」缓建（如实登记，不得读成已具备）**：F20 九处发送方全改、F21 两项（委托包装同步 / `knowledge_tools` 静默不签）、完整「出站签名单入口三层」。当前只有问数主链路签 `r`；其他出站仍按旧形状，nl2sql 侧无 `r` ⇒ 无条件脱敏（fail-closed，不产生越权）。P15 基线注记已写明收紧触发。
- **仍未做**：提交、现网镜像重建分发与 `kubectl apply`（D3）。

❗ **补记 6 · 部署态核验（2026-11-12 06:06 UTC；读数绑现网 Pod `GIT_REV=d9fa8eaaf241797c5dd26ead620dad7ce23dd864`、本地 `HEAD=4d2fd313cc013dcdf55226a5fccdd6ce038c0820` / 索引树 `bc93a039a5b318f19f422e1d6eae5f509c457b8e`，换 rev 复取）**：
- **结论：最新代码【未部署】，且连 1a 都未部署**。现网两个业务 Pod 的 `/srv/agent-platform/GIT_REV` 均为 `d9fa8eaa…`；`git merge-base --is-ancestor d9fa8eaa HEAD` = True、`git rev-list --count d9fa8eaa..HEAD` = **6**，本地 HEAD `4d2fd313` 与 37 件暂存树 `bc93a039` 均未进现网。
- **只读判据表**（本轮三次 `ssh -o BatchMode=yes root@<internal-host-126> "bash -s"` 脚本，`.tmp-scratch/deploy-probe*.sh` 取证后删除；全程**零写操作**，不输出 Secret / DSN / 数据行）：
  | 判据 | 本地最新 | 现网实测 |
  |---|---|---|
  | 1a 符号 `ROLE_FEATURES` / `effective_role` / `bind_role_context` / `require_feature` / `asserted_role` | 全在 | Pod 内 **5 个零命中** |
  | 1b 符号 `FORBIDDEN_FEATURE` / `check_internal_header_sign_sites` | 全在 | **零命中** |
  | 1c-a 符号 `verify_internal_header_with_role` | 在 | **零命中** |
  | 1c-b 符号 `_data_permission_overrides` | 在 | **零命中** |
  | 迁移 `017_user_role.up/down.sql` | 仓库有 | 镜像内 **零命中** |
  | 真 PG `users.role` 列 | 017 待应用 | `psql \d users` 7 列中**无 role** |
  | `app_config.yaml` 角色键 | 已删 + 未知键 raise | `:91/:92` 仍为 `admin_roles: ["admin"]` / `default_query_role: "analyst"` |
  | Deploy / Pod | — | 4 个 Deploy READY 1/1；`agent-platform` Pod 起于 2026-11-10T03:47:09Z、`nl2sql-service` 起于 2026-11-11T11:16:02Z（均早于本轮施工）；镜像 tag 仍 `*:dev`；`nl2sql-service rollout history` 仅 **REVISION 1** |
- **量具瞎定性（硬规矩 #7）**：第二次探测用 `python3 -c ... sqlalchemy` 查 PG 列 → `ModuleNotFoundError`（应用容器无该包），command exit 1 但**这不是读数**、不能当成「无 role 列」的证据；改用 postgres Pod 内 `psql -U ... -d ... -c "\d users"` 复取成功（只输出表结构、无数据行）⇒ `users` 表实为 `id / org_id / display_name / is_admin / created_at / password_hash / last_login_at`，**确无 `role`** ⇒ 迁移 017 未应用。
- **部署前置（顺序不可逆，全部属 D3 人批；本轮未执行、对集群零写操作）**：
  ① **先提交**：37 件仍暂存、未 commit ⇒ 镜像里根本没有新代码。按「PR <400 行」建议拆 2–3 个 commit（1b / 1c-a / 1c-b+文档）。
  ② **真 PG 应用 `017_user_role.up.sql`**：缺 `role` 列时 1a 的 6 参数 INSERT / 6 列 SELECT 会直接报错 ⇒ 迁移必须先于或同批于 1a 代码，且是不可逆 DB 变更。
  ③ **重建两个业务镜像**：`agent-platform:dev`（1b 改 agent_server + 公共层）、`nl2sql-service:dev`（1c-b 改 nl2sql + agent-core/runtime 公共层）；1c-a 改的是 `packages/*` 公共层，**两个镜像都含该层，不能只重建一个**。
  ④ **清单同批 apply**：`deploy/k8s/00-config.yaml`（删 `NL2SQL_DEFAULT_QUERY_ROLE`）与 `30-nl2sql-service.yaml`（删 `DEFAULT_QUERY_ROLE` env）必须同批 —— 只删 CM 键而不删 Deployment 的 `configMapKeyRef` 会让 Pod 进 `CreateContainerConfigError`。
  ⑤ **镜像内 YAML 必须是新版**：现网镜像 `app_config.yaml` 仍含两个旧角色键，1c-b 的 `_data_permission_overrides()` 对未知键具名 raise ⇒ 旧 YAML + 新代码会在**启动期**直接报错（补记 5 的部署硬前置，Q6 实取导出）。这是「YAML 下线 = 一次 build+distribute 发布列车」的实物依据。
  ⑥ **分发到节点并 rollout**：`nl2sql-service` 当前从未重新 rollout（REVISION 1），需确保新镜像真被拉起而不是复用旧 tag 缓存。
- **部署后须按硬规矩 #6 (b) 复取**：Pod `GIT_REV` = 新 commit sha、上述 8 个符号全部命中、`users.role` 列存在、镜像内 `app_config.yaml` 旧键零命中、两个 Deploy READY 1/1、根套件与 `make eval` 在部署态复跑。**未复取前不得写「已部署 / 已验证」**；「本机全绿 / 已暂存 / 已暂存进索引」都不等于部署。
- **未跑**：真 PG 迁移、镜像构建 / 分发、`kubectl apply`、部署态 E2E（R4 E2E 变体）。

❗ **补记 7 · 部署前本机预检与下线键清尾（2026-11-12；读数绑 `HEAD=4d2fd313` + 工作区，换 rev 复取）**：
- **动机**：补记 6 判定「最新代码未部署」，其发布列车第 ④⑤ 步要求 CM 键 / Deployment env / 镜像内 YAML 三者同批。本轮**不碰现网写操作**，只做本机可完成的清尾，避免发布时踩「配了没人读」或「Deployment 引用已删 CM 键」。
- **既有门禁复核（无需另造齿，不过度设计）**：`tests/deploy/test_nl2sql_service_manifest.py:322` 的 `test_configmap_actually_carries_the_referenced_keys()` 钉「Deployment 每个 `configMapKeyRef.key` 都在 CM data 里」；`tests/deploy/test_k8s_manifest_wiring.py:239` 的 `test_configmap_has_no_dead_keys()` 钉「CM 无死键」，`:902-905` 另有合成违规自证 ⇒ 补记 6 担心的「只删 CM 键不删 Deployment 引用」在仓内**已有判据可咬**，不重复建。
- **清掉 3 处真实残余（不是登记文字）**：① `applications/nl2sql-service/.env.example:63-66` 仍带 `ADMIN_ROLES=["admin"]` / `DEFAULT_QUERY_ROLE=analyst` ⇒ 照模板生成 `.env` 会让已下线字段重新变成「配了没人读」；删两键并留下线说明。② `applications/nl2sql-service/README.md:100/:102/:125` 仍写「非 admin 角色」「角色来自服务端断言 `DEFAULT_QUERY_ROLE`」及配置清单里的该键 ⇒ 改为「无 `data.unmasked` 能力」「角色由内部签名头 `r` 承载 + `has_feature` 单一解释」，配置清单移除该键。③ `tests/nl2sql_service/test_query_rate_key.py:53/:56` 的 MagicMock 桩仍设 `s.default_query_role` / `s.admin_roles` ⇒ 删两个死桩属性，其余桩属性与断言逐字不变。
- **新增防回流判据**（`tests/nl2sql_service/test_settings_precedence.py`，硬规矩 #8 双自证）：`test_retired_role_keys_absent_from_env_template()` 真读现版 `.env.example` 并要求 `SENSITIVE_COLUMNS` 在键集内（**真面参与判决**，不是扫不到所以绿）；`test_retired_role_key_gate_can_bite()` 往模板形状注入两个旧键，断言判据同时命中（**合成违规能咬**，注释里的旧键不算）。
- **验证**：`uv run --with ruff ruff check .` → rc=0；`uv run pytest tests/nl2sql_service -q` → **218 passed / 1 skipped**；`tests/deploy` → **79 passed**；`applications/nl2sql-service/tests` → **235 passed / 8 skipped**；`scripts/check_doc_sync.py` / `scripts/lint_architecture.py`（20 齿）rc=0。`git grep -n -E "^(ADMIN_ROLES|DEFAULT_QUERY_ROLE)="` → **活文件零命中（NONE）**。全仓文件系统扫描另有 3 处命中，全部位于 `.tmp-scratch/<历史树快照>/applications/nl2sql-service/.env.example`（`git ls-files --error-unmatch` 均为 False、gitignored、不入库不进镜像），是历史取证快照副本**不是活配置**，按「历史快照不回填、不改写」惯例不处置。
- **未做 / 不得读成已放行**：提交、真 PG 迁移 017、镜像构建分发、`kubectl apply`（D3 人批）。现网仍为 `d9fa8eaa`（补记 6 读数），本轮对集群**零写操作**；本机全绿 ≠ 已部署。

**十条反证**（缺任一条，对应那格就是空转齿；均为**合成违规 → 期望非零或行为翻转**）：

| # | 反证 | 封住的事实格 |
|---|---|---|
| **R1** | 不带 `role` 的旧令牌照常被验签通过 → 得到 `viewer` 能力集；断言项为「**兜底计数 ≥ 1 且能力集 = viewer**」（评审 #6：不再断言「恰好一条 WARNING」，否则与 D9 新口径自相矛盾） | F4 claims 无 role 位；D9 兜底 |
| **R2** | ❗ **按评审 #2 改写**：不再是「给 skill 声明 permissions 并分两次调」——那三个形状已被在册用例钉住（`packages/agent-runtime/tests/test_policy.py:106`、`tests/planner/test_policy_validator.py`），且刀 1 根本没有接线项（F19）。改为**机检登记**：lint 断言本轮**不接线**（`capabilities.py` 与两应用装配层不得出现 `permissions=` 声明，违者红并报具名理由）+ §3/§6 删掉一切可读成「接上权限引擎」的表述（已改，见 N7） | **F2 引擎在、声明面空** ⇒ 不先把「没接线」写成齿，“接上权限引擎”会被下一轮读成已具备 |
| **R3** | viewer 令牌调 `POST /sql/train` → 403，且**该请求一行都不落**（不是先写后回滚） | D4 消费点必须真拦 |
| **R4** | ❗ **按评审 #9 改写**（原第二半句是空证：`admin_roles` 键被 D5 删掉后，配个不存在的名字→行为本来就不变，静默忽略也满足它，封不住任何东西）。现改为两格：**正向**——admin 不掩码 / editor 掩码；**残留**——`app_config.yaml` 里留着 `admin_roles` 或 `default_query_role` → **启动具名报错**（靠 1c 新增的未知键 raise，否则「配了没人读」依旧静默）。❗ **第三轮（N-1）加 E2E 变体**：经**真 `/query` 链路**（skill → 出站单入口 → nl2sql）断言 admin 不掩码——直调 `execute_sql` 的反证放不过「签发侧未改」的传输断（主路径未签 ⇒ 永远脱敏，单元级全绿、生产静默失效） | D5：证明脱敏不再依赖角色名字符串，**且残留键不会被 `.get(default)` 悄悄吃掉** |
| **R5** | 代理端点 body 里塞 `tenant_id=<他租户>` → 403；KS 收到的只有签名头，无 Form `tenant_id` | D7 + D20（body 不是断言源）+ F9 |
| **R6** | ❗ **按评审 #11 从「未定」升为决策**（依 `datasource.py` docstring 自陈的「宁可报错也不猜」既有纪律拍死）：**默认源**缺凭据 = **启动失败**；**非默认源**缺凭据 = 降级无该源 + 具名日志（不静默、不回落）。界面保存一个 Secret 里不存在的 `credential_ref` → 保存成功但 `status='saved-not-applied'`，启动 reconcile 报**具名错误** | F10 「未知 id fail-fast 不回落」同纪律；不再是风险登记里的「未定」（原 R-6 已改写） |
| **R7** | ❗ **第三轮瘦身（缓建至 P2，恢复触发 = 第一个新 feature 入枚举）**：本轮**不建**该 lint——9 个码全有消费点且各绑专属反证（❗ 第七轮 10→9：kb.config 随模板砍除）（R3/R4/R5/R10…），消费点证明由专属反证逐格承担；届时建 lint 的形状保留如下：往枚举里加一个无消费点的 feature → lint 当场报红。❗（届时必携硬规矩 #8 两件）：枚举或消费点**扫描解析没有结果**时，lint 必须非零并报 `<<< FEATURE-LINT-UNPARSED`——**不得默默报绿**（否则「量具瞎」会被读成「本轮没问题」） | **D4 新门禁的非空转自证**（两件事：① 合成违规能咬 ② 真面参与判决）；本轮该格由各 feature 的专属反证承担（§12 瘦身 2） |
| **R8** | ❗ **P7 已拍 A（2026-11-11）⇒ 本反证定为单一形状**：表里有 `dw` 行且 `app_config.yaml datasource:` 块也还在 → **启动具名报错**（原「或表行覆盖 YAML 且在日志里声明来源（选项 B）」分支**已删**，不再保留可选行为）；**不得两源各自算一次后静默取一个** | F16：同一件事两个配置源，是“改了没生效”最难查的一族 |
| **R9** | ❗ **新增（D11 配套）**：旧形状的内部头（只带 `t/u/ts`）→ 新验签方读到无 `r` ⇒ nl2sql **无条件脱敏**（行为翻转可断言）；带 `r` 的头 → KS 侧照旧只读 tenant、**不报错也不 401**（向后兼容自证，F17）。两个方向都要验，只验一个等于没验 | D11 承载是跨服务契约的**第二处不可逆面**（已登记进 ADR-0015 §4.2） |
| **R10** | ❗ **新增（P8 配套）**：不带 JWT、只带 `API_KEY` 的请求打各写面端点 → 行为按 **P8 拍板结果**可断言（无论是 viewer / 无 features / 403）；**唯一不许的是「未定义」** | F18 + `query_router.py:32` 闸门在位：守卫的第一种输入不能有定义空白 |

---

## 7. 在册判据的随动清单（**这些都是在“改判据”**，逐条给理由）

| 件 | 改法 | 为什么不是“放宽凑绿” |
|---|---|---|
| `tests/governance/test_login_no_secret_leakage.py` **三格** `fields == {...}`（评审 #3 纠正本文原来的“两处”） | `:68 UserRecord` **+`role`**（迁移 017 必然：登录要拿 role 签 claims，不带就签不出）；`:75 TokenResponse` +`role`；`:76 MeResponse` +`role`+`features` | 判据形态（钉死字段集、防额外信息外泄）不变；不收窄不删用例。**这是扩集合不是松**；新字段值必为非秘密 |
| `tests/nl2sql_service/test_result_masking.py`（❗ **评审 #4：本文初版漏列**） | 该件整篇钉 `is_masked_role(role, admin_roles)` 的**角色名语义** + `execute_sql` 的 `admin_roles` 透传（:76/:99）⇒ D5 落地必红。改法：保留“掩码/不掩码”两组行为断言，把**输入**从角色名换为 feature 集；`mask_value/mask_sensitive_columns` 那几组不碰 | 测的仍是“同一行数据在不同权限下看到什么”，只是判据源从角色名换为断言能力；不删用例、不收窄掩码结果形状 |
| `packages/agent-runtime/tests/test_auth_users.py:193-210`（❗ **评审 #3**） | `create_user` 首账号提权语义随 017 同批改（首账号 → `role='admin'`），该用例必红⇒ 断言换为 `role`，`is_admin` 保留位的等价断言另加一格 | “首账号自动成为管理员”是既有安全语义，不因迁移而变；只换表达载体 |
| `tests/deploy/test_k8s_manifest_wiring.py:412 _ASSERTION_FIELDS`（❗ **评审 #1：本文初版没发现 F1 会命中这里**） | **不改**（该探针只断言四字段**存在**，加 `role` 不破它），但**必须把这条“不随动”的判定写在这里** | 不能再靠“没看见”处理：“不随动”也是一个要留下理由的判定，否则下一轮会把未登记误读成漏随动 |
| ❗ **评审 #8 重写：`tests/governance/test_isolation_dimension_contract.py` 那行登记不成立**（本文初版写“新增两行登记”，照写必红）。实物：`MIGRATIONS_DIR` 取自 **agent-runtime 包内位置**（:28）、只 glob `*.up.sql`（:92），而 `datasources`（nl2sql 库）/ `kb_upload_profiles`（KS 库）**根本不在这个扫描面**；且 `:133` 有 stale 检查（白名单条目必须仍存在于扫描结果）⇒ **登进去当场打红，不登则该行是死字**。第二个扫描面 `SQL_SOURCE_SCAN`（:177，四文件的 SQL 谓词配对）同样不覆盖这两个 DDL | 两条出路（❗ **已定 (Ⅱ)**，依 P4 拍板 2026-11-11；(Ⅰ) 作为被否选项保留登记）：**(Ⅰ)** 把契约测试扫描面扩到 nl2sql/KS 迁移目录 + 各自白名单——**这是真判据变更**，按硬规矩 #8 必须同批带合成违规自证；**(Ⅱ)** 删掉本行登记，把「部署级 = 非隔离维」的声明落到 **P4/P3 决议载体** + 两个服务**各自**写一条归属列断言用例（不扩 runtime 判据面） | 本文推荐 **(Ⅱ)**：(Ⅰ) 是拿三个库的 DDL 去撑一把尺，后续每加一服务都得改 runtime 契约件；(Ⅱ) 不假装有跨服务判据。这不是“降低要求”，是**把判据放在它能真的咬的地方** |
| `scripts/lint_architecture.py` | ❗ **第三轮：feature↔消费点自检缓建至 P2**（R7 同步缓建，恢复触发 = 第一个新 feature 入枚举）；本轮新增两条：**出站签名单入口** + **窄门禁**（❗ 已拍 2026-11-11 P10=甲：lint 不钉 httpx 语法，钉**签发符号调用点**——`build_internal_headers(` / `sign_internal_header(` 只准出现在两个装配点文件 + agent-core 本体；D11 第三轮升级点 1、第四轮射程 F20 九处含 federation 两处照守；盲区由 R4 E2E + ADR §6.8 触发 8 兜住；必携硬规矩 #8 自证）+ **「本轮不接线」机检**（R2 改写后的形状：`capabilities.py` 与两应用装配层不得出现 `permissions=` 声明）；届时再建 feature↔消费点存在性自检（+ R7 的 `<<< FEATURE-LINT-UNPARSED` fail-closed） | 与 P13 身份装配同族：「禁止性 + 存在性互补，缺一条即退化为口头约定」；新增判据必携硬规矩 #8 自证（合成违规能咬 + fail-closed）。❗ 第四轮删重：原行末又写一遍「同一批新增一条本轮不接线机检」，与前面重复 |
| ❗ **新增（第五轮，F1 订正带出）：`web/src/api/auth.ts` 与 `verify-sse.mjs` fixture** | `AuthSession.isAdmin`（`:59` 接口 / `:220` 解析 / `:222` 返回）**随 role+features 同批改**：要么降为 `role === 'admin'` 的等价物（与 §5 `is_admin` 列保留同口径），要么换成 `role` + `features[]` 字段。**不得直接删**（它已是会话形状的一部分）；`verify-sse.mjs:519` 的 `is_admin: true` fixture 同批核（若它断言字段集则必红） | 前端只渲染不判定（§4）⇒ 会话形状必须带 role/features，否则 G1 屏面价值无法交付。**这不是放宽凑绿**：`auth.ts:213` 已有纪律「缺失按 false 不是 fail-open 的 true」，role 兜底与它同型（缺 → viewer），**判据形态不变、只换载体** |
| ❗ **新增（第六轮 H3）：`applications/agent_server/tests/test_console_router.py` 的路径集恒等约束** | **不随动，但是构造约束**：新代理端点（`POST /kb/uploads`、`PATCH /kb/{id}/status`）**必须挂新 router，不得挂 `console_router`**——`main.py:707-708` 注释自陈：该测试钉死 `console_router` 路径集**恒等于** `{("/console.html", ("GET",))}`，挂进去当场红。另 `:22 _FORBIDDEN_ENDPOINTS = ("/import", "/sql/train", "/session/revert", "import.html")` ⇒ console 页不得调这些端点 | 同 F1 k8s 探针那行：「不随动」也是要留理由的判定；不登记则下一轮可能把 kb 端点顺手挂进 console_router 而不知为何红 |
| ❗ **新增（第六轮 H11）：`applications/agent_server/tests/test_web_ui_mount.py`** | **不随动**：它钉的是挂载探测基准（进程 CWD 拼 `web/dist`，含「函数体里不得出现 `parents[`」那一格，`Dockerfile:79-80` 注释自陈）；刀 2b/3b **改页面不改挂载逻辑** ⇒ 不触它 | 若将来改挂载点/探测基准则必红（2026-11-02 在 241 真容器 `GET /ui/` 404 的失效形状就是它钉的） |
| ❗ **新增（第六轮 H5）：`is_admin` / `role` 双写纪律（跨刀 1 与刀 4）** | 迁移 017 加 `role` 后，**`is_admin` 与 `role` 必须保持等价**（`is_admin == (role == 'admin')`）：`auth_users.py` 的 **4 个读写点同批加 role**（`:248 INSERT`、`:279 SELECT`、`:101/:261/:293 UserRecord`）；首账号提权处**双写** `is_admin=true` + `role='admin'`。❗ **刀 4 的 `PATCH /users/{id}/role` 必须双写 `is_admin`**（§13 护栏已补） | 不双写则两列漂移：前端 `auth.ts:220` 读的是 `is_admin`，而守卫读 `role` ⇒ **屏上与权限不一致**（比两列都不对更难查）。与 §5「`is_admin` 保留不删、新代码只读 `role`」相容：**读只读 role，写必须双写** |
| `applications/agent_server/api/auth.py` 那段「判据必须是 `asserted_person_id`，不得换成 `asserted_tenant_id`」注释 | 追加一句 role 兜底的**同型警告** | D9 的兜底与那条旁路是同一个错误形状（宽判据把门打拍） |
| `.env.example` / `deploy/k8s/05-secrets.yaml` | `credential_ref` 名字集合与 Secret keys 一致；新 keys 仍走 `kubectl patch secret` | 维持 F11 「单一来源」不变量不破 |
| `AGENTS.md` 目录表 `web/` 那一行 | 描述订正（现写「未批开工 / 无 Vue / 无 package.json」，与 F12 实物冲突） | 文档随动，**不是**新增判据；`check_doc_sync.py` 只校首列路径存在性，接不住这类描述漂移 |
| `conf/app_config.yaml` 的 `datasource:` / `data_permission:` 两块（F16） | 按 D5/P7 结论改：角色相关键退役，`datasource:` 按 P7 选项处理；**同批给 `data_permission:` 段补未知键 raise**（`pool:` 段已有，`settings.py:222-240`） | 两个键的失数形状不同：`pool:` 段有「未知子段/未知键」raise，`data_permission:` 段走 `.get(default)` ⇒ **残留键静默忽略**。下线键时必须同时删 YAML，否则屏上/文件里都看得到但无人消费（R4 新第二格就封这里） |
| ❗ **新增（D11 配套，评审 #5）**：KS 侧「带而不用」的声明 | 在 KS 入口件写一句：内部头 payload 里的 `r` **本服务不读也不得自行解释**（它零依赖 agent-runtime，拿不到唯一映射表）；配合 `scripts/lint_architecture.py` 禁字面比较 role 字符串 | 不是新隔离判据，是防 ADR-0015 §6.5「下游自行解释 role 字符串」在 KS 那一侧发生；KS 不改代码 ≠ KS 不需要这句话 |
| ❗ **新增（第三轮 N-2）**：`web/scripts/check-events.mjs` 三枚齿与 `check-tokens.mjs` 扫描面对刀 2 的随动义务 | 新页面**自动入扫**（check-tokens 递归扫 web 全量 `.css/.ts/.vue/.html`，连注释里 `rgb(` 都判红 ⇒ 2b/3b 行数估计须算随动）；**齿 C5 端点成对性（基准=索引树）⇒ 2a 代理端点必须先于 2b 页面入库**（否则 C5 当场红）；❗ **第六轮补（H4）：C5 提供集是「从 main.py 沿装配链走」而非全仓装饰器** ⇒ 新 router 文件**必须被 main.py 装配链 include 且 git add**，否则 C5 报「装配链引用了索引树里没有的模块」（不是「端点不存在」，两格失败口不同）；`STORAGE_WL` 双向白名单（新页写存储须先进名单，列了不用也算漂移）；C3 凭据装配单入口；C4 把 `enterWithApiKey` 钉成必存控件（P8 已拍 (a) ⇒ 耦合解除） | 已入库的在册判据，本行是**随动登记**不是新增判据；不登记则刀 2 的合入顺序约束靠下一轮"发现" |

---

## 8. 待拍板——❗ **2026-11-11 用户拍板（全部拍板格已清）：P1/P8/P9（第一轮）；P3(a)/P4/P6/P7（第四轮）；P10=甲 窄门禁、R-13=甲 强警告、P6 时机=先开工刀 1（第六轮同日）；P3(b)=模板层砍除（第七轮澄清后拍——P3(a)(b)/R-11 随之消解，枚举 10→9）；P11=100MB · KS 侧唯一硬校验（第八轮，上传大小问询引出）。施工时再定 = P2/P5**

❗ **本节的“何时必拍”按评审 #19/#22 订正过：本文初版把 P4/P7 标为「评审前必定」是 overclaim**——刀 1/刀 2 与 P4 零耦合，评审结论不因 P4 未定而作废（事实：评审方已在 P4/P7 未定的情况下交出了 16/16 相符的结论）。正确档位：**评审前 = 无** · **刀 1 前 = P1/P8（已拍）+ ❗ P10（第六轮新增，1b 的 lint 边界，未拍）** · **刀 2 前 = P3/P6（P3(a)/P6 已拍，P3(b) 未定）** · **刀 3 前 = P4/P7（已拍）+ ❗ R-13 界面护栏二选一** · **施工时再定 = P2/P5**。❗ **第四轮订正：「刀 1 前置清零」不成立**——清零的只有拍板格（P1/P8/P9）；**1c 仍被两项实物阻塞**：现网 YAML 取证（本机不可达 126）+ 在途收敛件冲突规避（D10/R-8）。**拍板齐备 ≠ 可开工**，这两件事不同类。

- **P1** D9 兜底档位：`viewer` vs 直接 401（影响升级窗口与 R1 写法）。评审 #16：**可施工时再定**（ADR-0015 §2.4/§3 已载论证与复审条件）；但本文把它提到 **刀 1 前**，因为 R1 的断言形式直接依它。❗ **已拍（2026-11-11）：`viewer` 兜底**——旧令牌（无 role claim）按 viewer 处理 + D9 可聚合计数；升级窗口平滑，令牌自然过期（≤1h）后全量换新形状；R1 断言形式依此写死
- **P2** §4 十格够不够：本轮要不要把 `/import`、审计/成本面也暴露成 feature。评审 #17：可施工时再定（枚举纯 expand，不锁形状）
- **P3** 两问一起拍（❗ 评审 #18）：**(a)** `kb_upload_profiles` 落 KS 库 vs 先在 `shared-schemas` 定契约（影响刀 2 能否单独交付）；**(b)** **模板属谁**——全局共享 vs 按 tenant 隔离（本表当前无归属列，而上传 Form 带 `tenant_id`）。❗ **第三轮（N-4 + uncertainty #4 已关）**：KS 侧 ACL 语义已核——`resolve_server_tenant` 优先级 = **断言 > provided > default**（`tenant_utils.py:24` docstring，第四轮已复取原文），知识空间模型 = `scope_type` PUBLIC/PRIVATE ⇒ (b) 选项集三档：(i) 模板全局共享（部署级，与 P4 同型）(ii) tenant 谓词隔离（加归属列+谓词，体量上浮）(iii) `scope_type` 复用建模（最贴现有 ACL 形状）。❗ **第七轮拍板（2026-11-11，用户澄清「我的需求是知识库文档能界面上传」后）：模板层砍除 ⇒ P3(a)(b) 全部消解**——(a) 的 Mongo collection 不建、(b) 的归属不复存在；P3 仅存于恢复触发（见 §5 KS 侧登记）。
  - ❗ **(a) 已拍（2026-11-11 用户）：Mongo collection + `$jsonSchema` 校验**（理由：不为一张模板表新建关系库+迁移机制）。❗ **第四轮补充取证后理由订正（用户质疑「文档不是存 MinIO、chunk 不是存向量库吗」引出，F22）**：原写「KS 只有 Mongo+Milvus」**错**——KS 实有**四套**：MinIO（原文 PDF/图片）/ Milvus（chunk 向量 + 标量元数据）/ Neo4j（图谱）/ MongoDB（**只存会话历史**）。**选 Mongo 的正确理由不是「只有它」，而是「四套里只有它是通用文档库、适合配置类 CRUD」**：MinIO 是对象存储（无查询/谓词能力，做模板列表要自维护索引）、Milvus 是向量库（chunk 级不是模板级）、Neo4j 是图谱（模板不是图）。**无关系库仍成立**（`git grep -c -iE "psycopg|asyncpg|sqlalchemy|alembic|CREATE TABLE"` ⇒ rc=1），`pyproject.toml:32 pymongo>=4.17.0` ⇒ **不新增基建**。施工约束五条：① `$jsonSchema` 只校**有消费点的列**（§5 第三轮瘦身，不逐字镜像 F8 Form）；② collection 名与索引定义须进 KS 自己的启动装配（KS 无迁移链，不得假装有）；③ **模板不存口令/凭据形状**（与 D6 同纪律）；④ ❗ **不得扩展 `agent_core.memory.mongo.MongoHistoryStore`**（它是会话历史专用，KS 侧 `mongo_history_utils.py` 只是它的 shim）——模板 store **由 KS 自己用 pymongo 写**，否则把配置职责塞进 agent-core 的会话历史 store（撞分层与职责边界）。⑤ ❗ **模板 `scope_type` 必须与检索侧同源**（R-12，否则上传成功但检索不到）。❗ **随模板砍除消解（2026-11-11）：collection 不再建**；本条四套存储取证与「通用文档库」理由保留为事实记录，恢复触发时直接复用。
  - ❗ **(b) 已消解（2026-11-11 模板层砍除）**——原论证（归属列是不可逆面：后补要改存量回填 + 每个查询谓词 + 已交付界面语义）**保留为恢复触发时的决策依据**：届时若建模板，必须一开始就定归属。
  - ❗ **第四轮新发现的耦合（拍 (b) 前必读，本文不代拍）**：轻档 (i) 全局共享 **与 §4 把 `kb.config` 给 editor 相冲**——editor 是**租户内**角色（`users` 按租户），而模板是**部署级**⇒ **A 租户的 editor 改模板会改变 B 租户的上传口径**（跨租户写面）。这不是数据泄露（上传仍由服务端注断言 tenant，D7/F8），但是**配置污染**，且与 P4 已拍口径不一致（`datasource.manage` 只给 admin，`kb.config` 却给 editor）。**两个自洽出路**：**(甲)** 选 (i) 全局共享 + **把 `kb.config` 收归 admin**（改 §4 一格，与 P4 同口径：部署级配置只给 admin）；**(乙)** 选 (ii) tenant 隔离（加归属列 + 谓词，体量上浮 ≈60 行，`kb.config` 可留 editor）。⇒ **倾向轻档可以，但必须同时选甲或乙，不能只选 (i) 而不动 §4**。已登记为风险 **R-11**。❗ **随模板砍除消解（2026-11-11）**：`kb.config` 门不再存在，跨租户配置污染面随实体一起消失（R-11 消解登记见 §9）。
- **P4** `datasources` 首版是**部署级**还是带 `org_id`？❗ **已拍（2026-11-11 用户）：部署级**，且「不拿它作隔离维」必须写进**可执行载体**。载体按评审 #8 定为 §7 那行两出路里的 **(Ⅱ)**（P4 决议本体 + nl2sql 服务内一条归属列断言用例），**不进** `test_isolation_dimension_contract` 白名单（扫描面不盖 nl2sql/KS 库，登进去当场打红）。❗ **第四轮必须写清的知情降级**：部署级 + `datasource.manage` 给 admin，而 admin 是**租户内**角色 ⇒ **A 租户的 admin 改默认源会影响 B 租户的问数指向**（与 R-5 同文，但 R-5 原文只说「可能」，现已拍定为「就是」）。本轮接受它的理由 = **现网只有一个真实租户**（F10 单源现实），与 ADR-0007 §8 知情降级同型；**复审触发 = 第二个真实租户接入问数**（R-5），届时要么补 org_id 要么把 `datasource.manage` 升为平台级角色（两者都是翻案，不得静默漂移）
- **P5** 前端导航层：引入 `vue-router` vs 继续手写状态机（F12 零路由零 pinia）。评审 #20：可施工时再定（只影响 2b/3b 形状）。❗ 但评审 uncertainty #1 指出：`web/` 已是真 Vue 工程（vite + vue-tsc + pnpm + `check-tokens`/`check-events`/`verify-sse` 三把门禁脚本），**这三个脚本对新增页面是否强制未核** ⇒ 2b/3b 行数估计偏乐观，拍 P5 时一并读它们。❗ **第三轮（N-3 + uncertainty #1 已关）**：三把门禁对新页**自动强制**（check-tokens 递归扫全量源文件；check-events 的 C5 ⇒ 2a 端点须先于 2b 页面入库，见 §7 新行）；且引入 vue-router 与在册口径相抵（`plan-web-frontend-minimal-core-2026-10-29.md:164/:241/:376`「最小核心无前端路由」，视觉件 §9 排除项 1 已登记复审口径）⇒ **引入即须走该载体的复审修订（文档同批），非自由施工选择**
- **P6** 新代理端点与 roadmap #18「不新增后端专用接口」的关系定性。❗ **评审 #21 把它从“补不补 ADR”升级为“刀 2 开工前置”**：`docs/adr/0010-ui-stack-selection.md:25/:29` 与 `docs/plans/plan-frontend-stack-selection-2026-10-27.md:14/:90` 两件在册文档都引用了 #18 纪律 ⇒ 与字面相抵不是解释空间问题，**边界 ADR 必须在刀 2 第一批交付物前落地**（文档数 2 → 3，这条代价现由实物决定，不由本文预设）。❗ **已拍（2026-11-11 用户）：非选择题，必做件**（接受评审 #21 升级为开工前置）。⇒ 本轮交付物 **3 份**（方案 + ADR-0015 + 边界 ADR），**第三份尚未撰写**；它必须先于 2a 入库（与 C5 同族的顺序约束）。本文不代写它——它要引 #18 原文与两件在册件的具体行，须另起一轮取证（❗ 本文至今**未逐行读那两件**，§11 #21 已标为转述）。❗ **已拍（2026-11-11）：时机 = 先开工刀 1**——边界 ADR 在刀 1 施工期间另起一轮完成取证与撰写，**2a 开工前入库**（硬前置绑定 2a，不绑定刀 1）
- **P7**（由 F16 必出）`app_config.yaml datasource:` 块与 `datasources` 表的归属：**A 表为准、YAML 下线**（启动期见残留块就 raise）vs **B YAML 仅作首次 seeding**（表有行则忽略，需日志声明来源）。建议 **A**：B 会留下「改了表但 YAML 赢」的窗口，正是反证 R8 要封的形状。❗ **成本订正（评审 #22 + 本文 E1 复取）**：本文初版写“A 多一个清单变更”，**轻了**——`app_config.yaml` 烘在 nl2sql 独立镜像里（`Dockerfile.nl2sql-service:30-33`，`deploy/k8s/` 无挂载通道）⇒ **A = 一次 build + distribute 发布列车**，不是改清单。另：选 A 则 R8 与 Q6 的现网取证必须同批做。❗ **第三轮再订正（边际成本）**：刀 3 本身就改 nl2sql 代码（`services/datasource.py:87` + `api/dependencies.py:122`）⇒ 镜像重建是刀 3 的**内在成本**，不构成 A/B 的差异项；**A 的选择理由是 R8（双源漂移），不是成本**。❗ **已拍（2026-11-11 用户）：A 表为准、YAML 下线**，理由 = R8（不是成本）。⇒ **连带三件必做**：① 启动期见 `datasource:` 残留块**具名 raise**（R8 定为 A 形状，B 分支已删）；② **Q6 现网取证与 YAML 下线必须同批**（否则现网已改过的值会被静默丢——这正是 Q6 要取证的理由）；③ 刀 3 带一次 nl2sql build+distribute（内在成本，已定）
- **P8**（❗ **评审 #7 新增，由本文复跑 F18 后确认它是真空白**）**未断言调用方的 feature 档位**：今天 `/query` 仍接 `verify_api_key` 的 `API_KEY` 调用方（`query_router.py:32` 闸门在位、`web` 有 `ApiKeyBox.vue`），这些人**无 claims 因而无 role** ⇒ 守卫的第一种输入行为完全未定义。候选：**(a)** 按 `viewer` 兜底 **(b)** 无 features（只能打那些不分配 feature 的端点）**(c)** 全 403——**(c) 等于本方案替 ADR-0008 U1 关了旁路**，那是人批范围，**方案不得夹带**。⇒ 刀 1 开工前拍（R10 依它写）。连带拍点：F18 的 `kwargs.get("user_id", "default")` 客户端兜底要不要一并收（**它是行为变更，不是卫生修正**：observe 档下会从“按客户端 user_id 分桶”变为不拼用户段）。❗ **第三轮两条**：① web 侧机械耦合——`check-events.mjs` 齿 C4 把 `enterWithApiKey` 钉成必存控件 ⇒ 拍 (b)/(c) 时前端控件与门禁的耦合必须同批收（否则出现「门禁要求的死控件」）；② 若拍「收」user_id 兜底，收法走全局——`workspace_registry.server_user_id` 的 default 语义一处改，不在 `capabilities.py:110` 特判（第三轮升级点 3）。❗ **已拍（2026-11-11）：(a) viewer 兜底**——不新造第二条口径；C4 控件耦合随之解除（控件保留、通道有效）。**连带拍点（user_id 客户端兜底收不收）未单独拍 ⇒ 按用户「先核心」原则默认本轮不收**（不夹带行为变更）；1c 施工时若明示要收，走 `workspace_registry` 一处全局改（升级点 3 收法）
- **P9**（❗ **第三轮新增，用户 2026-11-11 问询引出**）**本轮角色交付定档：最小闭环 vs 若依式企业权限中心**。已核事实：auth 面仅 4 端点（`auth_router.py:196/:236/:271/:290`，零用户/角色/租户管理端点）；`users.is_admin` 零消费者（F1）；租户/权限管理面全仓无。若依式 = 角色表 + 角色-权限映射可配 + 用户管理界面（量级约翻倍，**D1 与 N2 翻案**）；最小闭环 = D1 现状（3 固定角色 + 9 feature 门，❗ 第七轮 10→9）。D3 已备 expand 路径（claims 形状不变、消费点不变）⇒ **先最小闭环后升级不返工**。刀 1 前拍（决定刀 1 体量与 P8 形状——API_KEY 通道在角色体系下的定性随之改变）。❗ **第三档候选（同日追问「后补好不好改」后补入）**：**固定角色 + 用户管理界面**——角色仍 3 固定码（N2/D3 不翻案、ADR-0015 claims 形状不动），加 `GET /users` + `PATCH /users/{id}/role`（≈120–150 行含测试）+ `user.manage` feature 枚举一行 + web 管理页（≈100–150 行 + 门禁随动），合计 ≈250–350 行单 PR；**零迁移**（`users.role` 已在 017）、**零 ADR 翻案**；审计复用既有 `AuditMiddleware` + 服务端断言主体纪律（`capabilities.py:142/:183`）。四条届时拍：① 护栏——不得自降、不得降最后一个 admin（首账号 advisory lock 同族不变量，库层 CHECK 管不了、端点层挡）；② 生效时机文案——改完**下次登录**才生效（N3/R-3 不变，界面必写）；③ 管理面仅 JWT——API_KEY 永不入 `/users`（P8 无论拍哪档都不影响这条）；④ `user.manage` 入枚举（D4 纪律成立：消费点=这两个端点）vs `role==admin` 硬挡。后补顺序守 C5：后端端点先入库、页面后合。❗ **2026-11-11 用户拍板：先不动管理中心——本轮按最小闭环交付（刀1 地基 + 刀2 知识库界面 + 刀3 数据源界面）；四类管理界面（刀4/5/6）延后为触发条件制（见 §13）。P9 关闭**

- **P10**（❗ **第六轮新增，H1 暴露，1b 开工前必拍**）**「禁裸 httpx 出站」lint 的扫描边界**。实物：applications 下 `AsyncClient(` **33 处**（22 测试 + 11 生产，其中约 5 处是非子服务出站：exhibition `warehouse_client.py`、agent_server `subagents/search.py`、`skill_loader/app.py`×2、`evaluation/run-all.py`）。**三条边界规则待拍**：① 是否排除 `tests/` 与 `evaluation/`（本文建议：排除）；② 非子服务出站白名单登记哪几项（warehouse/search/LLM）；③ **「子服务出站」的识别判据**——本文建议按 **URL 环境变量名**（`KNOWLEDGE_SERVICE_URL`/`NL2SQL_SERVICE_URL`/`KEFU_SERVICE_URL`/`EXHIBITION_SERVICE_URL`），而不是按语法形状（两者都是 `httpx.AsyncClient`，**语法上不可区分**）。❗ **不拍则 1b 那条 lint 不得开工**（照写会大量误报，而误报的门禁会被下一轮关掉——那比没有门禁更坏）。**替代选项**：若三条规则谈不拢，可**暂不建该 lint**，改由 R4 E2E 变体 + 代码评审承担（同 R7 缓建先例，带恢复触发）。❗ **已拍（2026-11-11）：甲（窄门禁）**——lint 不钉 httpx 语法，钉**签发符号调用点**（`build_internal_headers(`/`sign_internal_header(` 只准出现在两个装配点文件 + agent-core 本体）；表面极小、零启发式零白名单漂移；盲区（新出站不签）由 R4 E2E + ADR §6.8 触发 8 兜住；同批带硬规矩 #8 自证（合成违规能咬 + 真面参与判决）

- **P11**（❗ **第八轮新增，用户问询「上传文档大小、速度，admin 是不是要配切片规则」引出**）**上传文档大小上限**。取证：**全链路零显式上限**——uvicorn/Starlette 默认不限请求体（multipart 自动落盘 spool）；deploy 无 nginx/ingress 前置（agent-platform = NodePort 30080 直通，`deploy/k8s/20-agent-platform.yaml:330`；全仓 `kind: Ingress`/`client_max_body_size` 零命中）；KS `upload_files` 与 agent_server 均无文件大小校验（六关键词穷举 grep 仅 3 个文件命中且全无关：连接池 ×2、脚本打印 ×1）⇒ 2GB PDF 今天真传得上去（后果：处理管线小时级 + Milvus/MinIO 占用无界——**运维面真空白，非安全洞**）。❗ **已拍（2026-11-11）：100MB · KS 侧唯一硬校验**——单一真相源，一次覆盖直传（KS import.html）与刀2 代理（`/kb/uploads`）两条路径（最终都落 KS 同一入口）；web 表单加 JS 预检做**体验层**（超限秒级反馈，非安全层，值随 KS 常量注释同步）；代理层不重复设限；presigned URL 直传 MinIO **否决**（新增 presign 端点+CORS+桶策略一整面 + 绕 D7 服务端断言租户边界，违背最小闭环）。**复审触发 = 现网出现 >100MB 的合法文档需求**（届时重拍档位，不是放开）

---

## 9. 风险登记（每条带**复审触发条件**，无条件的登记不许写——《分支卫生》第 2 条）

| # | 风险 | 复审触发条件 |
|---|---|---|
| R-1 | D9 的 `viewer` 兜底会**掩盖**私钥/公钥配错（与 F9 fail-open 同族） | 按 D9 订正后的口径评：**可聚合计数 > 0 持续超一个 TTL 周期**（不再是“WARNING 条数”，那与“只记一次”自相矛盾、永不可评，评审 #6）；或 enforce 默认值被翻 |
| R-2 | 角色判定只在 agent_server 与 nl2sql 两个服务内生效；KS/exhibition 的 fork 不读 feature ⇒ “不同角色不同功能”在那两个服务内**不存在**（❗ D11 后还要加一句：KS 会**收到** `r` 但**带而不用**，不声明则下一轮会被读成“KS 也认角色”） | 当第 11 个消费点需要走到 KS/exhibition 时；或 `plan-identity-gate-6of6` 收敛完成后。❗ **第三轮补 + 第四轮订正**：federation 介导问数（`async_subagents.py:87`）今天签 `t/u/ts` 无 `r` ⇒ **1c 之前**该路径恒脱敏。❗ 原写「1c 后该路径恒脱敏」**与 1c 射程互斥**（1c 明写 F20 发送方全改经单入口，含该处）⇒ 现改为「1c 前」；1c 后仍恒脱敏的只有**未纳入单入口的残留路径**（第四轮复取后已知有两处风险：`knowledge_tools.py:145` 的静默不签、runtime 包装未同步，见 F21）。N7 同族已知边界，本文声明，防下一轮误读为漏改 |
| R-3 | N3：改某人角色 = 他下次登录才生效（最长 3600s，F6） | 第一次真实的「需当场剥夺权限」事件 |
| R-4 | `/import` 既有面本轮未纳管，与 `kb.upload` 形成两个能力入口 | 有人试图用界面上传替代它时 |
| R-5 | ❗ **P4 已拍部署级（2026-11-11）⇒ 本条从「可能」升为「已知的知情降级」**：数据源配置**就是**全局共享，A 租户的 admin 改默认源会影响 B 租户的问数指向（admin 是租户内角色，不是平台超管）。本轮接受理由 = 现网单租户（F10），与 ADR-0007 §8 同型。❗ **第六轮补在册依据（H8）**：「admin 是租户内角色」不是裸断言——`users.org_id REFERENCES organizations(id)`（`013:29`），而 `013` 文件头明写「**值域决策（org_id = tenant_id 同值域，D0 可逆）**：organizations.id 直接使用现有 tenant 断言值…所有 WHERE tenant_id 谓词零改动」⇒ org 即租户的企业化升级，**一人一企业（D9）所以 admin 是租户内而非平台超管**；身份层零 org_id（只用 tenant_id）⇒ **存储层 org_id / 身份层 tenant_id 是同值域异名，不得造第三套命名**。❗ 载体按评审 #8 换：这句声明**进不了** runtime 隔离契约件，落点是 P4 决议本体 + nl2sql 服务内用例（出路 Ⅱ，已定） | **第二个真实租户接入问数时**（届时要么补 org_id、要么把 `datasource.manage` 升为平台级角色，两者都是翻案） |
| R-6 | ❗ **按评审 #11 改写**：“启动失败 vs 降级”已按既有纪律拍死（见反证 R6），不再是未定态风险。残留风险 = **修完 Secret 必须重启才生效**（N4 不做热加载 ⇒ 运维窗口里的行为差异） | 首次现网 apply 出现 CrashLoop / `saved-not-applied` 长期不收敛时 |
| R-7 | ❗ **P7 已拍 A（2026-11-11）⇒ 真相源已定 = 表**。残留风险不再是「不知谁是真相」，而是**下线不彻底**：YAML 块留在镜像里但无人读（屏上/文件里看得到、行为不按它），或现网已改值被静默丢 | 启动期残留块 raise 未生效时；或 Q6 现网取证与 YAML 下线**不同批**时（P7 连带②） |
| R-8 | 工作区那件「错误信封收敛」在途未入库 ⇒ 本方案刀 1 与它**同时碰** `identity_middleware.py` / `query_router.py`。❗ 按评审 #14 订正：这是**合并冲突规避**，不是能力缺口（`AppError` 族在 HEAD 已可用） | 那件入库时（入库后需按 §1 命令复取 F4/F13，并按 D10 确认 `AppError` 形状未变） |
| **R-9** | ❗ **新增（D11 带来的混版本窗口）**：签发方升、验签方未升 ⇒ nl2sql 读到无 `r` 的头，**继续按旧的 YAML 常量脱敏**（两方向都 fail-closed，但行为不是本方案那个）。镜像与代码分两次发布时该窗口会变长 | 首次带 `r` 的头打旧 nl2sql rev 时；或现网 nl2sql 镜像 rev 落后于 agent_server rev 时（按 `GIT_REV` 比） |
| **R-10** | ❗ **新增（评审 #26 指出在册首要待执行项未进本件射程）**：刀 2 改 KS 代码并要 KS 侧验收，而 `AGENTS.md` 126 节 #4 的在册结论是「线上 `import_router.py` 缺 3 项已入库修复 ⇒ **KS 镜像重建+分发是当前首要待执行项**」。不先重建，R5 与代理验证的**读数全部绑不住 rev** | 刀 2 开工前；以及每次 KS 侧代码变更后（镜像 rev vs 仓库 rev 现取） |
| **R-11** | ❗ **新增（第四轮，P3(b) 耦合）：部署级模板 + `kb.config` 给 editor = 跨租户配置写面**。editor 是租户内角色而模板是部署级 ⇒ A 租户 editor 改模板会改变 B 租户上传口径（**非数据泄露**：上传仍注断言 tenant，且 F23 已证 `scope_type` 是等值 AND、PUBLIC 不跳过租户谓词；是配置污染）。**与 P4 已拍口径不一致**（`datasource.manage` 只 admin，`kb.config` 却 editor） | **P3(b) 拍板时必消解**（甲：全局共享 + `kb.config` 收归 admin；乙：tenant 隔离 + 谓词）；或第一个多租户共用上传模板的场景出现时。**不得带着本格进刀 2**。❗ **消解登记（2026-11-11 模板层砍除）**：实体与 `kb.config` 门均不存在 ⇒ 本风险随之消失；恢复模板层则复活，届时按甲/乙重拍 |
| **R-12** | ❗ **新增（第四轮，F23）：模板 `scope_type` 与检索侧不同源 ⇒ 「上传成功但检索不到」**。入库时 `scope_type` 附在 chunk 行上（F22），检索时是**等值过滤**（F23）⇒ 模板设 PUBLIC 而调用方传 PRIVATE 时，该批知识**静默不可检索**（不报错、任务状态还是成功）。同族：`build_retrieval_filter` 全空 = 全库检索、`tenant_id` 空 = 不做租户隔离（KS 既有 fail-open，**不在本轮射程**，N5） | 刀 2 施工时：**上传的 `scope_type` 必须与检索侧默认值同源**（❗ 2026-11-11 模板砍除后约束主体从模板改为**上传表单本身**：要么表单不开放 `scope_type` 可配、要么检索侧从同一来源取）；并补一条反证：经界面上传后**经真检索链路能命中**（不是只断言任务状态成功） |
| **R-13** | ❗ **新增（第六轮，H7）：界面能写出一个让服务起不来的配置**。D6 边界句①「保存时无法验任意 `credential_ref` 是否存在」 + R6「**默认源**缺凭据 = 启动失败」 ⇒ admin 经界面存一个不存在的 ref 并设为默认 ⇒ **下次重启 CrashLoop**（不是查询报错，是整服务不起）。这是 R6 那条已拍决策的**必然代价**，原文档未明写 | 刀 3 施工时二选一（**需拍**）：**(甲)** 设默认前强警告 + 界面标「未验证」（轻，不撞 D6）；**(乙)** 禁止把未验 ref 设为默认（重，**与 D6①「保存不校验」相冲**，需先拍是否允许保存时校验两个固定键）。或首次现网出现一次「改配置后 CrashLoop」时复审。❗ **已拍（2026-11-11）：甲（设默认前强警告）**——警告文案必写明后果（「下次重启服务将无法启动」）+ 显式确认 + 审计留痕；不撞 D6①；乙（禁设默认）放弃（需翻 D6① 且新增凭据面查询能力） |
| **R-14** | ❗ **新增（第八轮）：上传大小全链路无上限**——uvicorn 不限、无 ingress 兜底（NodePort 30080 直通）、KS/agent_server 零校验 ⇒ 无界上传拖垮处理管线（小时级）+ Milvus/MinIO 占用无界 | **已拍 P11 消解（2026-11-11）**：100MB · KS 侧唯一硬校验（§8 P11）；**复审触发 = 现网出现 >100MB 合法文档需求**（届时重拍档位） |

---

## 10. 给评审方的提问（❗ **本节已得到回答**，逐条对应关系见 §11；下面的文字保留是为了下一轮能同一把尺子重问）

- **Q1** D4+D5+R7 三件合起来，是否真的关掉了“配了代码里不存在的权限点”这一静默失效格？R7 的反证形式够不够？
- **Q2** D6 把口令管理推给了运维。若 `credential_ref` 指错 key，**谁先发现**（界面/启动/查询时）？这个延迟可接受吗？
- **Q3** D9 的兜底与 F9 那条实踩的 fail-open 形状差在哪里？仅靠“首一次 WARNING”够不够？
- **Q4** 在 ADR-0008 U1/U2 三项未决、enforce 默认关的前提下先铺 feature 门，是不是**在沙上盖楼**？如果是，最小前置刀是哪一件？→ **评审已答：不成立**（断言源链 JWT 验签→ContextVar 绑定已在位，feature 门在其上可 fail-closed 建成）。❗ **但它指出一块本文没写的真沙**：`API_KEY` 调用方无 claims 因而无 role ⇒ 已开 **P8**，配套反证 **R10**，并在 §4 表后明写“本表对未断言调用方行为未定义”这一格
- **Q5** F15 的 `_sanitize_identity` 加上 `role/features/permissions` 后，LLM 可填参数面是否还有**其它身份类入口**未闭？→ **评审答“有漏”（#24）**，本文已复跑定性并新增 **F18**：`capabilities.py:110` 直读 `kwargs.get("user_id", "default")`，但 `workspace_registry.py:77` 是 **ContextVar 优先** ⇒ 已绑定路径不可触达；**未绑定路径客户端值直接成为属主/分桶值**（降级面，非提示注入面；:234 处 `owner_user_id` 仍留 NULL 未硬造）。⇒ 定为卫生项 + P8 连带拍点，**不升格进刀 1**（评审 uncertainty #3 由此关掉）
- **Q6** D5 退役 `default_query_role` / `admin_roles`：按 F16，它们的**真值来源是 `app_config.yaml data_permission:` 块**，不是 settings 默认。退役时要同时处理：settings 字段 / YAML 键 / `state.py:94` 透传 / 现网已改过的 YAML。另注：`data_permission:` 段走 `.get(default)` ⇒ **残留键静默忽略**（与 `pool:` 段的未知键 raise 不同）。这个下线顺序要不要先取现网证？→ **评审答“要取证”（#25）**⇒ 已写入 1c 开工前置（本机不可达 126 ⇒ 该格阻塞时如实标阻塞，不声称已验）
- **Q7** 三刀体量 380/400/420 行均贴或超 PR<400 约束，本仓已有在册处置决策可引（“三刀体量全部超 400 行”那条）。本切法（1a/1b、2a/2b、3a/3b）是否拆到了“可独立验证”的边界？
- **Q8** 本文 §2 **七条**非目标（N1–N7；❗ 第四轮订正：原写「六条」是 N7 补入前的旧计数）里，哪一条你认为**现在就该做**而不是登记触发条件？（重点看 N1 与 N3）
- **Q9** D10 把「拒绝响应用 `AppError`」列为刀 1 前置（见 R-8）。如果那件在途工作长期不入库，本方案应该（a）等，（b）先用 `HTTPException` 后续再改，还是（c）把信封收敛并入刀 1？三者代价各是什么？→ **评审选 (a) 并重述了代价**（#14）：(a) 的真实含义是把委托方自己工作区里这件先入库（它已带契约用例、近完成），代价 ≈ 一轮评审；(b) 代价 = 两段式迁移 + 新增 `HTTPException(403)` 形状，**恰好再造这件正在退役的在册债**；(c) 代价 = 刀 1 破 600 行且把两个独立关注点塞进同一次评审。⇒ D10 已按此订正“前置”的语义（合并冲突规避，非能力缺口）

---

## 11. 评审结论台账（2026-11-11，模式 R）

> 口径声明（按 `docs/operations/evidence-format.md` §2.3：“转述别人的结论默认是它说了什么，不是事实是”）：本节的**“本文复取”列才是本文自己的结论**；“评审主张”列只是登记。两者的区分在这一行上。

**评审方读数（原文引用）**：判定当时 HEAD = `d9fa8eaa`；F1–F16 **16/16 复取相符**；工作区 8 件 / `+148 −45` 与本文 ⚠ 逐字对上；**无 P0 基线缺陷**；判决 = 「可开工但需先改 6 条」（刀1 前置 4 条 · 刀2 前置 1 条 · 刀3 前置 2 条，有交叉）。

**逐条处置**（✅ 已修入本文 · ❗ 已复取并修正严重级/成本 · ⏸ 待拍后修）：

| 评审编号 | 主张一句话 | 本文复取结果 | 处置 | 落点 |
|---|---|---|---|---|
| #1 | F1 额外命中 k8s 清单探针 | 核实：`_ASSERTION_FIELDS` 在 :412、:507 遍历存在性 | ✅ | §1 F1、§7 |
| #2 | R2 是重复劳动且刀 1 无接线项 | 核实：三形状已在册（`test_policy.py:106`）；接线点在 **federation 应用层** :98 | ✅（本文选择“登记不接线”而非“补接线”，理由见 N7） | §1 F19、N7、R2 |
| #3 | 字段集是三格不是两处 | 核实：`:68/:75/:76`；UserRecord 不带 role 就签不出 claims | ✅ | §1 F5、§7 |
| #4 | `test_result_masking` 整篇会被 D5 红 | 核实：它 import `is_masked_role` 并测角色名语义 | ✅ | §3 D5、§7 |
| **#5** | **role→nl2sql 承载未定义**（最高优先级） | 核实：`internal_header.py:66` payload 已是 `t/u/ts` JSON、验签 `.get()` 取值；**KS fork 调同一原语且只读 tenant** | ✅ **+ ❗修正成本与严重级**：评审的两个候选之外还有第三条（转发 JWT，撞 ADR-0008 U3）；且“KS 复用方一并核”这一半可当场关掉——**加键对 KS 无害、不需改 KS 代码**；严重级从“自动违反自己 ADR”下调为“需约束的自写解释”（lint 禁字面比较 + §7 KS 声明行封住） | §1 F17、**D11**、R9、§7 |
| #6 | D9 与 R-1 自相矛盾 | 核实：只记一次 ⇒ 计数封顶 1，触发条件永不可评 | ✅ | D9、R1、R-1 |
| **#7** | **未断言调用方的 feature 档位空白** | 核实：`query_router.py:32` 闸门在位；本方案第 10 节确实一字未写 | ✅（本文把它列为新待拍 P8 而**不代拍**；(c) 全 403 等于替 ADR-0008 U1 拍板，已明写不得夹带） | §4 行、**P8**、R10 |
| #8 | 隔离契约登记照写必红 | 核实：`MIGRATIONS_DIR` 取包内位置 :28、只 glob `*.up.sql` :92、:133 stale 检查；**本文另找到第二扫描面 `SQL_SOURCE_SCAN`（:177）也不盖这两个 DDL** | ✅ | §7 重写该行（改走 (Ⅱ)）、R-5 |
| #9 | R4 第二半句是空证 | 核实：键被 D5 删掉后“配个不存在的名字→行为不变”静默忽略也满足 | ✅ | R4、1c（补未知键 raise） |
| #10 | R7 缺 fail-closed 后一半 | 核实：依硬规矩 #8 第②件 | ✅ | R7、§7 lint 行 |
| #11 | R-6 不该以未定态入风险登记 | 核实：`datasource.py` docstring 自陈“宁可报错也不猜”——可依既有纪律自决 | ✅ | R6、R-6 |
| #12 | D6 通过但“档位不变”措辞要改 + 三条边界句 | 接受：“仅拖库”对手下密文+库外 KEK 确实更高 | ✅ | N1、D6 |
| #13/#17/#27/#28 | R5/R8 可咬、D7 代理剥 Form 成立、R3 通过 | 无需本文动 | —— | 未改 |
| #14 | Q9 选 (a)，且 D10 前置语义应重述 | 核实：`AppError`/`details`/`headers` 在 HEAD agent-core 已存在 | ✅ | D10、R-8、§10 Q9 |
| **#15** | 刀 1 照写必破 400，重拆 1a/1b/1c | 接受（叠加 #3/#4/#5 后三片合计 ≈600） | ✅ | §6 刀次表 + 体量订正 |
| #18 | P3 只答“表落哪”，未答“模板属谁” | 核实：本文列的 profiles 字段集**无归属列**，而 F8 的 Form 有 `tenant_id` | ✅（本文补一句：KS 侧 ACL 语义未逐行核，拍前先取证） | §5、**P3** |
| **#19/#22** | **本文“P4/P7 必须评审前定”不成立** | 接受：这是本文的 overclaim（评审方已在两者未定时交出 16/16 结论，即是反证）；P7-A 成本订正为发布列车（本文 E1 已独立复取到 `Dockerfile.nl2sql-service:30-33` 无挂载通道） | ✅ | §8 开头档位表、P4/P7 |
| #21 | P6 是刀 2 开工前置（非“要不要补 ADR”） | 本文未逐行读那两件在册件，按引用登记（标为转述） | ✅（文档数 2→3 的代价现由实物决定） | P6、§6 刀 2 |
| #23 | §4 加反证列 | 接受：lint 证不了“守卫在但被短路” | ✅（本文多拆一格：`data.unmasked` 绑 R4+R9） | §4 |
| #24 | Q5 有漏（`_run_general_qa`） | 核实：命中，但 **ContextVar 优先** ⇒ 已绑定路径不可触达；定性为**降级面而非提示注入面** | ✅ **+ ❗关掉评审 uncertainty #3** | §1 F18、Q5、P8 连带拍点 |
| #25/#26 | 1c 前先取现网 YAML 证；真正该提前的是清单外两件 | 接受：KS 镜像重建+分发 + 未断言档位 | ✅（**本文自身不能执行 126 取证**⇒ 标为阻塞项，不声称已验） | Q6、R-10、下方前置清单 |
| #29 | 若走签名头扩展，需同批登记进 ADR-0015 §4.2 | 接受：payload arity 变更是跨服务契约的第二处不可逆面 | ✅ | 件B ADR-0015 |

**本文不驳但要说清的一点**：六条必改**全部复现成立**，无一条驳回。上表的 ❗ 都是“修正严重级/成本”，不是“评审错了”——最典型是 #5：主张正确（确实一个字没写），但“要动 agent-core 共享原语、KS 复用方一并核”这半句的成本估高了（F17），且它未发现的第三条候选会撞 ADR-0008 U3。

**开工前置清单（按刀次，含方案外两件）**：

- **刀 1**：P1/P8/P9 **已拍毕**。❗ **第六轮新增：P10（1b 那条 lint 的扫描边界）未拍 ⇒ 1b 的 lint 齿不得开工**（守卫本体不受影响，可先做）。❗ **1c 仍阻塞**：① 现网 `app_config.yaml` 取证（**本机不可达 126**）；② 在途收敛件冲突规避（D10/R-8）。**1a 可开工，1b 守卫可开工 / lint 齿待 P10，1c 不可**
- **刀 2**：**KS 镜像重建 + 分发**（在册首要待执行项，AGENTS.md 126 节 #4；不先做则 R5 读数绑不住 rev）· **P6 边界 ADR（已拍必做，尚未撰写，须先于 2a 入库）** · **P3(a)(b) 已随模板层砍除消解（2026-11-11）** · **N-2 三齿随动（C5 ⇒ 2a 先于 2b 入库）**
- **刀 3**：**P4 + P7 已拍毕**（部署级 + A 表为准）⇒ 拍板格清零；残留前置 = **Q6 现网取证与 YAML 下线同批** + ❗ **R-13 界面护栏已拍（甲：强警告，2026-11-11）** + **两个镜像**（nl2sql + agent_server，H2）

**评审自列不确定的四条，本文处置**：#2（nl2sql 镜像来源）→ **已关**，见 F16 补行与 P7 成本订正（❗ 第三轮再订正：A/B 边际成本无差异，见 P7）；#3（Q5 可利用性）→ **已关**，见 F18；#1（web 三把门禁脚本对新增页是否强制）→ **已关（第三轮：对新页自动强制 + C5 顺序约束，见 §7 新行）**；#4（KS `tenant_utils` ACL 语义与模板归属选项集）→ **已关（第三轮：(b) 三档 + (a) 存储引擎四档，见 P3）**。**❗ 第二/三轮评审结论台账（N-1~N-4、出站签名单入口、瘦身项、P9）见 §12。**

---

## 12. 第二/三轮评审台账（2026-11-11，模式 R，基准 rev 仍为 `d9fa8eaa`）

> 第一轮台账见 §11。第二轮 = 修订版复核 + 四个不确定点定案；第三轮 = 「全局治本 / 防过度设计 / 核心优先」透镜 + 用户问询（出站签名 / 若依对标 / 上传现状）。**以下全部经本文独立复取**（命令风格同 §1，绑 `d9fa8eaa`），不是转述。

### 第二轮发现（N-1~N-4）

| # | 发现 | 实物锚点 | 处置落点 |
|---|---|---|---|
| **N-1** | D11 签发侧射程不完整：发送方 5 处中 3 处未签（nl2sql 主路径 ×2 + kefu）、2 处已签无 `r` ⇒ 1c 只做「payload 增键+两侧装配」则 admin 经 web 问数**永远被脱敏**（data.unmasked 主路径静默失效；R4 若直调 execute_sql 会假绿）。❗ **第四轮订正（本行读数是第三轮当时值，保留不改）：「5 处/3 未签/2 已签」经复取为「9 处 / 4 裸无凭据 / 2 静态 Bearer / 3 HMAC 已签」，详 §14.1 A1 与 F20**；**N-1 的结论（只改验签侧会静默失效）仍成立且更强** | F20 | D11 选定列 + §6 1c + R4 E2E 变体 + §9 R-2 补句 + 件B §2.6(d) |
| **N-2** | `check-events.mjs` 三齿对刀 2 是硬随动约束（C5 索引树成对性 ⇒ 2a/2b 合入顺序；STORAGE_WL/C3/C4），初版未列；且 C4 把 `enterWithApiKey` 钉成必存控件 ⇒ P8 拍 (b)/(c) 有 web 侧耦合 | `web/scripts/check-events.mjs` 全文（齿 C5/C2/C3/C4/STORAGE_WL） | §7 新行 + §6 刀 2 前置改三件 + P8 补句 |
| **N-3** | P5 引入 vue-router 与在册口径「最小核心无前端路由」相抵（三处在册文字 + 视觉件 §9 排除项 1 已登记复审口径）⇒ 引入即走复审修订，非自由选择 | `plan-web-frontend-minimal-core-2026-10-29.md:164/:241/:376` | P5 补句 |
| **N-4** | KS 全服务只有 Mongo+Milvus，**无关系库** ⇒ 「落 KS 自己的库」按字面不可施工；P3(a) 须先答存储引擎。❗ **第四轮订正（本行保留第三轮原文）：「只有 Mongo+Milvus」错，实为四套（MinIO 原文 / Milvus 向量 / Neo4j 图谱 / Mongo 会话历史），详 F22**；「无关系库」这一半仍成立（rc=1 零命中），P3(a) 结论（Mongo）不变但**理由已订正** | `pyproject.toml:32`（pymongo）、`core/config.py:100-102`、全服务 postgres/alembic/migrations/`CREATE TABLE` 零命中；❗ 第四轮补：`clients/` 四件、`README.md:179` MinIO 目录、`node_import_milvus.py` schema | §5 补句 + P3(a) 选项集扩四档 + **F22/F23/R-12** |

四个不确定点定案：#1 **已关**（三把门禁对新页自动强制；C5 ⇒ 2a→2b 顺序）· #2 **已关**（F16/Dockerfile 实锤）· #3 **已关**（`registry.py:120` 不拒额外参数 + ContextVar 优先 ⇒ 租户内降级面）· #4 **已关**（`tenant_utils.py:24` 优先级 + `scope_type` 模型 ⇒ (b) 三档，N-4 加深 (a)）。

### 第三轮：治本升级（三处，照「三层齐备」判据核验）

| 升级点 | 内容 | 落点 |
|---|---|---|
| 1（最重要） | **出站签名单入口**替代「逐发送方补签」：单一实现（agent-core `build_internal_headers` 收编 federation `_internal_tenant_header` 的 warn-once 软模式）+ 全局装配（`post_remote` 单入口，F20 五处 + D7 代理全走）+ 强制门禁（lint 禁裸 httpx 出站）——照 P2 统一异常处理先例；kefu 同刀顺手闭环。❗ **第四轮订正（本行保留第三轮原文）：「五处」应为九处、「单入口」不止 agent_server（federation 有 2 处），且需同步 runtime 委托包装 + 收编静默不签——详 §14.1 A1/A2/A3 与 F20/F21** | D11 选定列 + §6 1c + §7 lint 行 + §3 放弃④（件B §2.6(d) / §3 / §6.8 同步） |
| 2 | 1b 十个守卫 = 单一 `require_feature(code)` dependency，不是 10 段 inline if（漏接 = 无守卫 = R3 红） | §6 1b |
| 3 | P8 连带的 user_id 客户端兜底若拍「收」，走 `workspace_registry` 一处全局改 | P8 补句 |

### 第三轮：瘦身（防过度设计，各带恢复触发）

| # | 对象 | 处置 |
|---|---|---|
| 1 | profiles 字段集逐字镜像 F8 | 改「有消费点的列」（venue_id/knowledge_id/exhibition_id 是逐次参数）；§5 |
| 2 | R7 feature-lint（AST+UNPARSED） | 缓建至 P2，恢复触发 = 第一个新 feature 入枚举；本轮消费点证明由专属反证逐格承担（R7 行已改写并保留届时形状） |
| 3 | P7 成本表述 | 边际成本 ≈ 0（刀3 内在重建）；A 的理由改绑 R8；F16/P7 两处已订正 |
| 4 | N-4 的瘦解 | P3(a) 首推 Mongo collection（不为一张表新建关系库） |

### 第三轮：新增拍板格

- 新增拍板格 **P9**（本体在 §8）：本轮角色交付定档——**最小闭环 vs 若依式企业权限中心**。用户问询引出：auth 面零管理端点（`auth_router.py:196/:236/:271/:290` 实测）、`users.is_admin` 零消费者（F1）、若依式 = D1/N2 翻案且量级约翻倍；D3 已备 expand 路径 ⇒ 先最小闭环后升级不返工。**刀 1 前拍**。❗ 同日补入**第三档候选**（固定角色 + 用户管理界面，≈250–350 行纯 expand 层，可后补不返工），见 P9。❗ **拍毕（2026-11-11）：最小闭环**——四类管理界面延后为触发条件制（§13）

### 第三轮：必须保留的「看似重」项（防矫枉过正）

D11 承载 + R9 双向 + R-9（跨服务契约第二处不可逆面）· D5 退役透传链 + 未知键 raise（双源）· P8/R10（守卫第一种输入定义空白）· D9 可聚合计数（R-1 可评性）· N-2 三齿随动（在册判据）。

---

## 13. 管理界面延后路线（2026-11-11 用户拍定：先核心后管理界面；本节降为**延后登记**——每期带触发条件，届时重开）

> 用户 2026-11-11 先明示需要租户/角色/权限/用户四类管理界面，同日改拍「先不动这么复杂的，先处理最核心的；文档上传、数据源配置需要界面处理」⇒ **P9 关闭为最小闭环**，本节四期**延后而非取消**，每期登记触发条件：

| 期 | 内容 | 重量 | 在册前置 / 翻案项 | 关键护栏 |
|---|---|---|---|---|
| **刀1（内容不变）** | 断言源 + 9 feature 门 + 3 固定角色（D1 现状；第七轮 10→9） | ≈600 | ❗ **第六轮订正：原写「前置已清零、可开工」不成立**——P1/P8/P9 已拍，但 **1b 的 lint 齿待 P10**、**1c 被现网取证（不可达 126）+ 在途件冲突规避阻塞** ⇒ **只有 1a 与 1b 守卫本体可开工** | — |
| **刀4 用户管理** | `GET /users` + `PATCH /users/{id}/role`（三选一）+ web 页 | ≈250–350 | 刀1 落地即可（纯 expand，零迁移） | ① 不自降/不降最后一个 admin（advisory lock 同族）② 改完**下次登录**生效（界面必写，N3 不变）③ 仅 JWT ④ 审计挂既有 `AuditMiddleware`（`capabilities.py:142/:183`）⑤ ❗ **第六轮补（H5）：`PATCH role` 必须双写 `is_admin`**（保持 `is_admin == (role=='admin')`），否则前端 `auth.ts:220` 读的 is_admin 与守卫读的 role 漂移 ⇒ 屏上与权限不一致 |
| **刀5 角色管理 + 权限配置** | 角色表（code/name/is_system）+ role→feature 映射入库 + CRUD 面 + web 页 | ≈600–900 | **ADR-0015 §6.2 在册强制：D5 未就位不许建角色表 ⇒ 必须在 1c 之后**；D1/N2/D3 翻案走 ADR 修订；迁移 017 的 `CHECK` 改 FK | ① feature 枚举仍**代码闭合**（界面只能勾 10 个既有码，不能造新码——造新码 = D4 死门）② `data.unmasked` 安全门**不开放界面勾选**（建议）③ 映射改完**下次登录**生效（claims 缓存语义）④ 管理面仅 JWT |
| **刀6 租户管理** | 定性取决于拍板：动态建租户（平台化多租户）vs 管理现有租户 + 用户分派（管理面） | 未定（前者重得多） | 动 **ADR-0007**（服务端断言租户）前提 + KS/exhibition 两套 fork 的租户通路（F7：身份门 4/6）⇒ **须先立 Spec/ADR，不并入本方案** | 全部管理面仅 JWT + 审计；租户级管理员是否为第五角色 → 随定性一起拍 |

- **触发条件（延后 ≠ 取消，逐期登记）**：刀4 = 第一次出现「改角色不想连库改 SQL」的运维诉求；刀5 = 第一个真实租户要求差异化角色（N2 触发；ADR-0015 §6.2「D5 未就位不许建角色表」的先决条款届时依旧有效）；刀6 = 第一个需要动态建租户的真实需求（届时先答两问：动态建租户 vs 管理现有+分派；`data.unmasked` 安全门是否允许界面勾选）。
- **本轮交付 = 刀1（地基，内容不变）+ 刀2（知识库界面）+ 刀3（数据源界面）**——用户 2026-11-11 确认刀2/刀3 为本轮核心。
- 刀5/刀6 重开时各需一轮方案修订/Spec（非 T0 改动先 Spec 后代码——《AI 开发范式》总纲）。

---

## 14. 第四轮审核台账（2026-11-11，**本文自审**，非外部评审；基准 rev 仍 `d9fa8eaa`）

> 口径声明：本轮是用户要求「再审核下最新的文档内容」后本文做的**自审**，全部锚点由本文 `git show` / `git grep` 复取（命令风格同 §1）。**与 §11/§12 的区别**：那两节是外部评审结论的处置台账，本节是本文自己找出的错。按 `evidence-format.md` §2.3，本节读数均为本文实取，不是转述。

### 14.1 承重面事实错误（3 处，均已订正）

| # | 错在哪 | 复取证据 | 订正落点 |
|---|---|---|---|
| **A1** | **F20 「发送方 5 处」漏 4 处**，且把 agent_server 的件误挂 nl2sql 名下 | `git grep -n "client.post" -- applications/agent_server/capabilities.py` ⇒ **5 处**（:261/:286 KS、:313 nl2sql、:339 kefu、**:366 exhibition**）；`git grep -n "sign_internal_header(" -- "*.py"` ⇒ 生产面 **3 处**（`agent_server/api/sql_router.py:61`、`agent_federation/agent/async_subagents.py:87`、**`agent_federation/tools/knowledge_tools.py:145`**）；`git show d9fa8eaa:applications/nl2sql-service/nl2sql_service/api/sql_router.py` ⇒ **`fatal: path does not exist`** | F20 重写为 **9 处**（HMAC 3 + 静态 Bearer 2 + 裸无凭据 4）；D11 升级点 1②、§6 1c、§7 lint 行、ADR-0015 §2.6(d) 同步 |
| **A2** | **D11/ADR 「单入口只住 agent_server」射程窄了** | F20 有 **2 处在 federation**（`async_subagents.py:171`、`knowledge_tools.py:145`）⇒ 只收敛 agent_server 会使「lint 禁裸 httpx」在 federation 报红或被迫白名单豁免（= ADR §6.8 那条被绕开） | D11② 改为**两个应用各一个装配点、共用 agent-core 同一实现**；§6 1c 落点面补 federation；ADR §2.6(d) 同步 |
| **A3** | **两个施工陷阱未登记**（原 F20 之外） | ① `agent_runtime/identity.py:261` 是**委托包装**（→ `_core_sign`，注释自陈「原语单一实现于 agent_core」）——**不是第二实现**（本文初判要收回），但 `knowledge_tools.py:145` 经它签 ⇒ 不同步包装则该路径拿不到 `role` 且不报错；② `knowledge_tools.py:140-147` = `try: … if _hk: … except ImportError: pass` ⇒ **静默不签**（比 federation warn-once 更弱，F9 同族） | **新增 F21**；D11① 补两个必做项；ADR §2.6(d) + §6.8 触发面扩为「包装层与 core 参数面不同步」 |

### 14.2 自相矛盾与计数错（6 处，均已订正）

| # | 矛盾 | 订正 |
|---|---|---|
| B1 | **R7 已缓建至 P2，但 §4 表头与 D4 仍写「D4 自检当场红」/「否则门禁报红」** ⇒ 指向一把本轮不存在的尺（与「把接线当启用」同族） | D4 + §4 表头改为「由专属反证逐格承担（R3/R4/R5/R10）」，并明写缓建不等于放弃 + 恢复触发 |
| B2 | **R-2 写「1c 后 federation 路径恒脱敏」，而 1c 明写发送方全改经单入口（含该处）** ⇒ 互斥 | R-2 改为「**1c 之前**恒脱敏」；1c 后仍恒脱敏的只有未纳入单入口的残留路径（F21 两处） |
| B3 | §1 写「共 19 条（F1–F19）」但表内有 **F20** | 改为 **21 条（F1–F21）**（本轮新增 F21） |
| B4 | §10 Q8 写「§2 六条非目标」但实有 **N1–N7 七条** | 改为七条（原计数是 N7 补入前的旧值） |
| B5 | F19 写「**唯一**非 None 的调用是 `test_policy.py:106`」 | 复取：同文件 `test_validate_permission_granted` 等也传非 None ⇒ 改为「非 None 的调用只在测试里」（属「只有 N 处」型断言，在册记忆有同型坑） |
| B6 | §7 lint 行末尾**重复**写了一遍「同一批新增一条本轮不接线机检」 | 删重，并把 R2 形状合进前一句 |

❗ **另订正一处 overclaim（不计入上表，因为它在状态行与 ADR 两处）**：「**刀 1 前置清零，可开工**」不成立——清零的只有**拍板格**（P1/P8/P9）；**1c 仍被两项实物阻塞**（现网 YAML 取证本机不可达 126 + 在途收敛件冲突规避）。**拍板齐备 ≠ 可开工**。已同步订正本文状态行、§8 档位表、§11 前置清单、ADR-0015 状态行。

### 14.3 用户拍板落点（2026-11-11 第四轮）

| 格 | 用户拍板 | 本文落点 | 连带必做 |
|---|---|---|---|
| **P3(a)** | Mongo collection + `$jsonSchema`（不为一张表新建关系库） | §8 P3(a) 已拍 + §5 KS 侧改 collection | 事实前提已复核（`pyproject.toml:32 pymongo`、关系库 rc=1 零命中）；`$jsonSchema` 只校有消费点的列；collection/索引进 KS 启动装配 |
| **P3(b)** | 「届时按 P4 同型判断，倾向轻档」 | ❗ **本文判定不能届时**，仍列刀 2 前必拍 | 归属列是**不可逆面**（后补要改存量回填+每个谓词+已交付界面）；且**轻档 (i) 与 §4 `kb.config` 给 editor 相冲** ⇒ 新增 **R-11**，必须同时选甲（收归 admin）或乙（tenant 隔离） |
| **P4** | 部署级 + 「不作隔离维」写进可执行载体 | §8 P4 已拍 + §7 出路定为 **(Ⅱ)** | R-5 从「可能」升为「已知知情降级」（admin 是租户内角色 ⇒ 跨租户影响）；复审触发 = 第二个真实租户 |
| **P6** | 非选择题，必做件 | §8 P6 已拍 + §6 刀 2 前置 + §11 清单 | **文档数 2→3**，第三份（边界 ADR）**尚未撰写**，须先于 2a 入库；本文至今未逐行读 `0010:25/:29` 与 `plan-frontend-stack-selection:14/:90`（§11 #21 标为转述） |
| **P7** | A 表为准、YAML 下线（理由是 R8 不是成本） | §8 P7 已拍 + **R8 定为单一形状（B 分支已删）** + §6 刀 3 + R-7 改写 | ① 启动期残留块具名 raise；② **Q6 现网取证与下线同批**；③ 刀 3 带一次 nl2sql build+distribute |
| **P2/P5** | 施工时再定 | 保持 §8 原档位（不阻塞任何刀） | P5 引入 vue-router 须走在册口径复审修订（N-3） |
| **P8 连带** | user_id 客户端兜底默认不收 | §8 P8 已记（本轮不收，不夹带行为变更） | 若届时收，走 `workspace_registry` 一处全局改（升级点 3） |

### 14.4 本轮复核**成立**、未改的第三轮锚点（防下一轮误以为全错）

- **N-4 KS 无关系库**：成立（`pyproject.toml:32 pymongo>=4.17.0`、`README.md:68` MongoDB；关系库关键词 rc=1 零命中）。
- **uncertainty #4 KS ACL 语义**：成立（`tenant_utils.py:24` docstring 原文「优先级 **签名断言 > provided > default**」）。
- **N-2 三齿**：成立（`web/scripts/check-events.mjs` 的 C5 `:8/:14`、C2/C3/C4 `:195-197`、`STORAGE_WL` `:268/:286-289`；**C4 把 `enterWithApiKey` 钉成必存控件在 `:352`**）⇒ P8 已拍 (a) 后该耦合解除（控件保留、通道有效）。
- **F19 接线点在 federation**：成立（`planners/agentic_runtime_bridge.py:98`）；`test_policy.py:106` 确为 `pv.validate(g, caller_permissions={"read"})`。

### 14.5 本轮**未做**的事（不扩范围，按在册「等待期停手交回」纪律）

1. **第三份边界 ADR 未写**（P6 已拍必做，但需先逐行取 #18 原文与两件在册件 ⇒ 另起一轮）。
2. **1c 现网 YAML 取证未做**（本机不可达 126，仍阻塞，不声称已验）。
3. **两份件仍未入库**（`git status` 层面 `??`）⇒ 按《观测面硬规矩》#11/#13，**现在还不能当批准依据**；是否 `git add` 待用户明示。
4. **未新增任何判据/量具/门禁齿**：本轮全部改动是「订正既有事实条 + 登记已发生的拍板 + 消解自相矛盾」，属收尾；R-11 是**风险登记**（账面）不是新门禁齿。
5. **未动一行产品代码**，未触碰工作区那 8 个在途文件。

### 14.6 第四轮补充取证（用户质疑「上传的文档存哪」引出，本节均为本文实取）

**用户质疑成立**：原文存 MinIO、chunk 转向量存 Milvus——**不是存 Mongo**。本文上一轮的 N-4「KS 只有 Mongo+Milvus」**漏了 MinIO 与 Neo4j**，已订正。

| 取证项 | 读数 | 落点 |
|---|---|---|
| KS 存储分工 | `clients/` 四件：`milvus_utils` / `minio_utils` / `mongo_history_utils` / `neo4j_utils`；`README.md` 架构图与依赖表四套并列 | **新增 F22**；N-4 加订正注记 |
| 原文落点 | MinIO 桶 `kb-import-bucket`、目录 `pdf_files`/`images`（`README.md:179`、`.env.example:70`） | F22 |
| chunk 落点 | Milvus `kb_chunks`：13 个字段，**`tenant_id`/`scope_type` 是附在向量行上的标量字段**（`extract_tenant_scope_for_chunk(state)`）⇒ **KS 今天没有文档级元数据表** | F22；§5 KS 侧 |
| Mongo 职责 | **只存会话历史**，`mongo_history_utils.py` 是 `agent_core.memory.mongo.MongoHistoryStore` 的兼容 shim | F22；P3(a) 施工约束④（不得扩展该 store） |
| `scope_type` 是否跨租户 | `build_tenant_filter` = `tenant_id == …` **and** `scope_type == …`（等值 AND）⇒ **PUBLIC 不跳过租户谓词、不跨租户** | **F23**；❗ 本文一度怀疑「模板改 PUBLIC 会跨租户泄露」，**取证后收回**；R-11 定性（配置污染非泄露）仍正确 |
| 新发现的静默失效 | 检索侧 `scope_type = Field("")` 默认空；若调用方传 PRIVATE 而模板设 PUBLIC ⇒ **上传成功但检索不到** | **新增 R-12**（刀 2 施工约束 + 反证：经真检索链路能命中，不是只断言任务成功） |
| KS 既有 fail-open（不在本轮射程） | `build_retrieval_filter` 全空返回 None = **全库检索**；`if tenant_id:` 空则**不做租户隔离**（docstring 自陈） | F23 登记；N5 不收敛 KS fork ⇒ **仅登记不动** |

❗ **P3(a) 结论不变（Mongo），但理由换了**：不是「KS 只有 Mongo」，而是「四套里只有 Mongo 是通用文档库、适合配置 CRUD」。**用户拍的板仍成立，本文把它的依据补对了**。

### 14.7 根因分析（用户问「为什么之前是错的、需要被纠正」）——❗ **本节是方法性缺陷登记，不是单次失误道歉**

**直接原因：用只能证「负面断言」的搜索面，去支撑「穷举断言」。**

N-4 当时的取证命令是 `git grep -c -iE "psycopg|asyncpg|sqlalchemy|alembic|CREATE TABLE" ⇒ rc=1`。它只能证明「**无关系库**」，**证不了「只有 Mongo+Milvus」**——零命中只能排除被搜的那几项，不能枚举未被搜的项。正确命令是 `git ls-tree clients/`（**一条就看见四件**），而本文直到用户质疑才跑它。

**三层根因（按严重度递增）**：

| 层 | 缺陷 | 实物证据 |
|---|---|---|
| **方法层** | 穷举断言（「只有 X」/「共 N 处」/「命中面只有…」）用了**排除式搜索**而非**枚举式命令** | N-4 用 grep 零命中推「只有两套」；F20 用四个文件的 grep 推「共 5 处」；F1 用 `-- "*.py"` 推「命中面只有…」 |
| **复核层** | 第四轮复核 N-4 时**只复了一半**（无关系库那半），把「部分复核通过」当成「整条成立」；另一半（穷举性）**从未被复核** | 与硬规矩 #9「判决新鲜度」/「数绑件名不绑内容」同型：复核了能复核的，跳过了不能复核的 |
| **线索层（最重）** | **第一轮 grep 输出里已经出现过 `clients/minio_utils.py`**（ruff per-file-ignores 那段），本文看见了但没追 | 不是「找不到」，是「看见了没核」——线索已在眼前，却被当成无关噪声 |

**为什么用户能纠正而本文自审没抓到**：用户用的是**领域常识**（RAG 系统 = 对象存储 + 向量库是标准架构），拿常识去挑战穷举断言；本文的取证是**搜索驱动**而非**架构驱动**——没有先问「一个 RAG 系统应该有哪几套存储」再逐项核。**搜索驱动只能找到你想到的词，架构驱动能发现你没想到的缺失。**

#### 同型错误全清单（用同一把尺子重扫全文）

| # | 断言 | 错在哪 | 状态 |
|---|---|---|---|
| 1 | N-4「KS 只有 Mongo+Milvus」 | 排除式 grep 推穷举；漏 MinIO/Neo4j | ✅ 已订正（F22，**用户纠正**） |
| 2 | F20「发送方共 5 处」 | 只 grep 四个文件推全仓穷举；漏 exhibition/KS×2/knowledge_tools | ✅ 已订正（第四轮 A1，本文自审） |
| 3 | F19「**唯一**非 None 调用是 :106」 | 同文件 granted 用例也传非 None | ✅ 已订正（第四轮 B5） |
| 4 | **F1「命中面只有 py 件 / 零消费者」** | **搜索面 `-- "*.py"` 漏前端**；`web/src/api/auth.ts:59/:220/:222` 实有解析 | ✅ **本轮（第五轮）新抓并订正**，带出 §7 漏列随动件 |

❗ **四者同一根因**，所以它不是「偶然写错一个词」，是**取证方法缺陷**。第 4 处还带出一个**漏列的随动件**（`auth.ts` 会话形状 + `verify-sse.mjs` fixture）——如果不扫，刀 1 会在前端侧漏改。

#### 重扫后**复核成立**的穷举/负面断言（防下一轮误以为全错）

> ❗ 本节故意用**列表而非表格**，且**行首不以编号开头**：表格行首 `| F7…` 会被「F 条数」的机械计数（`^\| \*?\*?F\d+`）误计入（实测使 23 看起来变 29）；列表行首 `- **P9…` 同理会被 P 计数（`^- \*?\*?P\d+`）误计入（实测使 9 变 10）。**事实表本体 23 条、拍板格本体 9 个**。

- **F7「KS 零依赖 agent-runtime」**：`git grep -F "agent_runtime" -- applications/knowledge-service` ⇒ **rc=1 零命中**（但 KS **依赖 agent-core**，多文件命中 ⇒ 原措辞准确，不得读成「KS 零依赖共享包」）
- **F10「nl2sql 无 datasources 表 / 迁移止于 006」**：`ls-tree migrations/` ⇒ 001–006 成对，**无 007+**
- **F14「下一可用号 017」**：`ls-tree runtime migrations/` ⇒ 最新 `016_user_credentials`
- **F12「前端零路由零 pinia」**：`package.json` **全文**：deps 仅 vue+eventsource-parser，**devDeps 也核了**（全是构建/lint 工具，无 router/pinia）
- **F13「端点面」**：`git grep -E "@app\.(get|post…)" -- applications/agent_server` ⇒ **零命中**（无 app 级路由，`api/` 的 `@router` 面即完整）
- **F16「deploy 无 app_config 挂载通道」**：`git grep -F "app_config" -- deploy/` ⇒ **全树仅 2 处注释**（`00-config.yaml:75`、`36-…:89`）
- **auth 面仅 4 端点（P9）**：`auth_router.py` 的 `@router` 全清单 ⇒ register/login/me/logout **正好 4**
- **N-4「deploy/k8s 无 KS 清单」**：`ls-tree deploy/k8s/` 过滤 knowledge/ks ⇒ **空**

#### 纪律修正（本文后续取证必守，也适用于下一轮）

1. **穷举断言必用枚举式命令**：「只有 X」/「共 N 处」/「命中面只有…」必须来自 `ls-tree` / 完整依赖清单 / **全仓** grep，不得来自排除式 grep 的零命中。
2. **负面断言必写明搜索面**：写「零命中」时必须同时写「在什么面上零命中」（如 F1 应写「`*.py` 面零端点消费」而不是「零消费者」）。
3. **部分复核 ≠ 整条成立**：一条事实含两个断言时（如 N-4 = 无关系库 + 只有两套），**两个都要分别复核**；只核一个就得标「另一半未核」。
4. **架构驱动先于搜索驱动**：取证前先问「这类系统应该有哪些部件」（RAG = 对象存储+向量库+元数据+会话），再逐项核存在性——**缺失的部件不会出现在你的 grep 关键词里**。
5. **线索不得当噪声**：grep 输出里出现的同类件名（如 `minio_utils.py`）必须追一次，即使它不在当前搜索目标里。

### 14.8 第六轮深度审核（用户要求「找隐藏的没发现的问题」）——**不查措辞与计数，只查承重逻辑与施工可行性**

> 方法：先列出**从未被验证过的承重面**（users 表结构 / TokenClaims 实际形状 / lint 扫描边界 / web 产物镜像归属 / 端点恒等性约束 / create_user 读写点），再逐个取证。全部绑 `d9fa8eaa`。

#### 🔴 P0：设计描述缺陷（需重拍）

| # | 问题 | 实物证据 | 处置 |
|---|---|---|---|
| **H1** | **「禁裸 httpx 出站」那条 lint 按文档描述施工会大量误报**：D11③ / §7 lint 行 / ADR §2.6(d) 都写「禁 applications 下裸 `httpx.AsyncClient(`/`client.post(`，白名单登记制」，但**未定义扫描边界** | `git grep -F "AsyncClient(" -- applications/` ⇒ **33 处**：**22 处是测试**（exhibition `test_server.py` 14 + agent_server `test_callback.py` 7 + `test_human_task_api.py` 1），生产面 11 处里**约 5 处不是子服务出站**（exhibition `warehouse_client.py` 外部数仓 REST、`subagents/search.py` 外部搜索、`skill_loader/app.py`×2、`evaluation/run-all.py`） | ❗ **本文先修正自己一个过强判断**：取证前本文一度写「不可施工」，**取证后收回**——它**可施工，但缺三条边界规则**：① 排除 `tests/` 与 `evaluation/`；② 非子服务出站（warehouse/search/LLM）白名单登记；③ **「子服务出站」的识别判据**（建议按 URL 环境变量名：`KNOWLEDGE_SERVICE_URL`/`NL2SQL_SERVICE_URL`/`KEFU_SERVICE_URL`/`EXHIBITION_SERVICE_URL`）。⇒ **新开 P10 待拍**，不拍则 1b 那条 lint 不得开工。❗ **已拍（2026-11-11）：甲（窄门禁）**——lint 改钉签发符号调用点（不钉 httpx 语法），见 §8 P10 |

#### 🟠 P1：发布列车漏项与施工约束漏列

| # | 问题 | 实物证据 | 处置 |
|---|---|---|---|
| **H2** | **web 产物进 agent_server 镜像 ⇒ 刀 2b/3b 都要重建 agent_server 镜像**，文档原未写 | `Dockerfile:12 FROM node:24-alpine AS web-builder` → `:29 pnpm install --frozen-lockfile && pnpm run build` → `:81 COPY --from=web-builder /web/dist ./web/dist`；`main.py:809 app.mount("/ui", NoStoreStaticFiles(directory=dist…))`；`Dockerfile.nl2sql-service` 搜 web ⇒ **rc=1 零命中**（nl2sql 镜像不含前端） | §6 刀 2/刀 3 发布成本订正为**各两个镜像**；❗ 连带：`--frozen-lockfile` 是判据不是优化项（`Dockerfile:25` 注释）⇒ **改 web 依赖必须同批更新 `pnpm-lock.yaml`**，否则构建红 |
| **H3** | **新代理端点不得挂 `console_router`**（路径集被钉死恒等） | `main.py:707-708` 注释自陈：`test_console_router.py` 钉死该子路由路径集**恒等于** `{("/console.html", ("GET",))}`；另 `test_console_router.py:22 _FORBIDDEN_ENDPOINTS = ("/import", "/sql/train", "/session/revert", "import.html")` | §7 新增随动行（构造约束） |
| **H4** | **C5 提供集是从 main.py 沿装配链走**，不是全仓装饰器 ⇒ 新 router 文件必须被装配链 include 且 git add | `check-events.mjs` C5 段原文：「提供集：从 main.py 沿装配链走（不是“全仓装饰器”：没 include 的路由表项运行时不存在）」+「装配链引用了索引树里没有的模块」失败口 | §7 C5 行补一句（原只写「2a 先于 2b」，不够） |
| **H5** | **`is_admin` / `role` 双写纪律未定** ⇒ 两列会漂移 | `auth_users.py:248 INSERT INTO users (id, org_id, display_name, is_admin, password_hash)`、`:279 SELECT … is_admin …`、`:101/:261/:293 UserRecord(is_admin=…)` ⇒ **读写点共 4 处都要加 role**；而前端 `auth.ts:220` 读的是 `is_admin` | §5 补双写纪律；❗ **跨刀隐患：§13 刀4 的 `PATCH /users/{id}/role` 必须双写 `is_admin`**，否则两列不一致、前端 isAdmin 与 role 矛盾（刀4 护栏原未列这条） |
| **H6** | **D9 与 P8 是两个兜底实现点**，文档只说「不新造第二条口径」但未指定单一实现位 | D9 落点 = 「`verify_token` 后的消费侧」；而 **API_KEY 路径不经 `verify_token`**（P8）⇒ 两处各写一个兜底就会漂 | D9/P8 补一句：**两路均调 `authorization.py` 同一个 `resolve_features(claims: TokenClaims \| None)`**，兜底逻辑只住这一处 |

#### 🟡 P2：运维风险未明写 + 论证依据补强

| # | 问题 | 实物证据 | 处置 |
|---|---|---|---|
| **H7** | **界面能写出一个让服务起不来的配置**（原文档未明写） | D6 边界句①「保存时无法验任意 ref 是否存在」 + R6「**默认源**缺凭据 = 启动失败」 ⇒ admin 经界面存一个不存在的 `credential_ref` 并设为默认 ⇒ **下次重启 CrashLoop** | **新增 R-13**；界面护栏二选一：设默认前强警告，或禁止把未验 ref 设为默认（后者与 D6① 相冲）。❗ **已拍（2026-11-11）：甲（强警告，文案必写后果 + 显式确认）**，见 §9 R-13 |
| **H8** | R-5/R-11 「admin 是租户内角色」**原为裸断言，现有在册依据** | `013_org_user_conversations.up.sql` 文件头：「**值域决策（org_id = tenant_id 同值域，D0 可逆）**：organizations.id 直接使用现有 tenant 断言值…所有 WHERE tenant_id 谓词零改动」；`users.org_id REFERENCES organizations(id)`；身份层零 org_id（只用 tenant_id） | R-5/R-11 引该依据；❗ **P4 「带 org_id」选项要注明：nl2sql 侧用 `tenant_id` 命名**（同值域异名，不得造第三套命名） |
| **H9** | 正面事实：**`TokenClaims(` 全仓构造点只有 1 处** ⇒ 加 role 字段影响面极小 | `git grep -c -F "TokenClaims(" -- "*.py"` ⇒ 仅 `identity.py` 1 处（测试不直接构造，走 `mint_token`） | 补进 F4；**1a 体量焦虑可缓解**（与 H1–H6 的加量项部分抵消） |
| **H10** | F18 定性（降级面）**有在册依据可引** | `013` 文件头：「conversations.user_id 先可空…014b 前 read 断言只到 org 级，**不得宣传“会话按人隔离已具备”**」 | F18 补引（与本文定性同向） |
| **H11** | 另一枚在册钉子：`test_web_ui_mount.py` 钉挂载探测基准（含「函数体里不得出现 `parents[`」） | `Dockerfile:79-80` 注释自陈；2026-11-02 在 241 真容器 `GET /ui/` 404 的失效形状 | §7 登记为「**不随动 + 理由**」（刀 2b/3b 改页面不改挂载逻辑），同 F1 k8s 探针那行的处理方式 |

#### 本轮**复核成立**的承重锚点（之前从未验过，本轮首验）

- **F4 claims 形状**：`identity.py:61-67` `@dataclass(frozen=True) TokenClaims(tenant_id, user_id=None, jti=None, exp=None, iat=None)` ⇒ **无 role 位✓**（原文写 :62-68，实际 :61-67，差一行，已订正）；`verify_token` docstring 自陈「强制 exp/iat/sub…必须含非空 tenant_id claim」⇒ F4 后半✓。
- **迁移 017 可施工性**：`users` 表在 `013:27` 建（`id/org_id/display_name/is_admin BOOLEAN/created_at`），`016` 补 `password_hash/last_login_at` ⇒ **表存在、`is_admin` 是 BOOLEAN**（回填 `WHERE is_admin` 合法）、**无 role 列**（017 加列不冲突）。
- **users 无 login 列**：登录用 `id`（`auth_users.py:279 WHERE id = %s`）⇒ 1a 签 role 时读 users 行的路径已存在，不需要新建查询。

❗ **本轮未新增任何产品代码改动**；H1 开 **P10**（lint 边界）属**审核暴露的必要拍板格**，不是范围扩张；H7 的新 R-13 是风险登记（账面）。

### 14.9 第八轮问询（2026-11-11，用户问「上传大小、速度，admin 要不要配切片规则」；基准 rev 仍 `d9fa8eaa`）

> 方法同前：先取证后回答，全部锚点实取。**结论三件**：① admin **不需要**在界面配切片规则（不界面化，带触发条件登记）；② 大小上限是真空白 ⇒ 开 **P11**（当轮拍毕：100MB · KS 侧唯一硬校验）；③ 速度瓶颈在处理管线不在传输。

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| **K1** | KS 上传接口**无任何切片参数**：`upload_files` Form 字段实测 13 个，唯一处理开关 `enable_item_name_recognition`（NER，bool 默认 True）**已在表单** | `import_router.py` Form 字段逐行实取 | 回答「admin 要不要配切片」= **不需要**——今天也没有这个参数面可配 |
| **K2** | 切分策略是**代码常量**，连部署级配置面都没有 | `node_document_split.py`（464 行）配置段：`DEFAULT_MAX_CONTENT_LENGTH = 2000` / `MIN_CONTENT_LENGTH = 500` / `chunk_overlap=0`（注释原文「无重叠：按标题切分后语义完整，无需重叠」）；全仓 `app_config.yaml`（仅 nl2sql 有该文件）grep chunk/split 零命中 | **切片不界面化**：调参 = 改常量 + golden 回归 + 发版（工程闭环，`eval/run_eval.py:257` 归因维度在册「切分劈答案」）。**触发条件**：golden 集出现「切分劈答案」类失分，或首次出现按文档类型差异化切分的真实需求——届时重新评审，不是自由施工 |
| **K3** | **大小全链路零上限（真空白）** | 六关键词穷举 grep（`client_max_body_size`/`max_upload`/`MAX_FILE`/`file_size`/`size_limit`/`max_size` × deploy + 两服务）= 仅 3 个文件命中且全无关；`deploy/k8s/20-agent-platform.yaml:330` NodePort 30080 直通，无 nginx/ingress 前置 | **开 P11，当轮拍毕**：100MB · KS 侧唯一硬校验（单一真相源盖直传+代理两路）；web 表单 JS 预检做体验层。新增 **R-14**（消解登记见 §9） |
| **K4** | 速度：**瓶颈在处理管线不在传输** | `upload_files` 返回 task_id + `get_task_progress` 轮询（异步任务）；NER = LLM 调用、embedding = 本地 CPU（126 实测 `LocalEmbedder`） | 回答：传输秒级可忽略；刀2 代理一跳增量同样可忽略；**2a 设计注记** = 流式透传 + 显式超时（防大文件占内存）——已写进 §6 刀2 行 |
| **K5** | `agent_server/api/import_router.py` 的 `/import` **不是 KS 代理**（易混淆点澄清） | 67 行，`response_model=ImportResponse`，缺 PDF 依赖 400 / 无 DATABASE_URL 503；装配链实物：`main.py:41` → `api/routes.py:23` → `import_router`（已接线非死件） | 它是 agent_server **自己 pgvector KB** 的导入端点 ⇒ **不能当 2a 复用**，新代理端点仍是新端点（D7 形状不变） |

❗ **本轮计数变化**：P 10→11、R- 13→14；F/D/反证 R/N 不变。

