# 知识库三级钻取修复（库→文档→切片）

> 状态：✅ 已部署 + 真浏览器验证通过（2026-11-19 09:35，绑 rev=07583c9d）。触发：用户指出 v2 的右栏显示"上传历史流水"而不是"这个库下有哪些文档"，左栏 doc_count 恒 0，业务逻辑混乱。用户明确：要的是成熟知识库平台的三级结构——左侧知识库，选中后看该库下**实际文档**，点文档看**切片信息**。不关心上传记录。

## 根因（实取确认）

1. `kb_collections.doc_count` 冗余字段恒 0，无人维护 → 左栏全显示 0。
2. 右栏读 `kb_upload_history`（每次上传/重灌一行），不是"库下有哪些文档"。
3. `kb_documents` 唯一键 `(tenant, knowledge_id)`，一库一行，支撑不了"一库多文档"。
4. **真正的数据源是 Milvus v3 集合**：chunk 的 `source_doc` 字段 = 文档名，`knowledge_id` = 所属库。实取 `kb_6ea391ada2a2` 有 1 文档 `GBT45704` / 7 切片。

## 目标三级结构

- 左栏：知识库列表（doc_count = 该库 distinct source_doc 数，实时算）
- 右栏：选中库后，列出该库下 distinct 文档（source_doc + 切片数 + 状态）
- 点文档：展开该文档的切片明细（part/heading/content）

## 实现

1. KS 加只读端点 `GET /documents/tree`：按断言租户，从 Milvus v3 集合查 knowledge_id 非空的 chunk，按 (knowledge_id, source_doc) 聚合，返回文档名 + 切片数 + 切片列表（part/heading/content）。doc_count 同步由此产生。
2. 平台代理 `GET /kb/documents/tree`（复用 kb.upload 读门控）。
3. 前端：`api/kb.ts` 加 listDocumentTree()；KbUpload.vue 右栏改为消费文档树（库→文档→切片），去掉"上传历史流水"呈现；左栏 doc_count 用文档树的真实数。
4. 保留上传能力（拖文件→上传到当前库），上传后刷新文档树。

### 删除粒度扩展（配套）
点单个文档下线时只下线该 source_doc 的切片，不能把整库都 REVOKED：
- `kb_delete.revoke_document` 加 `source_doc` 参数（None=整库旧行为兼容）；读/删 filter 加 `source_doc ==`；
- 登记表回写判据：整库删必写；单文档删仅当 `has_other_active_docs()` 为 False（无其它有效文档）才写 REVOKED；
- KS `DELETE /documents/{id}?source_doc=` + 平台 `kb_delete_document(source_doc)` 透传；前端 deleteKbDocument 加第三参。

### 字段名教训（真环境验证抓到）
Milvus v3 集合真实字段是 `title`/`parent_title`，**没有 `heading`**——初版端点请求 heading 会 502。
只读脚本 describe_collection + 实跑聚合确认，已改为 title/parent_title。真实数据读数：
10 个分片样本聚合出 6 库 / doc_count 各 1；会展库 `kb_6ea391ada2a2` 的 `GBT45704` = 1 文档 / 7 切片。

## 边界

- 不改 tenant 断言、不改向量 schema、不改检索逻辑。
- 切片内容取自 Milvus（真实入库数据），不取 summary（那是切分读数统计，非切片本身）。
- 文档下线（REVOKED）的屏蔽仍由检索侧 status 谓词负责；文档树展示的是"实际存在的文档"。

## 真环境验证（2026-11-19 09:35，绑 rev=07583c9d）
- ✅ 部署：平台 `f77a577378973` / KS `6d6322a16779d` 三节点一致；GIT_REV=07583c9d；openapi 含 `/documents/tree` + DELETE source_doc 参数；KS hostPort 冲突删旧 Pod 解决。
- ✅ 后端：`/documents/tree` 用真实 Milvus 聚合，字段对齐 title/parent_title（无 heading），6 库读数正确；720 项测试全绿。
- ✅ 真浏览器（admin CDP，独立端口 9349）：
  - 左栏文档数**真实**：`会展标准库-clean | 1 文档`、`会展标准库 | 0 文档`（不再是全 0）——直接修掉用户吐槽的"外面全 0"bug。[PASS-DOCCOUNT]
  - 选库 → 文档列表：`会展标准库-clean 的文档 1 份 · 7 片`，显示 `GBT45704 | 7 片`，不是上传历史流水。[PASS-DOCLIST]
  - 点文档 → 切片明细：展开 7 片，带标题/内容/REVOKED 状态。[PASS-CHUNKS]
  - 左栏 ✎× 按钮实测 `delWithinItem=true`（未溢出）、库名 ellipsis/nowrap 生效（185c4e01 的兜底随本批已部署生效）。
- ✅ 漂移门禁 rc=0（台账更新到 07583c9d + 新 digest）。测试账号验后降回 viewer。
