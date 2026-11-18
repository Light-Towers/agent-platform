# 知识库删除 + 管理页方案（2026-11-18）

> 状态：**待评审**（Spec 先行，实现未开始）。触发：用户问「上传历史那么多 ID 是什么、能删吗」→ 明确诉求：单文档删 + 整库删 + 库下有文档禁删 + 新建知识库管理页；删除语义选**软删除（REVOKED）**。
> 本文只定义**做什么/为什么/验收**（问题空间）；具体改哪些函数、SQL、组件属 design/实现阶段。

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

## 5. 影响面与落地顺序（T3，按依赖分阶段）

**总定性**：D1(chunk status) + D4(注册表) 两个最规范选择叠加 = T3 级（1.5–3w 量级），不是一两个小时。必须分阶段，每阶段可独立验证。

| 阶段 | 内容 | 可独立验证的判据 | 风险 |
|---|---|---|---|
| P1 数据模型底座 | 新增 kb_collections 注册表 + 上传写入路径改造（上传前确保库存在）+ `/kb/knowledge-bases` 改查注册表 | 上传自动建库；列表返回库元数据；租户隔离 | 低 |
| P2 schema v3 + 重灌 | 两侧 create_collection 加 status 字段（镜像同步测试）；新集合名；存量 PUBLISHED 全量重灌；两侧检索谓词加 `status != REVOKED` | schema 镜像测试绿；重灌后检索正常；status 过滤生效 | **高（真环境运维重灌）** |
| P3 删除端点 + 管理页 | DELETE 单文档（→REVOKED）+ DELETE 整库（前置校验无有效文档）；新建 KnowledgeBaseAdmin.vue | §4 全部验收判据 | 中 |

**顺序理由**：P1 先让"库"成为一等实体（D4 判据才有根）；P2 是最高风险的重灌，单独一个阶段可回滚验证；P3 依赖 P1 的库实体和 P2 的 status 过滤才成立。**不要跳过 P2 直接做 P3**——没有 status 字段，REVOKED 无法在检索层生效。

## 6. 复审触发条件

- 改检索过滤口径 / chunk schema / 状态迁移表后，§4 验收判据全部重跑。
- 软删除屏蔽名单若加缓存，须定义失效判据（删除后多久生效），并纳入取证。
