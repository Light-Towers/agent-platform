# 知识库文档操作重设计：下线(可恢复) + 真删除 + 上线

> 状态：代码完成 + 本地 CDP 验证按钮显隐通过，待部署。触发（用户 2026-11-20）：点"下线"后提示成功但文档仍在列表（因文档树不过滤 REVOKED），用户以为没成功；用户重新设计——下线(可恢复) 与 真删除 两个操作并存。

## 现状（实取）
- 当前只有"下线"：把切片 status→REVOKED，数据保留、检索不召回、**无恢复入口、无真删除**。
- 文档树读**所有**切片（含 REVOKED），所以下线后文档仍显示在列表 ⇒ 用户以为没成功。
- `verify-kb-C-libraryB` 下线后 status=REVOKED（确实成功），但文档树 doc_count 仍=1。

## 用户拍板的设计（2026-11-20 二次确认）
**两阶段操作，删除只对已下线文档开放**：
1. **有效文档**：只显示「下线」按钮（status→REVOKED，不再召回，文档标灰 +「已下线」标签，数据保留，可恢复）。
2. **已下线（REVOKED）文档**：显示「上线」（status→PUBLISHED 恢复召回）和「删除」两个按钮。
   - **删除按钮只在已下线时出现**——避免误删有效文档，删除是不可逆的真删。
   - 「删除」= 物理删 Milvus 切片 + 清 kb_documents 登记，文档从列表消失，带确认弹窗。

⇒ 用户不能一步删除有效文档，必须先下线再删除（多一道防线）。

## 实现
### 后端 KS（knowledge-service）
- `kb_delete.py` 加：
  - `restore_document(client, collection, tenant, kid, source_doc)`：把该文档 REVOKED 切片重插为 PUBLISHED（复用 revoke_document 的读-删-重插模式，status 目标改 PUBLISHED）。
  - `purge_document(client, collection, tenant, kid, source_doc)`：Milvus `delete(filter=tenant+kid+source_doc)` 真删 + 回调清 kb_documents 登记。
- `import_router.py` 加端点：
  - `POST /documents/{knowledge_id}/restore?source_doc=`（上线）
  - `DELETE /documents/{knowledge_id}/purge?source_doc=`（真删除）—— 注意与现有 `DELETE /documents/{knowledge_id}`（下线）区分路径。
- 单测：restore/purge 的纯函数逻辑（注入 client）。

### 平台代理（agent_server kb_router.py）
- `POST /kb/documents/{id}/restore` + `DELETE /kb/documents/{id}/purge`，feature `kb.publish`（同下线），签名头透传。

### 前端
- `api/kb.ts`：加 `restoreKbDocument` / `purgeKbDocument`。
- `KbUpload.vue`：文档列表每项按 `doc.chunks[].status` 判断——
  - **全部 REVOKED（已下线）**：标灰 +「已下线」标签 +「上线」「删除」两个按钮。
  - **有非 REVOKED 切片（有效）**：只显示「下线」按钮（无删除按钮）。
- 需加 `isRevoked(doc)` helper（所有 chunk status 都=REVOKED）。

## 验证
- ✅ 静态：后端 12 单测（restore/purge/revoke）+ ruff；前端 typecheck/lint/6门禁/check-events 全绿。
- ✅ 本地 CDP（mock 文档树，一有效一 REVOKED）验证**按钮显隐**（用户拍板的核心规则）：有效文档 `buttons=["下线"]`、已下线文档 `buttons=["上线","删除"]` +「已下线」标签 + 标灰。截图确认视觉。
- ⏳ 待部署 + 真环境：下线→标灰→上线→恢复召回→真删除→从列表消失；删库判据仍正确。

## 实现要点
- KB `kb_delete.py`：抽 `_delete_chunks`/`_reinsert_with_status` 通用函数；`revoke_document` 复用；新增 `restore_document`（REVOKED→PUBLISHED，无下线切片则 found=False）、`purge_document`（只删不插）。PUBLISHED 常量=字面量（本模块零 KS 依赖）。
- `kb_registry.py`：新增 `delete_document`（清登记）。
- KS `import_router.py`：`POST /documents/{id}/restore?source_doc=` + `DELETE /documents/{id}/purge?source_doc=`。
- 平台 `kb_router.py`：`_proxy_write` 加 params；新增 `POST /kb/documents/{id}/restore` + `DELETE /kb/documents/{id}/purge`（kb.publish 门控）。
- 前端 `api/kb.ts`：restoreKbDocument / purgeKbDocument；`KbUpload.vue`：`isRevoked(doc)`（所有 chunk status=REVOKED）+ 两阶段按钮；`base.css` 已下线标灰 + 激活 ry-btn--danger / ry-tag--warning（原本死类）。

## 边界
- 下线/上线/删除都按 source_doc 粒度，不动整库。
- 真删除不可逆，必须确认弹窗。
- 不改整库删除逻辑（已有）。
