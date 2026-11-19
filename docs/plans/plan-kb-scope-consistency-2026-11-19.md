# 对话页知识范围与知识库页一致性 + 页签刷新保持

> 状态：实现中。触发（用户 2026-11-19）：① 对话页「知识范围」下拉显示的库与知识库页列表不一致；② 切页签后刷新浏览器跳回对话页。

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

## 验证
- 后端单测（/collections doc_count 聚合注入缝）+ ruff + doc-sync；前端 typecheck/lint/6 门禁/check-events。
- 真浏览器：viewer/admin 下拉都显示 name+真实数且与知识库页一致；切页签刷新保持当前页；无权角色刷新回对话页。
