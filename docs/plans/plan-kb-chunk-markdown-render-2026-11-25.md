# 知识库切片预览的 Markdown 渲染（2026-11-25）

> 状态：Delivered｜触发：用户截图问「知识库展示的时候，有这些 # 号干嘛？」+「不仅仅处理 # 号，看看还有没有别的要处理的」
> 原则：`docs/principles/README.md` P4 边界先行、用户视角（看到的与内容一致）；零 v-html、零新依赖。

## 1. 取证（实取生产 Milvus，不是猜）

对 `知识图谱 概念与技术3`（37 片）与 `后端技术中阶`（2 片）逐片扫描 Markdown 构造：

| 构造 | 数量 | 原表现 | 处置 |
|---|---|---|---|
| `#`/`##`/`###` 标题 | 102 | `#` 字面显示 | heading 块，隐藏 #，按层级渲染 |
| `<table><tr><td>` HTML 表格 | 10 表 / 298 格 | 标签字面显示，极难读 | table 块，渲染成真表格 |
| `<sub>`/`<sup>` | 5 | 标签字面显示 | 行内上下标 token |
| `\uf0e0`（PDF Wingdings 符号） | 有 | 可能显示成豆腐块 | 归一化成 `•` |
| `$$…$$` LaTeX | 少量 | 字面显示 | code 块 |
| `（无标题）` | 1 片 | 正文明明有 `# 第 3 讲关系抽取` | 从首个标题推导 |
| `<headquarters 0.7>` / `<author, book>` | 多处 | 关系抽取元组 | **原样保留，绝不当 HTML 剥掉** |

**关键陷阱（P4）**：`<headquarters 0.7>` 一类是关系抽取的元组记号，不是 HTML 标签。
若用宽泛的 `<[a-zA-Z][^>]*>` 正则剥离会丢内容 ⇒ 只认**精确闭合标签** `<sub>…</sub>` / `<sup>…</sup>`。

## 2. 方案

- `markdown.ts`：新增 `extended` 参数（**默认 false，聊天气泡行为完全不变**）。
  extended 下增加 heading / table 块、sub/sup 行内 token、`\uf0e0`→`•`、`$$`→code。
  表格只认 `<table…>…</table>` + `<tr>/<td|th>`，单元格走 `parseInline`（安全，无 v-html）。
- `MarkdownText.vue`：加 `extended` prop，模板渲染 `<h1>`–`<h6>` 与 `<table>`。
- `InlineTokens.vue`：渲染 sub/sup。
- `KbUpload.vue`：切片文本段改用 `<MarkdownText extended>`；图片仍按 `parseContentTokens` 原位内嵌；标题从首个标题回退。
- `base.css`：标题按层级降号（颜色仍 `--text-1`，不新增色）、表格边框走 `--border-decor`。

## 3. 验证（rev `c8f49b41` 之后的工作区，前端门禁全绿）

- `pnpm run typecheck` rc=0 · `pnpm run lint` rc=0
- `pnpm run verify:markdown`：E1–E5（默认模式边界）+ **F1–F12**（标题层级/隐藏 #/默认模式不变/HTML 表格/单元格/关系元组保留/sup/sub/Wingdings/LaTeX/XSS 安全）全过
- `pnpm run check:events` rc=0 · `pnpm run check:tokens` rc=0（123/123）· `pnpm run verify:sse` rc=0（168 断言）

**未覆盖**：本机无浏览器自动化工具，未做真截图确认 `<h2>`/表格在浏览器里的实际观感；
判据是解析器行为 + 前端门禁，不声称「浏览器里看到了」。需部署后人工目视复核。

## 4. 回滚

改动全在前端渲染层，不改生产数据（Milvus 切片原文原样保留）。回滚 = 还原前端 4 个文件 + CSS。
