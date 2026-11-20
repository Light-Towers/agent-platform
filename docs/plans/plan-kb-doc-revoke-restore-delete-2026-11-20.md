# 知识库文档操作重设计：下线(可恢复) + 真删除 + 上线

> 状态：✅ 已部署 + 真环境端到端验证通过（2026-11-20 14:10，绑最终 rev=6ff6ba82，KS 镜像 1eb567a71ff3 / digest 44bfd385）。触发（用户 2026-11-20）：点"下线"后提示成功但文档仍在列表（因文档树不过滤 REVOKED），用户以为没成功；用户重新设计——下线(可恢复) 与 真删除 两个操作并存。

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
- ✅ 真环境端到端（绑 rev=6ff6ba82）：上传→下线(200,标灰REVOKED)→删除(200, found=true, deleted_chunks=1)→文档消失。完整两阶段通过。
- ✅ 真浏览器按钮显隐（线上后端）：有效文档 `["下线"]`、已下线文档 `["上线","删除"]` +「已下线」标签 + 标灰。

## 502 根因（部署中抓到并修复）
- 真删除端点稳定返回 502，但切片实际已删、文档树已消失（用户看到"失败"但文档没了）——用户视角下必须修。
- 日志 `logger.exception` 抓到真因：`TypeError: delete_document() got an unexpected keyword argument 'tenant_id'`。
- 根因：`import_router.py` 从 kb_registry import 的 `delete_document(tenant_id, knowledge_id, collection)` 被**同文件 line 618 的同名路由函数** `delete_document(knowledge_id, source_doc)` 遮蔽 ⇒ purge 的 lambda 调到路由函数而非 registry 函数。
- 修复：import 改别名 `delete_document as delete_document_registry`，lambda 调别名；加回归测试 `test_purge_registry_callback_is_correct_function`。
- 另加防御：purge 的 registry 回调异常被吞（附带清理失败不影响"切片已删"的用户目标）。

## 部署插曲（为何变久）
- 反复构建/分发（今日 4-5 轮）把 241 磁盘撑到 96%（21.38GB dangling 旧镜像）→ kubelet 给节点打 disk-pressure taint → KS Pod 无法调度卡 Pending。
- SSH 两次 reset 中断构建/分发 → 改 detached（nohup 脱离 SSH）才稳。
- 修复：`docker image prune -f` 回收 10GB，磁盘 96%→85%，taint 解除，Pod 正常调度。

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
