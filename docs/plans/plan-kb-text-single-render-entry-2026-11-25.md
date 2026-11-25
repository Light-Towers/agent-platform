# 知识库文本显示：单一渲染入口（治本，2026-11-25）

> 状态：Delivered｜触发：用户「治本方式，怎么去解决？」+ 前两轮逐处补 `#` 的反思
> 原则：`docs/principles/README.md` P3（全局统一靠机制不靠自觉）、P4（边界先行）、架构三层齐备
> 关联：`plan-kb-chunk-markdown-render-2026-11-25.md`（逐处补丁，本方案取代其散点做法）

## 1. 根因（实取，非推断）

子 agent 全链路调查（`web` → `agent_server` → `KS` → `Milvus`）结论：

- **数据层**：KS 按 Markdown 原文切块（`node_document_split.py:95` `title = 整行 '## 章节名'`），
  PDF→MD 的 `<table>` / Wingdings / `$$` 原样入库。**这是保检索的设计选择，不是 bug**。
- **展示层病根**：同一份 KB 文本走三条路径，各自决定是否剥标记——
  ① `KbUpload` 正文（本轮改 extended）② `KbUpload`/`CitationList` 标题纯插值 ③ `EvidenceList`/`Timeline` 纯插值。
  ⇒ 漏一个就是一个补丁（我前两轮：`## 本章大纲` 补正文、`#0` 补标题行，正是这个规律）。
- **契约层**：`title VARCHAR` 字段必填但允许空串，没有任何"展示标题无 `#`"的保证。

## 2. 方案（① + 轻量③）

### 轻量③：API 边界一次性归一化标题

- 新 `web/src/utils/kbText.ts`：`stripHeadingMarks(raw)` 单一实现，剥 `^#{1,6}\s+`。
- `api/kb.ts` 的 `KbTreeChunk` 增 `titleDisplay` / `parentTitleDisplay`，`listDocumentTree` 返回前一次归一化
  （保留 `title` 原字段供回显/检索，display 字段专供 UI）。调用方拿到的标题天然干净，不必各自剥。

### ①：正文单一渲染组件

- 新 `web/src/components/KbContentText.vue`：内部固定 `parseContentTokens` + `MarkdownText extended` + `AuthImage`，
  **调用方没有开关可传**（extended 封在组件里，不可能忘记）。
- `KbUpload.vue`：标题行读 `titleDisplay`、`first_title` 走 `stripHeadingMarks`、正文改用 `<KbContentText>`。

### 顺手同类（同一字段类，零风险）

- `CitationList.vue` 的 `cite.heading` 走 `stripHeadingMarks`（纯标题字段）。

### 门禁（防再散点）

- `verify-markdown.mjs` 加 H 组：行为断言（`stripHeadingMarks` 正确剥 `#`、保留正文 `#`）+ 结构断言
  （`KbContentText.vue` 存在且调用 `extended`、`KbUpload` 不再自带 `#{1,6}` 正则、`api/kb.ts` 调用归一化），
  结构判定带**自证**（造违规样本必须报红，否则门禁瞎）。

## 3. 明确不做（边界）

- **不改 KS 切分 / 不重灌历史数据**：raw content 保检索，重灌代价（KS 重建 110min + 31 图重传）不值。
- **不改聊天气泡**：`Answer` / `ChatStream` 用模型答案文本，用户拍板过"气泡行为不变"，不走 extended。
- **不改 `EvidenceList` / `Timeline`**：那是事件文案 + 片段混合文本，套渲染会动到非 KB 内容；登记为后续按面处理。
- **不引入第三方 markdown 库**：零依赖、零 v-html 纪律保持。

## 4. 验证

### 实施记录
- 新 `utils/kbText.ts`：`stripHeadingMarks()` + `firstHeadingOf()`（首个标题提取也收敛至此，KbUpload 内不再有任何 `#{1,6}` 正则）。
- `api/kb.ts`：`KbTreeChunk` 增 `titleDisplay`/`parentTitleDisplay`，`listDocumentTree` 一次归一化。
- 新 `KbContentText.vue`：封装 `parseContentTokens` + `MarkdownText extended` + `AuthImage`，调用方零开关。
- `KbUpload.vue`：标题读 display 字段、正文用 `<KbContentText>`、`first_title` 走归一化；删掉本地 `chunkTokens`/`MarkdownText`/`AuthImage` 直引。
- `CitationList.vue`：`cite.heading` 走 `stripHeadingMarks`。
- `verify-markdown.mjs`：G1–G4（归一化行为）+ H1/H2/H4/H2s（结构门禁含自证）。

### 验证读数
- `pnpm run typecheck` / `lint` / `verify:markdown` / `check:events` / `check:tokens` / `verify:sse` 全绿
- 生产那批语料（102 标题 / 10 表 / 5 sub-sup / Wingdings / `$$`）已固化为 F1–F12 黄金集
- **本地真渲染验证（无需部署）**：新 `scripts/verify-kb-render.mjs`（`pnpm run verify:kb-render`），
  用 Vite SSR + `@vue/server-renderer` 把 `KbContentText.vue` 真渲染成 HTML，喂生产真实切片语料，
  A1–A9 + B1 全过：`##` 不出现、`<h1>/<h2>/<table>/<sup>` 真渲染、表格在图片前、关系元组保留。
  这补上"解析器单测"与"部署目视"之间的缺口——**不需要部署、不需要浏览器自动化**。
- **SSR 边界（诚实标注）**：SSR 不执行客户端 `fetchImageBlob`，图片此时是 `<span 加载中…>` 占位，
  最终 `<img src=blob>` 需浏览器端加载后才出现 ⇒ 本验证证明"图片 token 在正文正确位置渲染"，
  不声称验证了图片字节。真浏览器像素级目视仍推荐（非阻塞）。
