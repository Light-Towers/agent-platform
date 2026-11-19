# 修复：上传解析成功但刷新后文档没了（上传即入库）

> 状态：代码完成，待部署。触发（用户 2026-11-19）：选测试库上传文档，解析成功，刷新后文档没了。绑诊断时的 rev=26d0b21e。

## 根因（实取坐实，非猜测）
1. 测试库 `kb_d73b8969113d` 上传历史有 2 条 `知识图谱 概念与技术3.pdf`，均 completed、33 切片。
2. 但 Milvus 里该 knowledge_id **0 条切片**，文档树 / 库列表 doc_count=0 → 刷新后空。
3. 日志显示管线 8 步全走完（含"向量生成"），但"导入向量库"节点无任何写入日志。
4. 代码定位：`node_import_milvus.py:70-74` 用 `should_publish_to_production(state)` 判非 PUBLISHED（前端上传默认 DRAFT）→ **跳过生产入库**，仅审计留痕。metadata 校验还要求 authority/exhibition_id 等 6 字段（前端默认空），即使改 PUBLISHED 也会被二次跳过。

本质：生命周期门禁有意设计，但 UI 没给发布入口 → "上传成功"是假象（解析了但没入库），产品体验断链。

## 决策（用户拍板）
「上传即入库，去掉隐藏门禁」——用户传完看到成功，文档就该可见可检索，不该还要走隐藏的发布步骤。

## 实现
- `node_import_milvus.py`：去掉 `should_publish_to_production` 跳过门禁；新增纯函数 `should_skip_import(state)`——只有 status=REVOKED（删除态）跳过，其余（DRAFT/REVIEWING/PUBLISHED/空）都写入 Milvus。
- 检索侧谓词恒为 `status != REVOKED`（`build_retrieval_filter`），DRAFT 切片天然可召回 ⇒ 上传即可检索。
- 不动 `should_publish_to_production` 函数本身（生命周期契约 + exhibition-agent 测试保留）。
- 前端不改（form 默认 DRAFT 现在直接入库）。

## 测试更新（业务语义变更，非凑绿）
- `test_upload_import_immediately.py`（新）：钉 DRAFT/REVIEWING/PUBLISHED/空入库、REVOKED 跳过。
- exhibition-agent `TestImportMilvusLifecycleGate.test_draft_state_skips_milvus_insert` → 改名 `test_draft_state_proceeds_to_milvus`，改钉 should_skip_import。
- `TestMultiTenantIsolation` 4 条：旧断言精确相等不含 status 谓词，软删除（前批）加了 `status != REVOKED` 后漂移——改为"含目标子串 + 含 REVOKED 谓词"。属历史测试漂移修复。
- 全组 36 passed，ruff 绿。

## 待部署验证
- 重建 + 分发 KS 镜像（平台无改动）后 rollout。
- 真环境：传一份文档到测试库 → 上传 completed → 文档树出现该文档 + 对话能检索 → 刷新后仍在。
