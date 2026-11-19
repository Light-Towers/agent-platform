# 对话页知识范围与知识库页一致性 + 页签刷新保持

> 状态：✅ 已部署 + 真浏览器验证通过（2026-11-19 10:45，绑 rev=26d0b21e）。触发（用户 2026-11-19）：① 对话页「知识范围」下拉显示的库与知识库页列表不一致；② 切页签后刷新浏览器跳回对话页；③ 页面无文档但删库 409；④ 左栏 ✎× 按钮溢出、无选中态。

## 根因（实取确认，绑 rev=07583c9d）
1. **显示口径不同**：对话页下拉 `App.vue:470` 显示 `kb.knowledge_id` + `kb.doc_count`；知识库页左栏显示 `kb.name` + 文档树真实数。两页都读 `GET /kb/knowledge-bases`（KS `/collections`），但：
   - `/collections` 的 `doc_count` 是恒 0 冗余字段（无人维护）
   - 知识库页左栏的真实数来自 `/documents/tree`（kb.upload 门控，viewer 拿不到）
   - 实测 `/collections` 6 库 doc_count 全 0，`name` 却都是对的（会展标准库-clean 等）
2. **刷新时机**：`refreshKnowledgeBases()` 只在 onMounted/canChat 变化时调，切页签不重拉 → 新建/改名库后切回对话页看到旧列表。
3. **页签跳回对话页**：`activeView` 是 App.vue 局部 ref，无持久化，刷新重新挂载 → 重置为 `'chat'`。

## 方案（用户拍板）
- **真实文档数走共用端点**：KS `/collections` 实时查 Milvus 按 `{knowledge_id: distinct source_doc 数}` 聚合，写入 `doc_count`。两页读同一端点同一字段，天然一致，viewer（chat.run）也能拿到真实数——避免给 viewer 开 `/documents/tree`（那会暴露全部切片正文）。
- 对话页下拉改用 `kb.name（N 篇）`；知识库页左栏保持现状（从 tree 取数，值与 /collections 一致）。
- 切回 chat 时 watch activeView 重拉 knowledgeBases + 文档数。
- activeView 持久化到 sessionStorage（关标签即失效），经 theme.ts 白名单封装；刷新后读回，**仍经 showKb/showDatasource/showRoleGate + chatShown 权限兜底**，无权回对话页。

## 存储门禁约束（check-events.mjs）
- 存储写者白名单只有 auth.ts / theme.ts；App.vue 不得直接写 localStorage/sessionStorage。
- theme.ts 已有 `readUiState`/`writeUiState`（localStorage，非凭据 UI 偏好）。本方案在 theme.ts 加 sessionStorage 档的 `readSessionState`/`writeSessionState`（C2 齿只校 auth.ts 档位，theme.ts 加 sessionStorage 不触发）。
- 只存非凭据值（视图键字符串），不存令牌。

## 额外修复（用户 2026-11-19 同批反馈）
- **删库 409 bug**：页面无文档却删不掉。根因=删库前置判据 `has_active_documents` 读 kb_documents 登记表 status，与页面读的 Milvus 实际切片漂移——空壳库（上传失败卡 DRAFT/REVIEWING，Milvus 无有效切片）登记表仍"有效"→ 409。改判据为 `has_active_chunks`（读 Milvus，与页面同源），fail-closed（Milvus 不可达拒绝删）。
- **左栏样式统一**：用户截图（浅色主题）✎× 溢出卡片 + 无选中态。根因 `.kb-sidebar__pick` 用 `width:100%` 占满行；改为 `flex:1 1 auto`（同会话列表），行内按钮小 padding+次要色；加 `is-active` 选中态（蓝边+底色，同会话列表），由父组件传 `selectedId`。

## 验证（2026-11-19 10:45，绑 rev=26d0b21e）
- ✅ 静态：后端 725 测试 + ruff + doc-sync；前端 typecheck/lint/6 视觉门禁/check-events 全绿。
- ✅ 部署：平台 `5ef9ca73d7d3` / KS `23cc728e239d` 三节点一致；GIT_REV=26d0b21e；KS 新聚合返回真实 doc_count；KS hostPort 冲突删旧 Pod。
- ✅ API：`/collections` doc_count 真实（会展库-clean=1 / 空壳库=0，不再全 0）；空壳库 `kb_75222a54523e` 删除返回 200（不再 409）且从列表消失。[PASS-1][PASS-3]
- ✅ 真浏览器（CDP，admin）：下拉显示 `会展标准库-clean（1 篇）`（name+真实数，与知识库页一致）；切知识库页刷新后 title=知识库页/kbVisible=true/chatVisible=false（保持当前页）；选中态 activeCount=1、✎× `delWithinItem=true`（不溢出）。[PASS-2][PASS-4]
- ✅ 漂移门禁 rc=0（台账更新到 26d0b21e + 新 digest）。测试账号验后降回 viewer。
