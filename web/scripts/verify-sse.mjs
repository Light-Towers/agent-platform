#!/usr/bin/env node
/* ============================================================================
 * verify-sse.mjs — SSE 客户端与三条错误通道的**行为**断言（工单件 §7 PR-1 判据面）
 *
 * 为什么这里必须真 import 被测模块，而不是像 check-events.mjs 那样读源码文本：
 * 工单件 §10.5 把 yak-ops 的做法定成两层 —— 第 ② 层（readFileSync + 字符串断言）
 * 「只适合锁结构不变量，不得用来锁行为」。本件锁的全是行为：
 *   A7「未收到 done 不得假定完成」/ §3 第 4 条「error 后紧跟的 done 不覆盖已渲染内容」/
 *   §2.2「未识别事件只报名、不 dump 载荷」/ A8「422 不得把 input 回显上屏」。
 * 这四条在源码文本上都「长得像对的」，只有喂帧才测得出来。⇒ 本件与 check-events.mjs
 * 不是同一条查两遍：那件管「分支齐不齐」，这件管「分支跑得对不对」。
 *
 * ⚠ 依赖 Node ≥22.18 的原生 TS 类型擦除（工单件 §10.5 那条「全程没有 vitest/jest」的形状）。
 *   加载失败**必须 rc=1 并说明原因** —— 把「跑不动」吞成「跳过」就是把本件变成空转门禁。
 *
 * 事件全集从这里**派生**（读 events.ts 的 EVENT_NAMES，它由 EVENT_LEGEND 的 key 导出，
 * 而图例 key 集 == 后端派生全集已由 check-tokens.mjs 断言 6 校验）：本文件不出现 12 这个数。
 *
 * 载荷泄漏用 canary 判：每个喂进去的帧都带一个 `secret: CANARY` 键，断言「快照里任何
 * 一条文本都不含 CANARY」。canary 检测器自己带正对照（故意含毒的串必须被判定为泄漏），
 * 否则「检测不到泄漏」与「检测器是空的」读数同形。
 * ==========================================================================*/

const CANARY = 'CANARY-载荷不得上屏-8f2c'

let checks = 0
let failures = 0
const failLines = []

function check(label, ok, detail = '') {
  checks++
  if (ok) {
    console.log(`  ✓ ${label}`)
  } else {
    failures++
    failLines.push(`${label}${detail ? ` —— ${detail}` : ''}`)
    console.log(`  ✗ ${label}${detail ? ` —— ${detail}` : ''}`)
  }
}

/** 泄漏判据：快照的**全部**上屏文本里不得出现 canary。 */
function leaks(snap) {
  const hay = [snap.answer, ...snap.timeline.map((t) => t.text)].join('\n')
  return hay.includes(CANARY)
}

const framesOf = (snap, event) => snap.timeline.filter((t) => t.event === event)

/* ---- 载入被测模块 ---- */
let sse
let errors
let events
try {
  sse = await import('../src/api/sse.ts')
  errors = await import('../src/api/errors.ts')
  events = await import('../src/api/events.ts')
} catch (e) {
  console.error(`❌ 无法加载被测 .ts（需 Node ≥22.18 的原生类型擦除，当前 ${process.version}）：${e.message}`)
  process.exit(1)
}

const { applyFrame, initialState, streamQuery } = sse
const { describeError, describeStreamError } = errors
const NAMES = events.EVENT_NAMES

/* canary 检测器正对照（先证检测器不是空的，再拿它做判据） */
console.log('§0 断言器与 canary 的正对照')
check('canary 检测器对含毒串必须报泄漏', leaks({ answer: `前缀${CANARY}后缀`, timeline: [] }))
check('canary 检测器对干净串必须不报', !leaks({ answer: '正常答案', timeline: [{ text: '正常一行' }] }))

/* ---- §A 三条错误通道（工单件 §3 末句「两组单测」的第一组：HTTP 侧）---- */
console.log('§A describeError：三条 HTTP 通道 + 两种 4xx 形状')
{
  const r401 = new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 })
  check('A1 401 → 文案把密钥问题与其它 4xx 分开（A4）',
    (await describeError(r401)).includes('密钥未填或不正确（服务端：INVALID_API_KEY）'))

  const r422 = new Response(JSON.stringify({
    detail: [{ type: 'missing', loc: ['body', 'checkpoint_id'], msg: 'Field required', input: CANARY }],
  }), { status: 422 })
  const t422 = await describeError(r422)
  check('A2 422 数组 detail → 取「字段名 + 原因」', t422.includes('checkpoint_id') && t422.includes('Field required'))
  check('A3 422 的 input（服务端 echo 的用户原文）不得上屏（A8）', !t422.includes(CANARY), t422)

  const r500 = new Response(JSON.stringify({ code: 'INTERNAL_ERROR', msg: '服务器内部错误，请稍后重试', request_id: 'req-42' }), { status: 500 })
  const t500 = await describeError(r500)
  check('A4 500 信封 → 引导向 request_id 而不是假称详情', t500.includes('req-42') && t500.includes('request_id'))

  const r503 = new Response('upstream blew up', { status: 503 })
  const t503 = await describeError(r503)
  check('A5 体不是 JSON → 带状态码的兜底句、不抛', t503.includes('503') && !t503.includes('upstream blew up'))

  const r404 = new Response(JSON.stringify({ detail: 'CHECKPOINT_NOT_FOUND' }), { status: 404 })
  check('A6 业务类字符串 detail → 原样带出并附状态码', (await describeError(r404)).includes('CHECKPOINT_NOT_FOUND'))
}

/* ---- §B 流内通道（第二组单测：describeStreamError）---- */
console.log('§B describeStreamError：两路 error 的载荷键不同')
{
  const a = describeStreamError({ type: 'error', error: '服务器内部错误，请稍后重试', secret: CANARY })
  const b = describeStreamError({ type: 'error', msg: 'Planner 侧文案', secret: CANARY })
  check('B1 router 直发那路（键 error）读得到', a.includes('服务器内部错误'))
  check('B2 planner 那路（键由 payload 决定，取 msg）读得到', b.includes('Planner 侧文案'))
  check('B3 两路文案都引导向 request_id', a.includes('request_id') && b.includes('request_id'))
  check('B4 错误帧除命中的一句文案外不渲染其余载荷', !a.includes(CANARY) && !b.includes(CANARY))
  check('B5 一个键都没命中时不谎称详情，用固定语义占位',
    describeStreamError({ secret: CANARY }).includes('服务器内部错误，请稍后重试'))
}

/* ---- §C 派生全集逐类都有分支（A2 前半的机器面）---- */
console.log(`§C 事件全集逐类跑分支（派生自 events.ts，共 ${NAMES.length} 类）`)
for (const name of NAMES) {
  const snap = applyFrame(initialState(), name, JSON.stringify({ type: name, secret: CANARY }))
  const hit = framesOf(snap, name).find((t) => t.kind === 'event')
  check(`C1 ${name} 有分支且产出 kind=event 项`, hit !== undefined, JSON.stringify(snap.timeline))
  check(`C2 ${name} 的分支不 dump 未知载荷`, !leaks(snap))
}

/* ---- §D 未识别事件不吞（§2.2 / A3）---- */
console.log('§D 未识别事件：只报名、不 dump 载荷')
{
  const snap = applyFrame(initialState(), 'mystery_event', JSON.stringify({ type: 'mystery_event', note: CANARY }))
  const row = snap.timeline[0]
  check('D1 出现「未处理的事件类型」项且 kind=unknown', row.kind === 'unknown' && row.text.includes(`未处理的事件类型：mystery_event`), row.text)
  check('D2 该项不含载荷内容（A3 的反面就是把它 dump 上屏）', !snap.timeline.some((t) => t.text.includes(CANARY)))

  const bad = applyFrame(initialState(), 'status', `{"broken:${CANARY}`)
  check('D3 data 不是合法 JSON → 报事件名而不显示原文', bad.timeline[0].kind === 'unknown' && !leaks(bad))

  const prim = applyFrame(initialState(), 'x', JSON.stringify({ type: 'constructor' }))
  const prim2 = applyFrame(initialState(), 'x', JSON.stringify({ type: 'toString' }))
  check('D4 原型键不被当成 handler（constructor/toString 必须走 unknown）',
    prim.timeline[0].kind === 'unknown' && prim2.timeline[0].kind === 'unknown')

  const nameOnly = applyFrame(initialState(), 'coordination', JSON.stringify({ decision: 'queue', secret: CANARY }))
  check('D5 只有 event: 行、data 里没有 type 时仍能命中原名分支', nameOnly.timeline[0].kind === 'event' && nameOnly.timeline[0].event === 'coordination')
}

/* ---- §E done 终止语义与抑制规则（工单件 §3 第 4 条，本批最高危）---- */
console.log('§E done 定稿 / error→done 抑制 / cache-hit 旁路形状')
{
  let s = applyFrame(initialState(), 'answer', JSON.stringify({ type: 'answer', text: '第一段答案' }))
  s = applyFrame(s, 'done', JSON.stringify({ type: 'done', thread_id: 't1', answer: '定稿全文' }))
  check('E1 done 是答案定稿与流终止的权威信号', s.answer === '定稿全文' && s.terminal === 'completed' && s.threadId === 't1')

  let e = applyFrame(initialState(), 'answer', JSON.stringify({ type: 'answer', text: 'X' }))
  e = applyFrame(e, 'error', JSON.stringify({ type: 'error', error: '服务器内部错误，请稍后重试' }))
  e = applyFrame(e, 'done', JSON.stringify({ type: 'done', thread_id: 't2', answer: '' }))
  check('E2 error 后紧跟的 done(answer:"") 不覆盖已渲染内容', e.answer === 'X', e.answer)
  check('E3 该会话终态是 failed 而不是 completed', e.terminal === 'failed')

  let e2 = applyFrame(initialState(), 'answer', JSON.stringify({ type: 'answer', text: 'X' }))
  e2 = applyFrame(e2, 'error', JSON.stringify({ type: 'error', error: '服务器内部错误' }))
  e2 = applyFrame(e2, 'done', JSON.stringify({ type: 'done', thread_id: 't3', answer: '不该被采用的收尾文本' }))
  check('E4 抑制不看 answer 是否为空串：非空也不覆盖', e2.answer === 'X' && e2.terminal === 'failed', e2.answer)

  let c = applyFrame(initialState(), 'cache_hit', JSON.stringify({ type: 'cache_hit', text: '缓存里的答案' }))
  c = applyFrame(c, 'done', JSON.stringify({ type: 'done', thread_id: 't4' }))
  check('E5 cache-hit 旁路的 done 不带 answer ⇒ 保留已落答案', c.answer === '缓存里的答案' && c.terminal === 'completed')
}

/* ---- §F streamQuery：真读流（注入 fetch，不发网络）---- */
console.log('§F streamQuery：A7 未完成判定 / 401 通道 / 网络失败可读性')
{
  const sseResponse = (chunks) => {
    const enc = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(enc.encode(c))
        controller.close()
      },
    })
    return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } })
  }
  const frame = (name, obj) => `event: ${name}\ndata: ${JSON.stringify(obj)}\n\n`

  const seen = []
  const noDone = await streamQuery({
    query: 'q', apiKey: '',
    fetchImpl: async () => sseResponse([frame('route', { type: 'route', capability: 'rag', secret: CANARY }), frame('answer', { type: 'answer', text: '半截' })]),
    onUpdate: (snap) => { seen.push(snap) },
  })
  check('F1 只开流不发 done ⇒ 终态仍是 open（A7：不得假定完成）', noDone.terminal === 'open', noDone.terminal)
  check('F2 末条明确写出「未收到 done 帧」', noDone.timeline[noDone.timeline.length - 1].text.includes('未收到 done 帧'))
  check('F3 过程量逐帧回调（页面靠它渲染，不等最终返回）', seen.length === 3, `onUpdate 次数=${seen.length}`)

  const brokeAfterError = await streamQuery({
    query: 'q', apiKey: '',
    fetchImpl: async () => sseResponse([frame('error', { type: 'error', error: '服务器内部错误，请稍后重试' })]),
  })
  check('F4 已 failed 的会话不被「无 done」改回 open（失败不得读成待完成）', brokeAfterError.terminal === 'failed', brokeAfterError.terminal)

  const full = await streamQuery({
    query: 'q', apiKey: 'abc123', sessionId: 's1',
    fetchImpl: async (url, init) => {
      check(`F5 请求路径按仓库根而不是 base 相对（当前 URL=${url}）`, url === '/query')
      check('F6 会话号与问题都进了 body', JSON.parse(init.body).query === 'q' && JSON.parse(init.body).session_id === 's1')
      check('F7 鉴权走 X-API-Key 头（EventSource 做不到这件事）', init.headers.get('X-API-Key') === 'abc123')
      return sseResponse([frame('route', { type: 'route', capability: 'rag' }), frame('done', { type: 'done', thread_id: 't9', answer: '最终' })])
    },
  })
  check('F8 正常流：收到 done 即 completed 并定稿答案', full.terminal === 'completed' && full.answer === '最终' && full.threadId === 't9')

  const denied = await streamQuery({ query: 'q', apiKey: 'wrong', fetchImpl: async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }) })
  check('F9 401（通道一，流未开）⇒ 明确文案而不是 TypeError（A4）',
    denied.terminal === 'failed' && denied.timeline[0].text.includes('密钥未填或不正确（服务端：INVALID_API_KEY）'), denied.timeline[0].text)
  check('F10 鉴权失败不受 error→done 抑制规则约束（流根本没开）', denied.doneReceived === false && denied.sawError === false)

  const boom = await streamQuery({ query: 'q', apiKey: '', fetchImpl: async () => { throw new Error('boom-net') } })
  check('F11 请求没发出去也给可读原因', boom.timeline[0].text.includes('请求未能发出') && boom.terminal === 'failed')

  let thrown = ''
  try {
    await streamQuery({ query: 'q', apiKey: '密钥含中文', fetchImpl: async () => sseResponse([]) })
  } catch (e) {
    thrown = e instanceof Error ? e.message : String(e)
  }
  check('F12 密钥含非 ASCII 在发出前就给人话提示（而不是运行时的头参数错误）', thrown.startsWith('接口密钥含非 ASCII'), thrown)

  const noBody = await streamQuery({ query: 'q', apiKey: '', fetchImpl: async () => new Response(null, { status: 200 }) })
  check('F13 200 但没有体流 ⇒ 明说读不到事件，不静默成功', noBody.terminal === 'failed' && noBody.timeline[0].text.includes('没有响应体流'))
}

/* ---- 断言器自身的反证（必须在最后跑，撤掉它自己那一条计数） ---- */
const before = failures
check('__selftest__ 断言器必须能把 false 记成失败', false, '这是故意注入的失败')
if (failures !== before + 1) {
  console.log('❌ 断言器本身不产失败 ⇒ 上面所有 ✓ 都不可信（这是门禁空转的形状）')
  process.exit(1)
}
failures = before
console.log('  ✓ 断言器自证：注入的 false 被记为失败（已撤销，不计入结论）')

console.log(`\n合计 ${checks - 1} 条断言（不含自测），失败 ${failures} 条`)
if (failures > 0) {
  console.log(`❌ SSE 行为契约失败：\n  ${failLines.join('\n  ')}`)
  process.exit(1)
}
console.log('✅ SSE 行为契约通过')
