# 知识库删除 + 管理页方案（2026-11-18）

> 状态：**P1/P2/P3 代码全部完成并提交**（2026-11-18）；P1/P2 已真环境部署验证（绑 rev=b82425de），P3 代码全绿但真环境待验（见 §9）。触发：用户问「上传历史那么多 ID 是什么、能删吗」→ 明确诉求：单文档删 + 整库删 + 库下有文档禁删 + 新建知识库管理页；删除语义选**软删除（REVOKED）**。
> 本文定义做什么/为什么/验收（问题空间）+ 实现口径（design），具体代码已落地。

## 0. 现状事实（代码实取，非猜测）

| 事实 | 证据 |
|---|---|
| 前端「上传历史」显示的 ID = `task_id`（UUID，一次上传一个） | `KbUpload.vue:71,511`；`/kb/history` → KS `/history` → `kb_upload_history` 按 task_id 一行 |
| 另有 `knowledge_id`（知识库 ID）= 你上传时填的，登记/发布/检索的锚点 | kb_registry 唯一键 `(tenant_id, knowledge_id)` |
| 两张 Mongo 表都**无 delete**：`kb_documents`（登记，一库一行）、`kb_upload_history`（历史，一传一行） | `kb_registry.py:146`、`kb_upload_history.py:107` 的 `__all__` |
| 生命周期已有 `REVOKED`/`EXPIRED` 软删除语义，但无触发端点；`/reimport` 只支持 DRAFT→REVIEWING→PUBLISHED | `knowledge_lifecycle.py:34-40`；`kb_router.py:219` 转 KS /reimport |
| **KS/Milvus 检索层不按 status 过滤**，chunk schema 无 status 字段 | `milvus_config.py` 无 status；`document_store.py:50` schema v2 字段清单 |
| `DocumentStore.delete_document` 按 **doc_id** 删，非 knowledge_id；是硬删除向量 | `document_store.py:312-324` |
| 前端无独立知识库管理页，只有上传页 KbUpload.vue；`/kb/knowledge-bases` 仅用于填充上传下拉 | `App.vue:72`；`kb_router.py:329` |

**推论（决定方案的关键）**：选了软删除，但"REVOKED 不召回"目前**没有现成机制**——因为向量 chunk 里没有 status 字段、检索不过滤 status。所以软删除要成立，必须新增一条"按 knowledge_id 屏蔽召回"的通路。

## 1. 目标

1. 单文档删：把某个 `knowledge_id` 标记 REVOKED，对话检索不再召回它。
2. 整库删：把整个知识库标记删除；**前置条件**：该库下已无有效文档（全部 REVOKED）才允许。
3. 新建知识库管理页：列出全部库（含文档数/状态）、每库下文档列表、删除操作入口。
4. 全程 tenant 隔离（签名断言）不变；删除不可逆操作的审计留痕。

## 2. 明确不做（本期边界）

- 不硬删除向量/文件/Mongo 记录（选软删除，数据可恢复）。
- 不改 tenant 断言/签名头链路。
- 不做权限细化（沿用 kb.publish 门控删除，理由见 §4）。
- 不做回收站/定时清理（REVOKED 数据永久保留，后续单独立项）。

## 3. 核心设计决策（待评审拍板）

### D1：软删除如何让检索不再召回（最关键）— **已定：chunk 加 status 字段**
向量 chunk 无 status 字段。三个候选：
- **(a) 屏蔽名单**：维护一张 `tenant + knowledge_id → revoked` 的注册表（Mongo），检索时查该名单，从召回结果里过滤掉 revoked 的 knowledge_id。优点不动向量/schema；缺点每次检索多一次名单查询（可缓存）。
- **(b) chunk 加 status 字段 ✅用户已选**：schema v2→v3 + 写入/重灌时带 status，检索谓词加 `status != REVOKED`。优点过滤在引擎侧、最干净；缺点要改 schema、全量重灌、动 KS/平台两侧（本次刚统一的链路，风险高）。
- **(c) 复用 kb_documents 状态**：检索前按 knowledge_id 查登记状态，非 PUBLISHED 的不召回。与 (a) 类似但复用现有表。

**代价（必须计入排期）**：schema v3 需 KS `node_import_milvus.create_collection` 与平台 `document_store._create_collection` 两侧逐字段镜像同步（有测试钉死镜像）；存量 PUBLISHED 文档需全量重灌进新集合（真环境运维动作）；两侧检索过滤都要加 status 谓词。

### D2："库下有文档禁删"的判据 — 待细化
kb_documents 一库一行（upsert 覆盖），"库下文档"实际是 kb_upload_history 里同 knowledge_id 的多条。判据候选：
- 该 knowledge_id 在 kb_documents 的状态 != REVOKED ⇒ 有有效文档 ⇒ 禁删库；
- 或按 kb_upload_history 里同 knowledge_id 且 status=completed 的条数。
**倾向前者**（登记状态为准，简单可靠），待 design 定。

### D3：删除用哪个 feature 门控 — 待细化
删除属写操作。候选：复用 `kb.publish`（有发布权即有权下线）vs 新增 `kb.delete`。**倾向复用 kb.publish**（少加权限码，角色矩阵不用动），待 design 定。

### D4：知识库"删除"后如何表示 — **已定：新增知识库注册表（治本）**
当前 kb_documents 没有"库"这张表——库即 knowledge_id 分组。三个候选：
- **(a) 新增 kb_collections 注册表 ✅用户已选（治本）**：建 kb_collections 表存库元数据（id/name/tenant/owner/状态），文档通过 knowledge_id 关联。整库删=标记该行 deleted，判据=无有效关联文档。模型最清晰。
- (b) 不建表，用列表视图：改动小但"库"无独立生命周期。
- (c) 重定义数据模型：影响面爆炸，独立立项。

**治本理由**：① "整库删"+"库下有文档禁删"两个判据必须有"库"这个一等实体才能落地（当前聚合视图无根）；② 容器与内容分离是标准关系建模，文档通过 knowledge_id 外键关联库；③ 避免未来给库加元数据/权限/共享时推翻重来。

**代价**：上传写入路径要改造（上传前确保 kb_collections 里库存在/自动创建）；`/kb/knowledge-bases` 改为查注册表；删除判据=查关联文档。

## 4. 验收判据（每层可核对）

- 单文档删：标记 REVOKED 后，对话检索该 knowledge_id 的验证盐**不再命中**；其他库照常召回。
- 整库删前置：库下有 PUBLISHED 文档时删除返回拒绝（明确原因）；全部 REVOKED 后允许删库。
- 管理页：列出全部库 + doc_count + status；删除按钮在库下有文档时禁用并提示。
- 租户隔离：跨租户删不到对方的库（签名断言）。
- 单测：delete 模块的租户过滤 + 状态迁移合法性（REVOKED 只能从 PUBLISHED 等合法态迁入）；检索屏蔽名单的可证性。

### P3 详细设计（实现口径，2026-11-18 钉死）

| 决策 | 取值 | 理由 |
|---|---|---|
| 软删除落地 | 向量侧重写 status=REVOKED（读切片→改 status→删旧→重插，向量原样复用） | pymilvus 无 update；P2 已把过滤做成向量侧 status 谓词，保持一致 |
| D2 禁删判据 | kb_documents 该库下有非 REVOKED 登记文档 ⇒ 禁删库（409） | 登记状态为准，简单可靠（用户拍板） |
| D3 门控 | 复用 kb.publish（有发布权即可下线） | 少加权限码，角色矩阵不动（用户拍板） |
| 单文档删 | `kb_delete.revoke_document`：读→删→用 REVOKED 重插 + 回写 kb_documents 状态 | 纯逻辑注入缝，5 单测覆盖租户隔离/向量原样/去主键 |
| 整库删 | `kb_delete.delete_collection_guard`：前置校验 + kb_collections.mark_deleted | 有有效文档 409、库不存在 404 |
| status 值域 | 正常文档=生命周期状态（PUBLISHED/REVIEWING…），软删除=REVOKED（见 P2 §8） | 过滤 `status != REVOKED` 天然排除软删项 |
| 前后端端点 | KS `DELETE /documents/{id}` + `DELETE /collections/{id}`；平台代理同名 + 管理页 KnowledgeBaseAdmin.vue | 平台纯代理，签名头透传；前端删单文档/删库二段确认 |

### P2 详细设计（实现口径，2026-11-18 钉死）

| 决策 | 取值 | 理由 |
|---|---|---|
| status 字段 | `VARCHAR(16)`，值域 `active` / `REVOKED`（对齐 KNOWLEDGE_STATUS.REVOKED） | 用生命周期已有枚举值，不另造 |
| 过滤语义 | 检索谓词加 `status != "REVOKED"` | **兼容存量**：老数据 status 为空/未设仍可召回；只有显式 REVOKED 被排除。重灌前不会误伤 |
| 集合名 | `platform_doc_v3_bge_m3` | Milvus 不支持给已有集合加字段 ⇒ 必须新集合；v2 集合保留可回滚 |
| 写入侧 status | KS `_enrich_chunk_metadata` 补 `status`（默认 active）；平台 `add_documents` 同样带 | 两侧镜像；缺省 active 保证新写入即有效 |
| 两侧过滤 | KS `milvus_filter_utils.build_retrieval_filter` + 平台 `document_store._build_filter` 都加 | 检索经两条路径（KS /api/v1/retrieve + 平台 DocumentStore），都要屏蔽 |
| schema 镜像测试 | `test_milvus_create_collection_mirrors_ks_schema` 加 status 断言 | 钉死两侧同步 |

**P2 拆两步落地**（代码与运维分离，各自可独立验证/回滚）：
- **P2-code**：schema 字段 + 集合名 + 两侧 filter + 写入侧 status + 单测。**不动真环境**——新集合在首次上传时由 KS 管线自动创建。
- **P2-data**：存量 PUBLISHED 文档重灌进 v3 集合（D3 运维动作，须单独授权 + 窗口）。重灌完成前 v3 集合为空、对话检索会退化——故 P2-code 与 P2-data 之间要尽量短，或先重灌再切配置。

### P2 真环境取证读数（2026-11-18，绑 rev=b82425de）

- 部署：平台镜像 `0449d9c1` / KS 镜像 `d3871b50` 三节点一致；GIT_REV=b82425de；health 200。
- 配置：平台 settings=`milvus platform_doc_v3_bge_m3 1024`；KS CHUNKS_COLLECTION=v3；PG chunks.status 列存在（migration 021）。
- 正向：新传 verify-p2-v3 → v3 集合自动创建 + 切片 status 字段在位 → 对话命中 3319。
- 重灌：4 条存量（verify-kb-A-7Q3 / C-libraryA / C-libraryB / final）从 v2 搬到 v3，各 1 切片，0 失败；v3 集合共 5 库；对话命中存量 TQ-7749，断链窗口关闭。
- 漂移门禁：台账基线更新后 verify_basis_drift rc=0。

**P2 暴露的两个 bug（已修，记此备查）**：
1. **config.py 集合名漏改**：P2-code 改了 `document_store.DEFAULT_DOC_COLLECTION=v3`，但工厂实际读 `get_settings().doc_milvus_collection`（config.py Field 默认仍 v2）⇒ 平台上线后仍连 v2。修复需再改 config.py + .env.example 并重Build镜像（commit b82425de）。**教训：改"默认值"要改真正被消费的那一处，不能只改协议层常量。**
2. **重灌脚本 PUBLISHED→PUBLISHED 被拒**：原脚本逐个 POST /reimport（走合法迁移表），PUBLISHED→PUBLISHED 报 400。改为 pymilvus 直搬（v2 读切片→补 status→写 v3，幂等），commit fe97eb19。**教训：重灌 ≠ 改生命周期状态，PUBLISHED 文档重灌要走切片搬迁而非 /reimport。**

**status 值域真相**：写入的 status 是**生命周期状态**（PUBLISHED/REVIEWING…），不是 spec 早期写的 active/REVOKED。检索过滤 `status != REVOKED` 仍能正确排除软删除项（PUBLISHED != REVOKED 为真）。P3 删除端点写 `status=REVOKED` 即可，正常文档保持 PUBLISHED。

## 5. 影响面与落地顺序（T3，按依赖分阶段）

**总定性**：D1(chunk status) + D4(注册表) 两个最规范选择叠加 = T3 级（1.5–3w 量级），不是一两个小时。必须分阶段，每阶段可独立验证。

| 阶段 | 内容 | 可独立验证的判据 | 风险 |
|---|---|---|---|
| P1 数据模型底座 | 新增 kb_collections 注册表 + 上传写入路径改造（上传前确保库存在）+ `/kb/knowledge-bases` 改查注册表 | 上传自动建库；列表返回库元数据；租户隔离 | 低 |
| P2-code schema v3 + 过滤（**已完成 2026-11-18**）| 两侧 create_collection 加 status 字段（镜像同步测试）；新集合名 platform_doc_v3_bge_m3；两侧检索谓词加 `status != REVOKED`；pgvector migration 021 + store.py 谓词 | **1234 passed / 9 skipped**；ruff/doc-sync/migration lint 绿 | 低（纯代码，未动真环境）|
| P2-data 切集合名 + 重灌（**已完成 2026-11-18**）| KS CHUNKS_COLLECTION 切 v3；存量 PUBLISHED 全量重灌进 v3；真环境 PG 跑 migration 021 | **重灌 4 条成功 0 失败**；v3 集合 5 库齐全；对话检索命中存量 TQ-7749；漂移门禁 rc=0 | 高（已完成）|
| P3 删除端点 + 管理页（**代码完成 2026-11-18，真环境待验**）| DELETE 单文档（→REVOKED）+ DELETE 整库（前置校验无有效文档）；新建 KnowledgeBaseAdmin.vue | **708 passed / 20 skipped**；前端 6 门禁全绿；ruff/doc-sync 绿 | 中（真环境验证待做）|

**顺序理由**：P1 先让"库"成为一等实体（D4 判据才有根）；P2 是最高风险的重灌，单独一个阶段可回滚验证；P3 依赖 P1 的库实体和 P2 的 status 过滤才成立。**不要跳过 P2 直接做 P3**——没有 status 字段，REVOKED 无法在检索层生效。

## 6. 复审触发条件

- 改检索过滤口径 / chunk schema / 状态迁移表后，§4 验收判据全部重跑。
- 软删除屏蔽名单若加缓存，须定义失效判据（删除后多久生效），并纳入取证。

## 9. 最终交付状态（2026-11-18）

| 阶段 | 代码 | 真环境 | 提交 |
|---|---|---|---|
| P1 库实体 | 完成（6 单测）| ✅ 部署验证（上传自动建库、/collections 列表）| `80c84590` |
| P2 schema v3 + 重灌 | 完成（1234 passed）| ✅ 部署验证（v3 集合、新传命中、4 存量重灌、漂移门禁 rc=0）| `f8d887de`→`b82425de`→`fe97eb19`→`d6afe912` |
| P3 删除端点 + 管理页 | 完成（708 passed + 前端 6 门禁）| ⏳ **待验**（当前真环境仍是 P2 镜像，无 P3 端点）| `dfe37503` |

### P3 真环境待验清单（下一轮，D3 全链路）
1. bundle `dfe37503` → 241 checkout → 重建两侧镜像（前端管理页需进平台镜像）→ 三节点分发 → rollout。
2. 删单文档真验：对 verify-kb-C-libraryB 下线 → 该库验证盐 4477 不再被对话检索召回；其它库照常。
3. 删库前置真验：库下有 PUBLISHED 文档时 DELETE /collections/{id} 返回 409；先把文档下线（REVOKED）后再删库成功、/collections 列表不再出现。
4. 租户隔离真验：default 租户删不到其它租户的库。
5. 验后更新漂移门禁台账到 P3 的 rev/digest。

> 当前线上状态：平台/KS 均为 P2 镜像（rev b82425de），DOC_BACKEND=milvus，v3 集合 5 库齐全，健康 200。P3 代码已入库但未上线，线上无删除端点。
