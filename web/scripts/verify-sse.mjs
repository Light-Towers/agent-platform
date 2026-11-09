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
 *
 * PR-2（刀㊲）在本件加了两组：§G 消费面（快照不回改 / 依据进表三组合 / class 与图标
 * 两个纯映射），F14–F16 请求号（响应头 → 快照，且错误通道同样有号可指），以及
 * §H 会话层（`stores/session.ts` 直接在 Node 里驱动：banner 跨轮累积/去重/溢出、
 * 跳轮不混行、非 ASCII 密钥那条必接）。加 §H 的时机：本件头注那句「可测性持平甚至
 * 更好：本件的导出可以直接被 `verify-sse.mjs` 在 Node 里驱动」——能驱动却不驱动，那句
 * 就只是一句能力声明而不是读数（本轮实取：`import('vue')` 与 `import('./session.ts')`
 * 皆 OK，exports=20）。
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

/**
 * 泄漏判据：快照的**全部**上屏文本里不得出现 canary。
 * 第三个数组是 PR-2 扩的：`evidence.preview` 与 answer/时间线一样会直接渲到屏上。
 * 参数按完整快照形状要（不写 `?? []` 兜缺省）—— 少传一个数组就该炸，而不是被判成"干净"。
 */
function leaks(snap) {
  const hay = [
    snap.answer,
    ...snap.timeline.map((t) => t.text),
    ...snap.evidence.map((e) => e.preview),
  ].join('\n')
  return hay.includes(CANARY)
}

const framesOf = (snap, event) => snap.timeline.filter((t) => t.event === event)

/** 拼一帧 SSE 文本（§F 与 §G 共用，不写两份 —— 两份会漂）。 */
const frame = (name, obj) => `event: ${name}\ndata: ${JSON.stringify(obj)}\n\n`

/** 把若干帧包成一个 200 的 SSE Response（不发网络，只让 streamQuery 真解）。 */
const sseResponse = (chunks, head = {}) => {
  const enc = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream', ...head } })
}

/* ---- 载入被测模块 ---- */
let sse
let errors
let events
let icons
try {
  sse = await import('../src/api/sse.ts')
  errors = await import('../src/api/errors.ts')
  events = await import('../src/api/events.ts')
  icons = await import('../src/components/icons.ts')
} catch (e) {
  console.error(`❌ 无法加载被测 .ts（需 Node ≥22.18 的原生类型擦除，当前 ${process.version}）：${e.message}`)
  process.exit(1)
}

const { applyFrame, initialState, streamQuery } = sse
const { describeError, describeStreamError } = errors
const { ICON_PATHS, iconKeyOf, iconPathOf, rowClassOf } = icons
const NAMES = events.EVENT_NAMES

/* canary 检测器正对照（先证检测器不是空的，再拿它做判据） */
console.log('§0 断言器与 canary 的正对照')
const clean = (answer, texts, previews = []) => ({
  answer,
  timeline: texts.map((t) => ({ event: 'x', kind: 'event', text: t })),
  evidence: previews.map((p, i) => ({ node: `n${i}`, count: 1, preview: p })),
})
check('canary 检测器对含毒串必须报泄漏', leaks(clean(`前缀${CANARY}后缀`, [])))
check('canary 检测器对干净串必须不报', !leaks(clean('正常答案', ['正常一行'])))
check('canary 检测器对依据片段含毒必须报泄漏（哨程扩到 evidence 的那一枚正对照）',
  leaks(clean('', [], [CANARY])))

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

  /* F14–F16 请求号（PR-2）：错误文案里那句「请凭本页的 request_id」必须有个实物可指。 */
  const traced = await streamQuery({
    query: 'q', apiKey: '',
    fetchImpl: async () => sseResponse([frame('done', { type: 'done', thread_id: 't11', answer: ' ok' })], { 'x-trace-id': 'req-77' }),
  })
  check('F14 响应头 x-trace-id 传到快照 requestId（不自己造号）', traced.requestId === 'req-77', traced.requestId)

  const untraced = await streamQuery({
    query: 'q', apiKey: '',
    fetchImpl: async () => sseResponse([frame('done', { type: 'done', thread_id: 't12', answer: 'ok' })]),
  })
  check('F15 没这个头 ⇒ requestId 是空串而不是 undefined/占位符（页面据此不显示该行）',
    untraced.requestId === '', JSON.stringify(untraced.requestId))

  const denied401 = await streamQuery({
    query: 'q', apiKey: 'wrong',
    fetchImpl: async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401, headers: { 'x-trace-id': 'req-88' } }),
  })
  check('F16 流未开的错误通道同样拿到请求号（取头发生在 !resp.ok 分支之前）',
    denied401.requestId === 'req-88' && denied401.terminal === 'failed', denied401.requestId)
}

/* ---- §G PR-2 消费面：快照不回改 / 依据进表门 / 两个纯映射 ---- */
console.log('§G 消费面：快照契约、依据列表、class 与图标映射')
{
  // G1 快照不回改：`onUpdate` 交出去的每一帧必须停在那一帧的形状上。
  // ⚠ 判法必须是“**持住快照引用，流跑完再回读**”：只记回调当时的长度，那么
  // “后面的帧往同一个数组 push”这种回归会读不出差别（当时与事后同数）。
  // 杀掉它的变异体是把 `applyFrame` 里 `timeline/evidence` 的逐帧复制改回共享引用 ——
  // 那时帧 2 的 push 会直接长到帧 1 手里那个数组上，这里的事后回读当场报红。
  const shots = []
  await streamQuery({
    query: 'q', apiKey: '',
    onUpdate: (s) => { shots.push({ s, tl: s.timeline.length, ev: s.evidence.length, ans: s.answer }) },
    fetchImpl: async () => sseResponse([
      frame('evidence', { type: 'evidence', node: 'kb', count: 2, preview: '片段一' }),
      frame('answer', { type: 'answer', text: '正文' }),
      frame('evidence', { type: 'evidence', node: 'kb', count: 1, preview: '片段二' }),
      frame('done', { type: 'done', thread_id: 'g1', answer: '定稿' }),
    ]),
  })
  check('G1a 逐帧快照如期交出来（四个事件帧 + 收尾一次）', shots.length === 5, `次数=${shots.length}`)
  check('G1b 已发出的快照不被后续帧回改（事后回读个数与当时一致）',
    shots.every((h) => h.s.timeline.length === h.tl && h.s.evidence.length === h.ev),
    JSON.stringify(shots.map((h) => [h.tl, h.ev, h.s.timeline.length, h.s.evidence.length])))
  check('G1c 逐帧计数形状（依据列表与时间线各自长）',
    shots[0].tl === 1 && shots[0].ev === 1 &&
    shots[1].tl === 2 && shots[1].ev === 1 &&
    shots[2].tl === 3 && shots[2].ev === 2 &&
    shots[3].tl === 4 && shots[3].ev === 2 &&
    shots[4].ans === '定稿',
    JSON.stringify(shots.map((h) => [h.tl, h.ev])))

  // G2 进表门三组合（与参照物 `console.html:230` 的 `count > 0 && preview` 同形）。
  const g2a = applyFrame(initialState(), 'evidence', JSON.stringify({ type: 'evidence', node: 'kb', count: 3, preview: '有片段' }))
  check('G2a count>0 且有片段 ⇒ 进列表一条，字段逐一对应',
    g2a.evidence.length === 1 && g2a.evidence[0].node === 'kb' && g2a.evidence[0].count === 3 && g2a.evidence[0].preview === '有片段',
    JSON.stringify(g2a.evidence))

  const g2b = applyFrame(initialState(), 'evidence', JSON.stringify({ type: 'evidence', node: 'kb', count: 0, preview: '不该出现的片段' }))
  check('G2b count=0 ⇒ 不进列表（服务端那句就是没命中）', g2b.evidence.length === 0, JSON.stringify(g2b.evidence))

  const g2c = applyFrame(initialState(), 'evidence', JSON.stringify({ type: 'evidence', node: 'kb', count: 5 }))
  check('G2c count>0 但无片段 ⇒ 不进列表，时间线明说「无片段可展示」',
    g2c.evidence.length === 0 && g2c.timeline[0].text.includes('无片段可展示'), g2c.timeline[0].text)

  // G3 片段只住在列表里：同一段预览不得在时间线再出现一遍（拆字段就是为了这条）。
  const g3 = applyFrame(initialState(), 'evidence', JSON.stringify({ type: 'evidence', node: 'kb', count: 1, preview: CANARY }))
  check('G3 片段进了依据列表（它是合法上屏面）', g3.evidence[0].preview === CANARY)
  check('G3b 同一段预览不得在时间线文案里重复出现',
    !g3.timeline.some((t) => t.text.includes(CANARY)) && g3.timeline[0].text.includes('片段见依据列表'),
    g3.timeline[0].text)

  // G4–G6 两个纯映射：class 与图标不得拼出 CSS/表里不存在的名字。
  check('G4 kind=transport ⇒ ev--transport / transport 图标（客户端侧行，不伪装成后端事件）',
    rowClassOf({ event: 'transport', kind: 'transport', text: 'x' }) === 'ev--transport' &&
    iconKeyOf({ event: 'transport', kind: 'transport', text: 'x' }) === 'transport')
  check('G5 kind=unknown ⇒ ev--unknown，图标也为 unknown',
    rowClassOf({ event: 'mystery', kind: 'unknown', text: 'x' }) === 'ev--unknown' &&
    iconKeyOf({ event: 'mystery', kind: 'unknown', text: 'x' }) === 'unknown')

  // G6 原型键 / 未入表的名字：必须收敛到 ev--unknown，而不是拼出 `ev--constructor`。
  // 这类行在运行态是“后端加了类型而这层没跟上”的形状，拼不存在的 class = 静默降级。
  for (const name of ['constructor', 'toString', 'hasOwnProperty', 'brand_new_event']) {
    const row = { event: name, kind: 'event', text: 'x' }
    check(`G6 ${name} 不拼成事件类 class（收敛为 ev--unknown）`,
      rowClassOf(row) === 'ev--unknown' && iconKeyOf(row) === 'unknown' && iconPathOf(row) === ICON_PATHS.unknown)
  }

  // G7 逐类派生：每个后端事件名都要拿到自己的 class 与非空 path（条数来自 NAMES）。
  for (const name of NAMES) {
    const row = { event: name, kind: 'event', text: 'x' }
    check(`G7 ${name} ⇒ ev--${name} 且图标 path 非空`,
      rowClassOf(row) === `ev--${name}` && iconKeyOf(row) === name && ICON_PATHS[name] !== undefined && ICON_PATHS[name] !== '')
  }
}

/* ---- §H 会话层：stores/session.ts 在 Node 里真驱动（不发网络）---- */
console.log('§H 会话层：banner 累积/去重/溢出、跳轮不混行、非 ASCII 密钥接住')
/* `store` 必须在模块层：§I 还要拿它驱动登录态机（写在 §H 的花括号里 ⇒ §I 读到的是
 * ReferenceError，症状是“门禁挂掉”而不是“判据没跑”）。不写初值：下一行就要给它接上的
 * 模块或 null，一个“没被读过的 null 初值”是 lint 的 useless-assignment。 */
let store
{
  try {
    store = await import('../src/stores/session.ts')
  } catch (e) {
    check('H0 会话层可被 Node 驱动（头注那句能力声明的实物）', false, String(e && e.message))
    store = null
  }
  if (store !== null) {
    check('H0 会话层可被 Node 驱动（不靠浏览器、不靠 vitest）', typeof store.ask === 'function')
    const { ask, apiKey, banners, busy, canSubmit, clearBanners, dropped, hasRound, question, timeline, traceNote, useExample, answerText, terminal, requestId } = store
    /* ⚠ 本件是 **.mjs**：Node 的原生类型擦除只对 `.ts` 生效，在这里写 `: void` 这类
     * 注解会当场 SyntaxError（本批实踩：首版 §H 就是被这一条拦住的，不是“测试红了”）。
     * 被擦除的类型属于被测的 `.ts` 那一侧；harness 自己保持纯 JS。 */
    const reset = () => { clearBanners(); question.value = ''; apiKey.value = '' }
    const okStream = (chunks, head = {}) => async () => sseResponse(chunks, head)

    check('H1 初始态：不忙 / 不可提交 / 无提示 / 未跑过',
      busy.value === false && canSubmit.value === false && banners.value.length === 0 && hasRound.value === false)

    // H2 空输入不得产生“跑过一轮”的假象（也不得发出请求）
    let calls = 0
    await ask(async () => { calls++; return sseResponse([]) })
    check('H2 输入为空 ⇒ 一问没发、也没记成“本轮已发起”', calls === 0 && hasRound.value === false, `calls=${calls}`)

    // H3 非 ASCII 密钥：sse.ts 明写它是唯一仍会抛的一条，到这一层必须接住（A2 不白屏）
    reset()
    question.value = 'q'
    apiKey.value = '密钥含中文'
    await ask()
    check('H3 非 ASCII 密钥被接住成一句屏上可读的提示（不冒未处理 rejection）',
      banners.value.length === 1 && banners.value[0].includes('接口密钥含非 ASCII'), banners.value.join(' | '))
    check('H3b 那一轮终态是 failed、提示已接住 ⇒ busy 必须回 false（不得卡在转圈）',
      busy.value === false && terminal.value === 'failed')

    // H4 正常流：跳次拿到定稿与会话号，请求号从注入的响应头进快照
    reset()
    question.value = '平台能查什么'
    apiKey.value = 'ascii-key'
    await ask(okStream([frame('evidence', { type: 'evidence', node: 'kb', count: 2, preview: '片段' }), frame('done', { type: 'done', thread_id: 'h4', answer: '定稿文本' })], { 'x-trace-id': 'req-h4' }))
    check('H4 正常跳：定稿答案 / 会话号 / 终态三件都对',
      answerText.value === '定稿文本' && terminal.value === 'completed' && timeline.value.length === 2)
    check('H4b 请求号进到会话层并可读（traceNote 与 requestId 同一件事的两面）',
      requestId.value === 'req-h4' && traceNote.value.includes('req-h4'), traceNote.value)
    check('H4c 依据进了会话层的只读视图（不只是快照里）',
      store.evidence.value.length === 1 && store.evidence.value[0].preview === '片段')

    // H5 跳轮不混行：上一轮的时间线不得渗进本轮
    reset()
    question.value = '第二问'
    await ask(okStream([frame('route', { type: 'route', capability: 'rag' }), frame('done', { type: 'done', thread_id: 'h5', answer: '第二答' })]))
    check('H5 新一轮从空快照起（上一轮的行不渗进来）',
      timeline.value.length === 2 && timeline.value.every((r) => r.event !== 'evidence'),
      timeline.value.map((r) => r.event).join(','))

    // H6 banner 跳轮累积 + 文本互异（A8 的单屏对比靠这条）。同样给足 done：
    // 缺 done 会额外进一条 transport 行，那会把“两轮各命中一条分支”这个前置读成三条。
    reset()
    question.value = '问 A'
    await ask(async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }))
    question.value = '问 B'
    await ask(okStream([
      frame('error', { type: 'error', msg: 'Planner 侧文案' }),
      frame('done', { type: 'done', thread_id: 'h6', answer: '' }),
    ]))
    check('H6 两轮各命中一条分支 ⇒ 屏上同时留两条且互异（A8）',
      banners.value.length === 2 && banners.value[0] !== banners.value[1], banners.value.join(' | '))
    check('H6b 流内 error 帧那一轮的诊断行确实进了屏上提示',
      banners.value.some((b) => b.includes('Planner 侧文案')))

    // H7 去重：同一句再来一次不增
    question.value = '问 C'
    await ask(async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }))
    check('H7 重复文案不堆屏（includes 去重，否则 8 上限会被同一句填满）',
      banners.value.length === 2, banners.value.join(' | '))

    // H8 溢出：连跑九轮各不同的诊断 ⇒ 上限 8 + 如实报折叠条数（不静默丢）。
    // 每轮都补一个 done 帧，不是随手写的：没 done 会额外进一条**同文**的 transport 行，
    // 它虽然被去重、但会让“每轮恰好推一条”这个前置不再成立，于是 dropped 的期望值
    // 变成要靠手算序列才能得到的数——那是“把当时的手算当成判据”的形状（本仓 §12 同族）。
    reset()
    for (let i = 0; i < 9; i++) {
      question.value = `第 ${i} 问`
      await ask(okStream([
        frame('error', { type: 'error', msg: `文案序号 ${i}` }),
        frame('done', { type: 'done', thread_id: `h8-${i}`, answer: '' }),
      ]))
    }
    check('H8 超上限时丢最旧且把折叠条数读出来（不静默丢）',
      banners.value.length === 8 && dropped.value === 1
      && banners.value[0].includes('文案序号 1') && banners.value[7].includes('文案序号 8')
      && !banners.value.some((b) => b.includes('文案序号 0')),
      `len=${banners.value.length} dropped=${dropped.value} first=${banners.value[0]}`)
    check('H8b clearBanners 只清提示不动时间线（事件行是本轮事实）',
      timeline.value.length > 0 && (() => { clearBanners(); return banners.value.length === 0 })() && timeline.value.length > 0)

    // H9 示例按钮：只填输入、不发请求（“发不发由人按提交决定”）
    reset()
    const beforeCalls = calls
    useExample()
    await ask(async () => { calls++; return sseResponse([frame('done', { type: 'done', thread_id: 'h9', answer: 'x' })]) })
    check('H9 useExample 只填句子；随后的 ask 才发请求（两件事不绑在一起）',
      question.value === store.EXAMPLE_QUESTION && calls === beforeCalls + 1, `calls Δ=${calls - beforeCalls}`)
    check('H9b 无请求号时 traceNote 明说没有，不给空占位式的引导',
      requestId.value === '' && traceNote.value.includes('未带请求号'), traceNote.value)
  }
}

/* ---- §I 登录面：凭据面与会话层登录态机在 Node 里真跑（不发网络）---- */
console.log('§I 登录面：存储档位/键名、头装配二选一、409 一次提交内补发登录、/auth/me 三支分读、401 掉线与退出')
{
  /* 假存储两份都装（session + local）。只装 sessionStorage 时，“没落 localStorage”与
   * “那个名字根本不存在、写了也不报错”读数同形 —— 前者是判据，后者是空转。
   * 装在 `globalThis` 上而不是交给被测件：`auth.ts` 本来就是按全局名字读的，
   * 那一句 `typeof sessionStorage === 'undefined'` 的早退支在浏览器里走不到，本件要跑的是
   * 写入支而不是早退支。 */
  const mem = { session: new Map(), local: new Map() }
  const stubOf = (m) => ({
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
    clear: () => m.clear(),
  })
  globalThis.sessionStorage = stubOf(mem.session)
  globalThis.localStorage = stubOf(mem.local)

  let auth
  try {
    auth = await import('../src/api/auth.ts')
  } catch (e) {
    check('I0 凭据面可被 Node 驱动', false, String(e && e.message))
    auth = null
  }
  if (auth !== null && store !== null) {
    const { readStoredToken, storeToken, applyCredentialHeaders, isCredentialPreflightError } = auth
    const {
      apiKey, ask, authMode, authNotice, banners, canChat, clearBanners,
      enterWithApiKey, hasStoredToken, loggedIn, question, resumeSession, signOut,
      submitCredentials,
    } = store
    const PW = 'CANARY-口令不得落存储-3d71'
    /* 假后端：按**调用次序**依次回 steps 里的 (status, body)，并把每一发的 path/头/体记下来。
     * `path`/`headers`/`body` 是「最后一发」的读数（既有断言读的就是这三个名字，不换口径），
     * `calls`/`paths`/`bodies` 是给「一次提交该发几发」这类判据用的 —— 一键化改的正是发数，
     * 单值版表达不了「先 409 再 200」这种两步形状（它会把第二发也回成 409，两种读数同形）。
     * 为什么不直接 stub 全局 fetch：被测面四个入口都收了 `fetchImpl` 注入位，
     * 不拿全局名字做隐形前提（§G 同一条口径）。 */
    const mkSteps = (steps) => {
      const seen = { path: '', headers: null, body: null, calls: 0, paths: [], bodies: [] }
      seen.call = async (url, init) => {
        seen.calls += 1
        seen.path = String(url)
        seen.paths.push(String(url))
        seen.headers = init?.headers instanceof Headers ? init.headers : new Headers(init?.headers ?? {})
        try { seen.body = JSON.parse(String(init?.body ?? 'null')) } catch { seen.body = null }
        seen.bodies.push(seen.body)
        const step = steps[Math.min(seen.calls - 1, steps.length - 1)]
        return new Response(JSON.stringify(step.body), {
          status: step.status,
          headers: { 'content-type': 'application/json' },
        })
      }
      return seen
    }
    const mkBackend = (status, body) => mkSteps([{ status, body }])
    const authOk = { access_token: 'tk-1', tenant_id: 't-a', user_id: 'u-1', is_admin: true }
    /* 复位必须同时清**内存与存储**两处。只清存储会留下一个屏上还写着「已登录」而手里没凭据的
     * 态（那正是 dropSession 存在的理由），后面的断言会测到一个生造不存的前置。 */
    const authReset = async () => {
      await signOut(async () => new Response('{"revoked":"false"}', { status: 200 }))
      clearBanners()
    }

    check('I0b 起始态：存储里没有令牌 ⇒ readStoredToken 给空串（不报 undefined、不抛）',
      readStoredToken() === '')

    // I1 没有用户 → 在同一屏建号，建完就是已登录（用户原话第一句，后端 201 直接回令牌）
    await authReset()
    authMode.value = 'register'
    const be1 = mkBackend(201, authOk)
    const ok1 = await submitCredentials({ login: 'alice', password: PW, displayName: '爱丽丝' }, be1.call)
    check('I1 建号成功即已登录（同一次往返，没有第二次点击）',
      ok1 === true && loggedIn.value === true && canChat.value === true)
    check('I1b 走的是绝对路径 /auth/register（写成相对会被拼成 /ui/auth/…而后端没那条路由）',
      be1.path === '/auth/register', be1.path)
    check('I1c 令牌落 sessionStorage 且键名就是那个在册键',
      mem.session.get('ap.auth.token') === 'tk-1' && readStoredToken() === 'tk-1')
    check('I1d 注册体带上 display_name（登录体不该带 ⇒ 两条请求体分形）',
      be1.body?.display_name === '爱丽丝' && be1.body?.login === 'alice')
    /* 两条纪律在“手里正有一把可用令牌”时才有牙：放到末尾跑时存储已被退出清空，
     * 那时这两句恒真（那就是把空转当判据）。 */
    check('I1e 口令 canary 不在存储的任何一个值里（它只进了请求体）',
      ![...mem.session.values(), ...mem.local.values()].some((v) => v.includes(PW)))
    check('I1f 存储里只可能出现令牌那一个键（不顺手存登录名/显示名）',
      [...mem.session.keys()].every((k) => k === 'ap.auth.token'), [...mem.session.keys()].join(','))

    /* I2 已有账号 → **一次提交**就登进去：/auth/register 撞 409 ⇒ 会话层当场用同一份凭据
     * 改走 /auth/login。用户原话第二句「有账号，直接登录就行」的实物是**发数**而不是屏上兑面：
     * 只切态不补发 = 要人再点一次，那一句就没成立（2026-11-05 由「只切态」改判为「切态+补发」）。 */
    await authReset()
    authMode.value = 'register'
    const be2 = mkSteps([
      { status: 409, body: { code: 'AUTH_LOGIN_TAKEN', msg: '登录名已被占用' } },
      { status: 200, body: authOk },
    ])
    const ok2 = await submitCredentials({ login: 'alice', password: PW, displayName: '' }, be2.call)
    check('I2 409 ⇒ 同屏当场改走登录并登录成功（一次提交、两发请求，没有第二次点击）',
      ok2 === true && loggedIn.value === true && be2.calls === 2, `calls=${be2.calls}`)
    check('I2b 两步的路径依次是 /auth/register → /auth/login（不往反方向递，多一步就是造号）',
      be2.paths.join(',') === '/auth/register,/auth/login', be2.paths.join(','))
    check('I2c 第二发的体不带 display_name（那是注册端点的键，登录体多一个就是两条请求同形）',
      be2.bodies[1]?.display_name === undefined)
    check('I2d 两发的体是同一份凭据（没有把人重新问一遍）',
      be2.bodies[0]?.login === 'alice' && be2.bodies[1]?.password === PW)
    check('I2e 自动改走后屏停在「登录」态（不留在建号态）', authMode.value === 'login')
    check('I2f 一次提交不得往存储留半成品：只那一把可用的令牌',
      mem.session.size === 1 && mem.session.get('ap.auth.token') === 'tk-1',
      [...mem.session.keys()].join(','))

    /* I2g 409 之后口令也不对 ⇒ 不假装登录，屏上是**第二发**那句（不拼第三份文案）。
     * 这一格是「补发后的 result 不得被丢了不查」的唯一读数。 */
    await authReset()
    authMode.value = 'register'
    const be2g = mkSteps([
      { status: 409, body: { code: 'AUTH_LOGIN_TAKEN', msg: '登录名已被占用' } },
      { status: 401, body: { code: 'AUTH_BAD_CREDENTIALS', msg: '登录名或口令不对' } },
    ])
    const ok2g = await submitCredentials({ login: 'alice', password: PW, displayName: '' }, be2g.call)
    check('I2g 409→401 ⇒ 不假装登录、不落盘、上屏的是第二发那句',
      ok2g === false && loggedIn.value === false && mem.session.size === 0
      && authNotice.value.includes('登录名或口令不对'), authNotice.value)

    /* I2h 非 409 一律不自动补发：403 是「本部署未开放注册」，而第二发故意给 200 ——
     * 条件被放宽成「任何失败都重试」时这里会登录成功并把一条真实配置读数洗成假登录。 */
    await authReset()
    authMode.value = 'register'
    const be2h = mkSteps([
      { status: 403, body: { code: 'AUTH_SIGNUP_DISABLED', msg: '本部署未开放自助注册' } },
      { status: 200, body: authOk },
    ])
    const ok2h = await submitCredentials({ login: 'alice', password: PW, displayName: '' }, be2h.call)
    check('I2h 403 ⇒ 只发一发、不自动改走登录（配置读数不得被洗成登录成功）',
      ok2h === false && be2h.calls === 1 && loggedIn.value === false, `calls=${be2h.calls}`)

    // I3 口令错（401）不自动切去建号：后端不分「账号不存在/口令错」，前端切了就等于重建存在性 oracle
    await authReset()
    authMode.value = 'login'
    const be3 = mkBackend(401, { code: 'AUTH_BAD_CREDENTIALS', msg: '登录名或口令不对' })
    const ok3 = await submitCredentials({ login: 'alice', password: PW, displayName: '' }, be3.call)
    check('I3 401 ⇒ 不切到建号态（登录体也不带 display_name）',
      ok3 === false && authMode.value === 'login' && be3.body?.display_name === undefined)
    check('I3b 登录走的是 /auth/login 且不发凭据头（入口凭据还没拿到）',
      be3.path === '/auth/login' && be3.headers.get('Authorization') === null && be3.headers.get('X-API-Key') === null)
    check('I3c 失败文案里不含口令（上屏那一句来自服务端信封，不是本地表单）',
      authNotice.value !== '' && !authNotice.value.includes(PW), authNotice.value)
    /* 方向不能反过来：登录态下失败只发一发。少这一句，「失败就先去建个号」这种写法
     * 在这里仍会是绿（假后端把两发都回 401）⇒ 症状是口令打错就静默多出一个人。 */
    check('I3d 登录态失败不反向补发建号（只发了一发）', be3.calls === 1, `calls=${be3.calls}`)

    // I4 2xx 但缺身份字段 ⇒ 不读成登录成功（那正是本仓最反对的「看起来绿」）
    await authReset()
    authMode.value = 'login'
    const be4 = mkBackend(200, { access_token: 'tk-half' })
    const ok4 = await submitCredentials({ login: 'alice', password: PW, displayName: '' }, be4.call)
    check('I4 200 但缺 tenant_id/user_id ⇒ 不当登录成功、不落盘',
      ok4 === false && loggedIn.value === false && mem.session.size === 0)
    check('I4b 那句屏上文案把“为什么不算成功”写出来（不是只说“登录失败”）',
      authNotice.value.includes('缺少可断言的身份字段'), authNotice.value)
    check('I4c 一发登录不得因为“体不对”而自己重试（补发只住 409 那一条支）',
      be4.calls === 1, `calls=${be4.calls}`)

    // I5 头装配二选一（直接调装配函数三组合）+ 前置校验可归类
    const h5 = new Headers()
    applyCredentialHeaders(h5, { apiKey: 'key-9', token: 'tk-9' })
    check('I5 两把都有 ⇒ 只发 Bearer、不发 X-API-Key（“并存”不等于“同时发”）',
      h5.get('Authorization') === 'Bearer tk-9' && h5.get('X-API-Key') === null)
    const h5b = new Headers()
    applyCredentialHeaders(h5b, { apiKey: 'key-9', token: '' })
    check('I5b 只有密钥 ⇒ 只发 X-API-Key、不发 Authorization',
      h5b.get('X-API-Key') === 'key-9' && h5b.get('Authorization') === null)
    const h5c = new Headers()
    applyCredentialHeaders(h5c, { apiKey: '', token: '' })
    check('I5c 两把都空 ⇒ 两个头都不发（observe 档/开发模式现状，不是本件新增行为）',
      h5c.get('Authorization') === null && h5c.get('X-API-Key') === null)
    let thrown5 = null
    try {
      applyCredentialHeaders(new Headers(), { apiKey: '', token: '令牌含中文' })
    } catch (e) { thrown5 = e }
    check('I5d 非 ASCII 令牌 ⇒ 发出前就拦下，且能被归成“凭据写错了”这一型（不是服务端回的错）',
      thrown5 instanceof Error && isCredentialPreflightError(thrown5) === true)
    check('I5e 非 ASCII 密钥那一型同样可归类（sse.ts 靠它决定“原样抛给页面”还是“折成时间线一条”）',
      isCredentialPreflightError(new Error('接口密钥含非 ASCII 字符')) === true
      && isCredentialPreflightError(new Error('服务端返回 HTTP 500')) === false)

    /* I6 已登录时 /query 的头装配从凭据面取（传输层不再自拼）。
     * 令牌只能由**登录**产生：直接往存储写一把而内存里没那一份，测到的是会话层的一个
     * 不存在的状态（`ask()` 读内存位，存储只是刷新后能捡回来的副本）。 */
    await authReset()
    authMode.value = 'login'
    await submitCredentials({ login: 'alice', password: PW, displayName: '' }, mkBackend(200, authOk).call)
    question.value = '平台能查什么'
    apiKey.value = 'key-q'
    let seen6 = null
    await ask(async (_u, init) => {
      seen6 = init.headers instanceof Headers ? init.headers : new Headers(init?.headers ?? {})
      return sseResponse([frame('done', { type: 'done', thread_id: 'i6', answer: 'ok' })])
    })
    check('I6 已登录时 /query 只带 Bearer（密钥不并发 ⇒ 读数不会混）',
      seen6 !== null && seen6.get('Authorization') === 'Bearer tk-1' && seen6.get('X-API-Key') === null,
      seen6 === null ? '未拿到请求头' : `auth=${seen6.get('Authorization')} key=${seen6.get('X-API-Key')}`)

    // I7 /auth/me 三支分读：asserted / expired / unreachable（第三支是本件存在的理由）
    const be7a = mkBackend(200, { tenant_id: 't-a', user_id: 'u-1' })
    const p7a = await auth.fetchAuthenticatedIdentity(be7a.call)
    check('I7a 200 + 身份字段 ⇒ asserted，且回读用的是手里那把令牌',
      p7a.kind === 'asserted' && p7a.tenantId === 't-a' && be7a.headers.get('Authorization') === 'Bearer tk-1')
    const p7b = await auth.fetchAuthenticatedIdentity(mkBackend(401, { code: 'AUTH_TOKEN_EXPIRED', msg: '令牌过期' }).call)
    check('I7b 401 ⇒ expired（这一支才是“该重新登录”）', p7b.kind === 'expired' && p7b.status === 401)
    const p7c = await auth.fetchAuthenticatedIdentity(mkBackend(503, { code: 'AUTH_NOT_CONFIGURED', msg: '登录面未启用' }).call)
    check('I7c 503 ⇒ unreachable 而不是 expired（把它们合一句就是“把 503 读成未登录”）',
      p7c.kind === 'unreachable' && p7c.status === 503)
    const p7d = await auth.fetchAuthenticatedIdentity(mkBackend(200, {}).call)
    check('I7d 200 但无身份字段 ⇒ unreachable，不读成已断言', p7d.kind === 'unreachable')

    // I8 刷新后恢复：令牌还在 + 后端 503 ⇒ 屏上必须明说“这不等于未登录”且令牌不丢
    await authReset()
    storeToken('tk-r')
    const be8 = mkBackend(503, { code: 'AUTH_NOT_CONFIGURED', msg: '登录面未启用（无库或无私钥）' })
    await resumeSession(be8.call)
    check('I8 503 不把人登出：令牌仍在 sessionStorage、hasStoredToken 仍真',
      hasStoredToken.value === true && mem.session.get('ap.auth.token') === 'tk-r')
    check('I8b 屏上那句带“这不等于未登录”（不是一句「未登录」把人回退到零）',
      authNotice.value.includes('这不等于未登录'), authNotice.value)
    check('I8c 但对话页不能就此打开（canChat 仍假）——“不能确定”不伪装成“已确定”',
      canChat.value === false && loggedIn.value === false)

    // I9 刷新后恢复：令牌过期 ⇒ 真的掉线，屏上给下一步
    await authReset()
    storeToken('tk-x')
    await resumeSession(mkBackend(401, { code: 'AUTH_TOKEN_EXPIRED', msg: '令牌已过期' }).call)
    check('I9 401 ⇒ 令牌两处都清（内存与存储只清一个会出现“刷新又回到 checking”的矛盾）',
      loggedIn.value === false && hasStoredToken.value === false && !mem.session.has('ap.auth.token'))

    // I10 对话中途 401 才掉线；keyMode 下的 401 是密钥错，不能把人踢下页面
    await authReset()
    authMode.value = 'login'
    await submitCredentials({ login: 'bob', password: PW, displayName: '' }, mkBackend(200, { ...authOk, access_token: 'tk-c', tenant_id: 't-c', user_id: 'u-c' }).call)
    question.value = '第二问'
    apiKey.value = ''
    await ask(async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }))
    check('I10 已登录时流前 401 ⇒ 掉登录态并给出可执行的下一步',
      loggedIn.value === false && authNotice.value.includes('重新登录'), authNotice.value)
    enterWithApiKey()
    clearBanners()
    question.value = '第三问'
    apiKey.value = 'key-m'
    await ask(async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }))
    check('I10b keyMode 下的 401 只报提示不掉线（那一档本来就没有登录态可登）',
      canChat.value === true && loggedIn.value === false)
    /* I10c 直接打传输层取那个读数：会话层不导出整个快照（导了组件就能写它），
     * 所以这一格只能从 `streamQuery` 的定稿快照里读 `httpStatus`。它是 I10 那条分支的
     * 前置：没有这个字段，会话层只能猜文案（文案改一个字就换一条路径）。 */
    const s10c = await streamQuery({
      query: 'q',
      apiKey: 'k-e',
      token: '',
      fetchImpl: async () => new Response(JSON.stringify({ detail: 'INVALID_API_KEY' }), { status: 401 }),
    })
    check('I10c 状态码进了快照（会话层那条 401 分支靠的是它，不是猜文案）',
      s10c.httpStatus === 401 && s10c.terminal === 'failed', `httpStatus=${s10c.httpStatus}`)

    // I11 退出：两处都清，屏上那句必须带上“服务端不撤销”的读
    await authReset()
    authMode.value = 'login'
    await submitCredentials({ login: 'carol', password: PW, displayName: '' }, mkBackend(200, { ...authOk, access_token: 'tk-d', tenant_id: 't-d', user_id: 'u-d' }).call)
    const be11 = mkBackend(200, { revoked: 'false' })
    await signOut(be11.call)
    check('I11 退出清掉内存与存储两处、回到未登录',
      loggedIn.value === false && canChat.value === false && !mem.session.has('ap.auth.token'))
    check('I11b 退出走的是 /auth/logout 且带了令牌（服务端才能认出是谁在退）',
      be11.path === '/auth/logout' && be11.headers.get('Authorization') === 'Bearer tk-d')
    check('I11c 屏上那句明说“不撤销已签发令牌”（不能把 200 读成已撤销）',
      banners.value.length === 1 && banners.value[0].includes('不撤销已签发令牌'), banners.value.join(' | '))

    // I12 累计面：本轮跑过十二个入口之后，localStorage 仍然一个键都没写过
    check('I12 全程零写 localStorage（ApiKeyBox 与 LoginView 屏上那句承诺的行为面）',
      mem.local.size === 0, [...mem.local.keys()].join(','))
    check('I12b 退出的 banner 里也不含口令（上屏文案只来自服务端信封）',
      banners.value.every((b) => !b.includes(PW)), banners.value.join(' | '))
  } else if (auth !== null) {
    check('I0c 会话层与凭据面同时可驱动（§H 已把会话层装了）', false, 'store 为空')
  }
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
