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
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseInline, parseMarkdown } from '../src/utils/markdown.ts'
import { stripHeadingMarks } from '../src/utils/kbText.ts'

const webRoot = fileURLToPath(new URL('../', import.meta.url))
const src = (rel) => readFileSync(webRoot + rel, 'utf8')

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

console.log('§D 引用角标（R5a）')
ok(parseInline('见 [1] 与 [12]').filter((t) => t.kind === 'ref').map((t) => t.text).join(',') === '1,12',
   'D1 数字角标解析为 ref token（供证据锚定）')
ok(parseInline('[abc] 与 [12x] 按文本').every((t) => t.kind !== 'ref'),
   'D2 非数字方括号不误判为角标，按文本保留')

console.log('§E 不支持语法的边界（R5c：不丢字、不进 HTML）')
const table = '| 列1 | 列2 |\n| --- | --- |\n| a | b |'
const tb = parseMarkdown(table)
ok(tb.length > 0 && tb.every((b) => b.kind === 'paragraph' || b.kind === 'list'),
   'E1 表格按普通段落逐行显示（不丢字、不假装有表格块）')
ok(tb.map((b) => b.kind === 'paragraph' ? b.lines.map((line) => line.map((t) => t.text).join('')).join('') : '').join('').includes('列1'),
   'E2 表格原文未被吞掉')
const nested = '1. 第一层\n   - 第二层\n2. 另一项'
const nb = parseMarkdown(nested)
ok(JSON.stringify(nb).includes('第二层'), 'E3 多级缩进列表的内层文字仍上屏')
ok(parseMarkdown('前文\n```js\nconst x = 1\n```\n后文').filter((b) => b.kind === 'code').length === 1,
   'E4 代码块边界仍成立')
const xss2 = parseInline('<img src=x onerror=alert(1)> [1]')
ok(xss2.some((t) => t.kind === 'text' && t.text.includes('<img')), 'E5 XSS 串仍按文本')

console.log('§F extended（知识库切片预览，PDF→MD 产物）')
const headingSrc = '# 第 3 讲\n\n## 本章大纲\n\n正文'
const hb = parseMarkdown(headingSrc, true)
const heads = hb.filter((b) => b.kind === 'heading')
ok(heads.length === 2 && heads[0].level === 1 && heads[1].level === 2, 'F1 标题解析成 heading 块且层级正确')
ok(heads[0].tokens.every((t) => !t.text.includes('#')), 'F2 # 号不进渲染文本')
ok(parseMarkdown(headingSrc).every((b) => b.kind !== 'heading'), 'F3 默认模式不变（聊天气泡仍不美化标题）')

const tableSrc = '<table><tr><td>Pattern</td><td>Example</td></tr><tr><td>PERSON</td><td>George</td></tr></table>'
const tbl = parseMarkdown(tableSrc, true).find((b) => b.kind === 'table')
ok(!!tbl && tbl.rows.length === 2 && tbl.rows[0].length === 2, 'F4 HTML 表格解析成 2x2 table 块')
ok(tbl.rows[1][0][0].text === 'PERSON', 'F5 表格单元格文本正确')
ok(parseMarkdown(tableSrc).every((b) => b.kind !== 'table'), 'F6 默认模式表格仍按段落')

// 关键边界：关系抽取元组 <headquarters 0.7> 不是 HTML，绝不能被剥掉
const tuple = 'ORGANIZATION {<headquarters 0.7> <in 0.7>}'
const tupleTokens = parseInline(tuple, true)
ok(tupleTokens.some((t) => t.text.includes('<headquarters 0.7>')), 'F7 关系元组原样保留（不误判 HTML）')

ok(parseInline('特朗普<sup>“</sup>新政', true).some((t) => t.kind === 'sup' && t.text === '“'), 'F8 sup 解析为行内上标')
ok(parseInline('bootstra<sub>pp</sub>in', true).some((t) => t.kind === 'sub' && t.text === 'pp'), 'F9 sub 解析为行内下标')
const wing = parseMarkdown('• 项\n\n\uf0e0 bootstra', true)
ok(JSON.stringify(wing).includes('• bootstra'), 'F10 Wingdings \uf0e0 归一成 •')
const latex = parseMarkdown('前文\n$$\n\\{< - 0. 75 >\n$$\n后文', true)
ok(latex.filter((b) => b.kind === 'code').length === 1, 'F11 $$…$$ 解析成代码块')
const xss3 = parseInline('<img src=x onerror=alert(1)> **粗**', true)
ok(xss3.some((t) => t.kind === 'text' && t.text.includes('<img')), 'F12 extended 下 XSS 串仍按文本（无 v-html）')

console.log('§G 标题显示单一归一化（kbText.ts，治本）')
ok(stripHeadingMarks('## 本章大纲') === '本章大纲', 'G1 剥 ## 标题标记')
ok(stripHeadingMarks('# 第 3 讲') === '第 3 讲', 'G2 剥 # 标题标记')
ok(stripHeadingMarks('正文 # 话题') === '正文 # 话题', 'G3 非行首 # 原样保留')
ok(stripHeadingMarks(null) === '' && stripHeadingMarks('') === '', 'G4 空值兜底')

console.log('§H 单一渲染入口门禁（结构断言 + 自证）')
// 判定函数本体（自证与真面共用同一把尺，避免"自证能咬、真面用另一套"）
const isScatterViolation = (text) => /chunkTokens\s*\(/.test(text) || /#\{1,6\}\\s/.test(text)
const kbContentSrc = src('src/components/KbContentText.vue')
const kbUploadSrc = src('src/components/KbUpload.vue')
const kbApiSrc = src('src/api/kb.ts')
ok(kbContentSrc.includes('parseContentTokens') && kbContentSrc.includes('extended'),
   'H1 单一入口组件内封 parseContentTokens + extended（调用方无开关）')
ok(!isScatterViolation(kbUploadSrc) && kbUploadSrc.includes('KbContentText'),
   'H2 KbUpload 正文已改用单一入口，不再自带 token 切分 / # 正则')
ok(kbApiSrc.includes('stripHeadingMarks') && kbApiSrc.includes('titleDisplay'),
   'H4 API 边界一次性归一化 display 字段')
// 自证：同一把尺必须能咬住违规样本（否则门禁瞎）。注入后立即撤销，不留在真面里。
const badSrc = 'function chunkTokens(c){ return parseContentTokens(c) } // #{1,6}\\s+'
const biteOk = isScatterViolation(badSrc)
ok(biteOk, 'H2s 自证：注入违规样本被同一判据命中（用后即弃，不进真面）')

console.log(`\n合计：${failures === 0 ? '全部通过' : failures + ' 条失败'}`)
process.exit(failures === 0 ? 0 : 1)
