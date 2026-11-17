#!/usr/bin/env node
/* ============================================================================
 * verify-markdown.mjs — 聊天气泡 Markdown 解析器的行为断言
 *
 * 真 import markdown.ts（Node ≥22 原生 TS 类型擦除），喂真实答案文本，断言块结构：
 *   · 用户那段「证据为无」回答：段落 + 有序列表(3) + 加粗 token + 来源段落
 *   · 代码块围栏、行内码、未闭合标记按文本保留、XSS 串当文本不解析
 * 与 check-events.mjs 的分工：那件锁源码结构，这件锁解析行为（喂文本才测得出）。
 * 加载失败必须 rc=1（不把跑不动吞成跳过）。
 * ==========================================================================*/
import { parseInline, parseMarkdown } from '../src/utils/markdown.ts'

let failures = 0
const ok = (cond, name) => {
  if (cond) console.log('  ✓', name)
  else { console.log('  ✗', name); failures += 1 }
}

const SAMPLE = `当前证据为“无”，因此**无法确认我能帮你做的完整事项范围**。根据历史记忆，只能确认可能涉及以下几类：

1. **租户业务数据相关查询**：需按租户隔离，业务数据须带 \`tenant_id\`；但未列明具体业务种类。
2. **展会分析数据相关查询**：如展台浏览及收藏量、展品浏览及收藏量、浏览时间等。
3. **记忆数据相关事项**：分为 \`episodic\`、\`semantic\`、\`procedural\` 三类；技能与共享知识在租户内共享、跨租户隔离。

结论：只能确认上述几类，**不能确认完整能力清单**。你可以继续提出具体问题，或提供证据让我进一步判断。
来源：历史记忆中的相关问答。`

console.log('§A 真实回答样本解析')
const blocks = parseMarkdown(SAMPLE)
ok(blocks.length === 3, `A1 解析成 3 块（引言/列表/结论+来源，实得 ${blocks.length}）`)
const list = blocks.find((b) => b.kind === 'list')
ok(!!list && list.ordered && list.items.length === 3, 'A2 有序列表 3 项')
const firstPara = blocks[0]
ok(firstPara.kind === 'paragraph' && firstPara.lines[0].some((t) => t.kind === 'strong' && t.text === '无法确认我能帮你做的完整事项范围'),
   'A3 首段含加粗 token「无法确认…」')
const item1 = list?.items[0] ?? []
ok(item1.some((t) => t.kind === 'strong') && item1.some((t) => t.kind === 'code' && t.text === 'tenant_id'),
   'A4 列表项含加粗 + 行内码 tenant_id')
ok(blocks.filter((b) => b.kind === 'paragraph').length === 2, 'A5 两段正文（引言 + 结论来源连续行）')

console.log('§B 代码块与边界')
const codeSample = '前文\n```python\nprint("hi")\nx = 1\n```\n后文'
const cb = parseMarkdown(codeSample)
const codeBlock = cb.find((b) => b.kind === 'code')
ok(!!codeBlock && codeBlock.lines.length === 2 && codeBlock.lines[0] === 'print("hi")', 'B1 代码块原样保留内部行')
ok(cb.filter((b) => b.kind === 'paragraph').length === 2, 'B2 代码块前后各一个段落')

console.log('§C 行内解析与安全')
ok(JSON.stringify(parseInline('**未闭合')) === JSON.stringify([{ kind: 'text', text: '**未闭合' }]),
   'C1 未闭合 ** 按文本保留')
ok(parseInline('a `b` c').some((t) => t.kind === 'code' && t.text === 'b'), 'C2 行内码解析')
const xss = parseInline('<img src=x onerror=alert(1)> **粗**')
ok(xss.some((t) => t.kind === 'text' && t.text.includes('<img')), 'C3 HTML 串当文本（无 v-html，天然安全）')

console.log(`\n合计：${failures === 0 ? '全部通过' : failures + ' 条失败'}`)
process.exit(failures === 0 ? 0 : 1)
