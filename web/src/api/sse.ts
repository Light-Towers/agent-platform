/* ============================================================================
 * sse.ts — /query 的 SSE 客户端（工单件 §7 PR-1：fetch + eventsource-parser 解帧）
 *
 * 三条已定死的纪律都在这个文件里落地，落地方式各自可核：
 *   ① §2.1 传输：必须走 `fetch`（要携带 `X-API-Key` 头，`EventSource` 不支持自定义头）；
 *      解帧不自写循环，交给 `eventsource-parser`（§10.3 第 2 条）。重连与鉴权头仍由本仓掌控。
 *   ② §2.2 未识别事件不吞：落到 `kind='unknown'` 那一条时间线项，**只报事件名、不 dump 载荷**。
 *   ③ §3 第 4 条 error→done 抑制：流内一旦出现过 `error` 帧，后续 `done` 的 `answer`
 *      一律**不覆盖**已渲染内容，会话终态置 `failed` 而非 `completed`。
 *      成因不是推测：`query_router.py` 的异常分支先 `yield error` 再 `yield done(answer:"")`，
 *      无条件把 `done` 读成"最终答案的权威信号"就会用空串覆盖已有渲染并当成功收尾。
 *
 * 事件名解析口径与 `console.html` 同形：`payload.type || 帧的 event 名`（后端 `_sse` 把
 * payload.type 提升为 `event:` 行，但两路不完全一致，所以两侧都读）。
 * ⚠ 文案与 `console.html` 有一处**写法差异必须知道**：它用全角空格（U+3000）分隔句子，
 *   本文件用半角 —— `no-irregular-whitespace` 对 JS 源码里的 U+3000 直接报红（本仓 JS 段进
 *   CI），而把它加进 lint 白名单等于给整个 `web/` 开一个「肉眼数不清的空格」口子。
 *   改的是分隔符不是文案语义；`verify-sse.mjs` 的断言按句子内容匹，不依赖这个字符。
 *
 * handler 表用 `satisfies Record<StreamEventType, Handler>`：联合里新增成员而这里少一项 ⇒
 * typecheck 当场红。表体保持**一行一键**（`web/scripts/check-events.mjs` 的 key 抽取按行首
 * 缩进后的第一个标识符算，多键共一行会漏读）—— 这条耦合与 `events.ts` 的图例字典同形，
 * 两份都是写进代码的约定，不是隐形假设。typecheck 与门禁是两套独立机制，不是同一条查两遍。
 *
 * ⚠ 路径基准：本文件服务的是挂在 `/ui/` 下的页面，**不能用相对 `"query"`** ——
 *   相对路径会拼成 `/ui/query`（`web/vite.config.ts` 的 `base: '/ui/'`）。`console.html` 能写
 *   相对是因为它自己就挂在根。这一条是照抄参照物时会当场踩中的形状，所以写进注释。
 * ==========================================================================*/
import { createParser } from 'eventsource-parser'
import type { EventSourceMessage } from 'eventsource-parser'

import type { StreamEventType } from './events.ts'
import { describeError, describeStreamError } from './errors.ts'

/** 会话终态三值。`open` = 尚未收到 `done` ⇒ **不得**读成完成（A7 判据）。 */
export type Terminal = 'open' | 'completed' | 'failed'

/** 时间线一项。`kind` 只三值，页面按它选色（分色渲染属 PR-2 的 Timeline 件）。 */
export interface TimelineEntry {
  readonly event: string
  readonly kind: 'event' | 'unknown' | 'transport'
  readonly text: string
}

/** 每次事件到达都会回调这个快照；页面不需要自己维护流状态。 */
export interface StreamSnapshot {
  readonly timeline: readonly TimelineEntry[]
  readonly answer: string
  readonly terminal: Terminal
  readonly threadId: string
  readonly sawError: boolean
  readonly doneReceived: boolean
}

/** `StreamSnapshot` 的可变孪生（内部用）。写成显式六行而不是映射类型：读得出来是谁。 */
interface Working {
  timeline: TimelineEntry[]
  answer: string
  terminal: Terminal
  threadId: string
  sawError: boolean
  doneReceived: boolean
}

/** 传输与鉴权参数。`apiKey` 只活在这次调用的闭包里（§2.3：不落 storage）。 */
export interface StreamQueryOptions {
  readonly query: string
  readonly sessionId?: string
  readonly tenantId?: string
  readonly apiKey: string
  readonly signal?: AbortSignal
  /** 测试注入位；生产走全局 fetch。缺省即 `globalThis.fetch`，不藏第二套实现。 */
  readonly fetchImpl?: typeof fetch
  readonly onUpdate?: (snap: StreamSnapshot) => void
}

type Payload = Record<string, unknown>
type Handler = (s: Working, p: Payload) => void

function snapshot(w: Working): StreamSnapshot {
  return { ...w, timeline: [...w.timeline] }
}

/** 独立跑一帧的起点（测试与页面首轮渲染用）。 */
export function initialState(): StreamSnapshot {
  return snapshot({ timeline: [], answer: '', terminal: 'open', threadId: '', sawError: false, doneReceived: false })
}

function withPush(s: StreamSnapshot, event: string, kind: TimelineEntry['kind'], text: string): StreamSnapshot {
  const w: Working = { ...s, timeline: [...s.timeline] }
  w.timeline.push({ event, kind, text })
  return snapshot(w)
}

/** 取字符串/数字字段并成句；缺失一律写「未给出」，不让 `undefined` 上屏（假装读到了）。 */
function orNone(p: Payload, key: string): string {
  const v = p[key]
  if (typeof v === 'string' && v !== '') return v
  if (typeof v === 'number') return String(v)
  return '（未给出）'
}

function count(p: Payload, key: string): number {
  const v = p[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

/**
 * 事件分支表。**这张表就是 §2.2 那条纪律的实现位** ——
 * 加一类事件而这里没动，`satisfies` 让 typecheck 红、check-events.mjs 让 CI 红。
 * `done` / `admission` / `coordination` 三类是 `console.html` 现在漏掉的（工单件 §0 那句
 * 「基线口径被实测改过一次」的实物），本表按 §1 的派生全集补齐。
 */
const EVENT_HANDLERS = {
  route: (s, p) => {
    s.timeline.push({ event: 'route', kind: 'event', text: `判给能力：${orNone(p, 'capability')} 理由：${orNone(p, 'reason')}` })
  },
  evidence: (s, p) => {
    const preview = typeof p.preview === 'string' ? p.preview : ''
    s.timeline.push({
      event: 'evidence',
      kind: 'event',
      text: `命中 ${count(p, 'count')} 条依据（${orNone(p, 'node')}）${preview === '' ? '（无依据）' : '\n首条片段：' + preview}`,
    })
  },
  memory: (s, p) => {
    s.timeline.push({ event: 'memory', kind: 'event', text: `召回记忆 ${Array.isArray(p.notes) ? p.notes.length : 0} 条` })
  },
  status: (s, p) => {
    // 只报用量一项：payload 里另有 snapshot / cost_used，两者都不是一行时间线该承接的东西
    // （snapshot 展开属 PR-2，金额属 §6 的成本面板射程）。不 dump 未知形状。
    s.timeline.push({ event: 'status', kind: 'event', text: `模型用量：${count(p, 'tokens_used')} tokens` })
  },
  replan: (s, p) => {
    s.timeline.push({ event: 'replan', kind: 'event', text: `推翻前判：${orNone(p, 'from_route')} → ${orNone(p, 'to_route')} ${orNone(p, 'reason')}` })
  },
  answer: (s, p) => {
    const text = typeof p.text === 'string' ? p.text : ''
    // 空 answer 帧不覆盖已有内容（graph 与 planner 两路都可能在收尾前给空串）。
    if (text !== '') s.answer = text
    s.timeline.push({ event: 'answer', kind: 'event', text: text === '' ? '（空回答）' : text })
  },
  error: (s, p) => {
    s.sawError = true
    s.terminal = 'failed'
    s.timeline.push({ event: 'error', kind: 'event', text: describeStreamError(p) })
  },
  suspended: (s, p) => {
    s.timeline.push({ event: 'suspended', kind: 'event', text: `执行挂起，等待外部回执（任务 ${orNone(p, 'task_id')}）` })
  },
  coordination: (s, p) => {
    s.timeline.push({ event: 'coordination', kind: 'event', text: `调度：${orNone(p, 'decision')}` })
  },
  admission: (s, p) => {
    const pos = count(p, 'position')
    const reason = typeof p.reason === 'string' && p.reason !== '' ? ` ${p.reason}` : ''
    s.timeline.push({ event: 'admission', kind: 'event', text: `准入判定：${orNone(p, 'status')}${pos > 0 ? `（排队位 ${pos}）` : ''}${reason}` })
  },
  cache_hit: (s, p) => {
    const text = typeof p.text === 'string' ? p.text : ''
    if (text !== '') s.answer = text
    s.timeline.push({ event: 'cache_hit', kind: 'event', text: '命中语义缓存' })
  },
  done: (s, p) => {
    s.doneReceived = true
    if (typeof p.thread_id === 'string') s.threadId = p.thread_id
    // ⚠ §3 第 4 条的抑制规则就落在这四行：出现过 error 帧 ⇒ 不看 answer、终态 failed。
    if (s.sawError) {
      s.terminal = 'failed'
      s.timeline.push({ event: 'done', kind: 'event', text: '流已终止（本次以失败收尾，done 帧的答案不覆盖已渲染内容）' })
      return
    }
    const answer = typeof p.answer === 'string' ? p.answer : ''
    // cache-hit 旁路的 done **不带 answer**（`query_router.py:207` 只发 `{type:"done", thread_id}`）：
    // 此时保留前面 `cache_hit` / `answer` 帧已落的答案，不得因"answer 缺席"清空已渲染内容。
    if (answer !== '') s.answer = answer
    s.terminal = 'completed'
    s.timeline.push({ event: 'done', kind: 'event', text: '回答已定稿' })
  },
} satisfies Record<StreamEventType, Handler>

/**
 * 按事件名取分支。**先 `Object.hasOwn`** 再取值：不用 `EVENT_HANDLERS[name]` 直取，
 * 否则一个叫 `constructor` / `toString` 的事件名会命中原型上的函数并被当成 handler。
 */
function handlerFor(name: string): Handler | undefined {
  if (!Object.hasOwn(EVENT_HANDLERS, name)) return undefined
  const candidate = (EVENT_HANDLERS as Record<string, unknown>)[name]
  return typeof candidate === 'function' ? (candidate as Handler) : undefined
}

/**
 * 单帧入、新快照出。**纯函数、不碰网络、不碰 DOM** —— 这三条是它能被
 * `web/scripts/verify-sse.mjs` 在 Node 里直接断言的前提（工单件 §10.5 的第 ① 层写法）。
 * `name` = 帧的 `event:` 行（本仓 `_sse` 会把它填成 payload.type）。
 */
export function applyFrame(state: StreamSnapshot, name: string, data: string): StreamSnapshot {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    const shown = name === '' ? '（未给出事件名）' : name
    return withPush(state, shown, 'unknown', `未处理的事件类型：${shown}（data 不是合法 JSON，内容不显示）`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    const shown = name === '' ? '（未给出事件名）' : name
    return withPush(state, shown, 'unknown', `未处理的事件类型：${shown}（data 不是对象帧）`)
  }
  const payload = parsed as Payload
  const type = typeof payload.type === 'string' && payload.type !== '' ? payload.type : name
  const handler = handlerFor(type)
  if (handler === undefined) {
    return withPush(state, type, 'unknown', `未处理的事件类型：${type}`)
  }
  const w: Working = { ...state, timeline: [...state.timeline] }
  handler(w, payload)
  return snapshot(w)
}

function buildHeaders(apiKey: string): Headers {
  const h = new Headers({ 'Content-Type': 'application/json' })
  if (apiKey !== '') {
    // HTTP 头只接 ASCII；把这条前置成一句可读提示，而不是让运行时抛裸的 fetch 参数错误
    //（`console.html` 同形，属实踩过的形状：粘贴时把中文说明一起带进来）。
    if (!/^[\x20-\x7E]*$/.test(apiKey)) {
      throw new Error('接口密钥含非 ASCII 字符（HTTP 请求头不允许），请确认粘贴的是密钥本身而不是中文说明')
    }
    h.set('X-API-Key', apiKey)
  }
  return h
}

/**
 * 发一次 /query 并把流读完，返回最终快照；过程量走 `onUpdate`。
 * **不抛业务异常**：HTTP 错误、网络错误、无体流都折成时间线里的一条 + 终态，
 * 页面因此不必为了"不白屏"（A2）再包一层 try/catch 去猜原因。
 * 唯一仍会抛的是密钥含非 ASCII 这一条前置校验 —— 那是调用方写错了，不是服务端的状态。
 */
export async function streamQuery(opts: StreamQueryOptions): Promise<StreamSnapshot> {
  let cur = initialState()
  const emit = (): void => {
    if (opts.onUpdate) opts.onUpdate(cur)
  }

  let resp: Response
  try {
    const body: Payload = { query: opts.query }
    if (opts.sessionId !== undefined) body.session_id = opts.sessionId
    if (opts.tenantId !== undefined) body.tenant_id = opts.tenantId
    const doFetch = opts.fetchImpl ?? globalThis.fetch
    // `signal` 单独条件赋值：`RequestInit.signal` 在 exactOptionalPropertyTypes 下接
    // `AbortSignal | null`，把 `AbortSignal | undefined` 直接摊进对象字面量会当场红。
    const init: RequestInit = { method: 'POST', headers: buildHeaders(opts.apiKey), body: JSON.stringify(body) }
    if (opts.signal !== undefined) init.signal = opts.signal
    resp = await doFetch('/query', init)
  } catch (err) {
    if (err instanceof Error && err.message.startsWith('接口密钥含非 ASCII')) throw err
    // 「请求根本没发出去」这一支：给可读原因，不给 `TypeError: Failed to fetch`（A4）。
    cur = withPush(cur, 'transport', 'transport', `请求未能发出（服务端不可达或地址错误）：${String(err)}`)
    cur = { ...cur, terminal: 'failed' }
    emit()
    return cur
  }

  if (!resp.ok) {
    // 流未开、状态码在 ⇒ 通道一/二走 describeError。§3 明写：鉴权失败不受抑制规则约束。
    cur = withPush(cur, 'transport', 'transport', await describeError(resp))
    cur = { ...cur, terminal: 'failed' }
    emit()
    return cur
  }

  if (resp.body === null) {
    cur = withPush(cur, 'transport', 'transport', '服务端返回 200 但没有响应体流（无法读取事件）')
    cur = { ...cur, terminal: 'failed' }
    emit()
    return cur
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const onFrame = (ev: EventSourceMessage): void => {
    cur = applyFrame(cur, ev.event ?? '', ev.data)
    emit()
  }
  const parser = createParser({
    onEvent: onFrame,
    // 解析器自己的错误（超缓冲等）不许静默：折成一条 transport 项。
    onError: (err) => {
      cur = withPush(cur, 'transport', 'transport', `SSE 帧解析失败：${err.message}`)
    },
  })

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    parser.feed(decoder.decode(value, { stream: true }))
  }
  parser.feed(decoder.decode())   // flush 末尾未换行的残余

  if (!cur.doneReceived) {
    // A7：流自然结束 ≠ 完成。没收到 `done` 就判"未完成"，界面不得解除 loading 假定成功。
    // ⚠ **不动 terminal**：这里若写 `terminal = 'open'`，会把已经因 error 帧置 `failed` 的
    //   会话改回"未完成"——那是比 A7 更坏的形状（失败被读成待完成）。无 error 且无 done
    //   时 terminal 本来就是 'open'，无须赋值；有 error 时它是 'failed'，必须留住。
    cur = withPush(cur, 'transport', 'transport', '流已结束但未收到 done 帧 ⇒ 本次不算完成（不得显示为成功）')
  }
  emit()
  return cur
}
