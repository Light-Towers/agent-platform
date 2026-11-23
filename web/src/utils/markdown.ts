/* ============================================================================
 * markdown.ts — 聊天气泡的极简 Markdown 解析（零依赖、零 v-html、零 XSS）
 *
 * 为什么自己解析而不上 marked + DOMPurify：本平台气泡里出现的 Markdown 只有
 * 四种形态（加粗/行内代码/有序或无序列表/```代码块），引第三方库要改 pnpm-lock、
 * Dockerfile 与内网构建链，且 v-html 一旦漏 sanitize 就是把模型输出当 HTML 执行。
 * ⇒ 这里把文本解析成**结构化 token 数组**，模板只用 Vue 插值渲染，模型输出永远是文本。
 *
 * 支持的子集（够覆盖 /query 答案与 /history 原文里实际出现的格式）：
 *   · **加粗**  → 行内 strong
 *   · `行内码`  → 行内 code
 *   · "1. xxx" / "- xxx" / "* xxx" → 有序/无序列表项（连续行合并成一个 list 块）
 *   · ``` 起止   → 代码块（内部原样，不做行内解析）
 *   · 其它      → 段落（连续行合并，空行分段）
 * 不支持的写法（标题 #、链接 []() 等）按段落原样显示——不丢字，只是不美化。
 * ==========================================================================*/

export type InlineToken =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'ref'; text: string }

export type MdBlock =
  | { kind: 'paragraph'; lines: readonly InlineToken[][] }
  | { kind: 'list'; ordered: boolean; items: readonly InlineToken[][] }
  | { kind: 'code'; lines: readonly string[] }

/** 解析一行里的 **加粗**、`行内码` 与 `[n]` 引用角标；未闭合的标记按普通文本保留，不吞字。 */
export function parseInline(line: string): InlineToken[] {
  const out: InlineToken[] = []
  let buf = ''
  let i = 0
  const flush = () => {
    if (buf) { out.push({ kind: 'text', text: buf }); buf = '' }
  }
  while (i < line.length) {
    if (line.startsWith('**', i)) {
      const end = line.indexOf('**', i + 2)
      if (end > i + 2) {
        flush()
        out.push({ kind: 'strong', text: line.slice(i + 2, end) })
        i = end + 2
        continue
      }
    }
    if (line[i] === '`') {
      const end = line.indexOf('`', i + 1)
      if (end > i + 1) {
        flush()
        out.push({ kind: 'code', text: line.slice(i + 1, end) })
        i = end + 1
        continue
      }
    }
    // [n] 引用角标：只认 1–3 位数字，渲染层据此锚定证据卡片；其它方括号按文本保留。
    if (line[i] === '[') {
      const ref = line.slice(i + 1).match(/^(\d{1,3})\]/)
      if (ref) {
        flush()
        out.push({ kind: 'ref', text: ref[1] ?? '' })
        i += 1 + (ref[0]?.length ?? 0)
        continue
      }
    }
    buf += line[i]
    i += 1
  }
  flush()
  return out
}

/** 是否列表行；返回有序标记与去掉标记后的正文。 */
function listLine(line: string): { ordered: boolean; body: string } | null {
  const ol = line.match(/^(\d+)\.\s+(.*)$/)
  if (ol) return { ordered: true, body: ol[2] ?? '' }
  const ul = line.match(/^[-*]\s+(.*)$/)
  if (ul) return { ordered: false, body: ul[1] ?? '' }
  return null
}

/** 把整段文本解析成块数组。 */
export function parseMarkdown(text: string): MdBlock[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: MdBlock[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''

    // 代码块：``` 起，到下一个 ``` 止（或到末尾，宽大地收尾）
    if (line.trimStart().startsWith('```')) {
      const code: string[] = []
      i += 1
      while (i < lines.length && !(lines[i] ?? '').trimStart().startsWith('```')) {
        code.push(lines[i] ?? '')
        i += 1
      }
      if (i < lines.length) i += 1 // 跳过收尾 ```
      blocks.push({ kind: 'code', lines: code })
      continue
    }

    // 空行：结束当前段落
    if (line.trim() === '') { i += 1; continue }

    // 列表：连续同类型列表行合成一块
    const first = listLine(line)
    if (first) {
      const items: InlineToken[][] = []
      while (i < lines.length) {
        const item = listLine(lines[i] ?? '')
        if (!item || item.ordered !== first.ordered) break
        items.push(parseInline(item.body))
        i += 1
      }
      blocks.push({ kind: 'list', ordered: first.ordered, items })
      continue
    }

    // 段落：连续非特殊行合成一块（行间用软换行，模板里每行一个 span）
    const para: InlineToken[][] = []
    while (i < lines.length) {
      const l = lines[i] ?? ''
      if (l.trim() === '' || l.trimStart().startsWith('```') || listLine(l)) break
      para.push(parseInline(l))
      i += 1
    }
    if (para.length) blocks.push({ kind: 'paragraph', lines: para })
  }
  return blocks
}
