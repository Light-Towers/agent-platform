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
 *
 * PR-2（刀㊲）给本件加了两个**消费面**字段：`evidence`（结构化依据，从时间线文本里拆出）
 * 与 `requestId`（响应头 `X-Trace-Id`）。拆与取的理由各写在字段自己的注释里，两条都有行为
 * 断言接住（§G 管快照不回改与依据进表条件，F14 管请求号从响应头传到快照）。
 *
 * PR-2b（登录面）给本件加了两条，都在下面各自的声明处注释：
 *   · `StreamQueryOptions.token` —— 入口凭据从「只有 `X-API-Key`」变成两条通道二选一，
 *     装配规则**不在本件**（在 `auth.ts` 的 `applyCredentialHeaders`，理由见那里的注释）；
 *   · `StreamSnapshot.httpStatus` —— 会话层需要一个能区分「401 = 凭据不可用」与其它失败的
 *     读数，才能把 A8 那条「401 跳回登录页」落到实处而不是靠猜文案。
 * ==========================================================================*/
import { createParser } from 'eventsource-parser'
import type { EventSourceMessage } from 'eventsource-parser'

import { applyCredentialHeaders, isCredentialPreflightError } from './auth.ts'
import type { StreamEventType } from './events.ts'
import { describeError, describeStreamError } from './errors.ts'

/** 会话终态三值。`open` = 尚未收到 `done` ⇒ **不得**读成完成（A7 判据）。 */
export type Terminal = 'open' | 'completed' | 'failed'

/** 时间线一项。`kind` 只三值，页面按它选色（`PR-2` 的 Timeline 件消费它）。 */
export interface TimelineEntry {
  readonly event: string
  readonly kind: 'event' | 'unknown' | 'transport'
  readonly text: string
}

/**
 * 一条依据的结构形态。字段集**逐个对应** `serialize_stream_event` 的 evidence 分支
 * （`{type,node,count,preview}`），不新增、不推断后端没给的字段（工单件 §12 第 1 条同源）。
 * 之所以从时间线文本里**拆出来**：PR-1 交客户端时没有消费者，片段只能塞进一句文案；
 * PR-2 交了依据列表，片段的家就在列表里 ⇒ 同一段 200 字预览在同屏出现两处是重复。
 */
export interface EvidenceEntry {
  readonly node: string
  readonly count: number
  readonly preview: string
}

/** 每次事件到达都会回调这个快照；页面不需要自己维护流状态。 */
export interface StreamSnapshot {
  readonly timeline: readonly TimelineEntry[]
  readonly evidence: readonly EvidenceEntry[]
  readonly answer: string
  readonly terminal: Terminal
  readonly threadId: string
  /** 响应头 `X-Trace-Id`（有则读，没有就是空串）。`describeStreamError` 那句
   * 「请凭本页的 request_id」在页面上必须有实物可指，否则是一句空指针式的引导。 */
  readonly requestId: string
  /**
   * 本轮 HTTP 入口的状态码；**0 = 没有 HTTP 层失败**（流开起来了，或请求根本没发出去）。
   * 这个字段只为一个消费者存在：会话层要在 401 时把登录态丢掉（A8）。为什么不把
   * `describeError` 的文案给它判：文案是给**人**看的一句话，按它做分支就等于让界面
   * 跟着服务端文案漂（改一个字就换一条路径）；状态码是 HTTP 契约，不会漂。
   */
  readonly httpStatus: number
  readonly sawError: boolean
  readonly doneReceived: boolean
}

/** `StreamSnapshot` 的可变孪生（内部用）。写成显式九行而不是映射类型：读得出来是谁。 */
interface Working {
  timeline: TimelineEntry[]
  evidence: EvidenceEntry[]
  answer: string
  terminal: Terminal
  threadId: string
  requestId: string
  httpStatus: number
  sawError: boolean
  doneReceived: boolean
}

/** 传输与鉴权参数。`apiKey` 只活在这次调用的闭包里（工单件 §2.3：不落 storage）。 */
export interface StreamQueryOptions {
  readonly query: string
  readonly sessionId?: string
  readonly tenantId?: string
  readonly apiKey: string
  /**
   * 登录令牌（PR-2b，方案 D-a/D-i）。非空 ⇒ 本请求只带 `Authorization: Bearer`；
   * 空 ⇒ 只带 `X-API-Key`（现状逐字不变，本机未启用登录面时问答仍可用）。
   * 两条通道**二选一**的规则不在这里写，在 `auth.ts` 的 `applyCredentialHeaders`。
   */
  readonly token?: string
  readonly signal?: AbortSignal
  /** 测试注入位；生产走全局 fetch。缺省即 `globalThis.fetch`，不藏第二套实现。 */
  readonly fetchImpl?: typeof fetch
  readonly onUpdate?: (snap: StreamSnapshot) => void
}

type Payload = Record<string, unknown>
type Handler = (s: Working, p: Payload) => void

/**
 * 两条数组都要逐帧复制 —— 快照的契约是「发出去之后不再变」：`onUpdate` 的消费者对
 * 每帧持有同一个 `StreamSnapshot`，若 `evidence` 沿用引用，后面帧的 `push` 会**回改**
 * 已经发出去的快照（`verify-sse.mjs` §G1 判的就是这条）。写成两行而不是映射类型同理。
 */
function snapshot(w: Working): StreamSnapshot {
  return { ...w, timeline: [...w.timeline], evidence: [...w.evidence] }
}

/** 独立跑一帧的起点（测试与页面首轮渲染用）。 */
export function initialState(): StreamSnapshot {
  return snapshot({
    timeline: [], evidence: [], answer: '', terminal: 'open',
    threadId: '', requestId: '', httpStatus: 0, sawError: false, doneReceived: false,
  })
}

function withPush(s: StreamSnapshot, event: string, kind: TimelineEntry['kind'], text: string): StreamSnapshot {
  const w: Working = { ...s, timeline: [...s.timeline], evidence: [...s.evidence] }
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
    const cnt = count(p, 'count')
    // 进依据列表的条件与参照物 `console.html:230` 同形（`count > 0 && preview`）：
    // `count: 0` 的帧在服务端就是「没命中」，塞进列表会得到一条空片段行。
    if (cnt > 0 && preview !== '') s.evidence.push({ node: orNone(p, 'node'), count: cnt, preview })
    s.timeline.push({
      event: 'evidence',
      kind: 'event',
      text: `命中 ${cnt} 条依据（${orNone(p, 'node')}）${preview === '' ? '，无片段可展示' : '，片段见依据列表'}`,
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
  const w: Working = { ...state, timeline: [...state.timeline], evidence: [...state.evidence] }
  handler(w, payload)
  return snapshot(w)
}

function buildHeaders(apiKey: string, token: string): Headers {
  const h = new Headers({ 'Content-Type': 'application/json' })
  // 装配规则住在 `auth.ts`（与 `/auth/*` 四个端点同一个实现位）：这里只交两个值。
  // 为什么不在这件里重写一份：两条通道的互斥关系是入口凭据面的知识，写两处就会各漂一份；
  // 而漂的那一型是「两把都发」——后端 `verify_api_key` 先看断言身份，密钥错了也不会红，
  // 于是读数分不清是哪把起效（看着绿，其实测的是另一条路）。
  // 非 ASCII 那两条前置校验也一并在那边（抛出的两句文案以「接口密钥/登录令牌含非 ASCII」
  // 开头，`streamQuery` 靠 `isCredentialPreflightError` 把它们与后端失败分开）。
  applyCredentialHeaders(h, { apiKey, token })
  return h
}

/**
 * 发一次 /query 并把流读完，返回最终快照；过程量走 `onUpdate`。
 * **不抛业务异常**：HTTP 错误、网络错误、无体流都折成时间线里的一条 + 终态，
 * 页面因此不必为了"不白屏"（A2）再包一层 try/catch 去猜原因。
 * 仍会抛的只有两条前置校验（密钥 / 令牌含非 ASCII）—— 那是调用方写错了，不是服务端的状态。
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
    const init: RequestInit = {
      method: 'POST',
      headers: buildHeaders(opts.apiKey, opts.token ?? ''),
      body: JSON.stringify(body),
    }
    if (opts.signal !== undefined) init.signal = opts.signal
    resp = await doFetch('/query', init)
  } catch (err) {
    if (isCredentialPreflightError(err)) throw err
    // 「请求根本没发出去」这一支：给可读原因，不给 `TypeError: Failed to fetch`（A4）。
    cur = withPush(cur, 'transport', 'transport', `请求未能发出（服务端不可达或地址错误）：${String(err)}`)
    cur = { ...cur, terminal: 'failed' }
    emit()
    return cur
  }

  // 请求号从响应头取，**不自己造**：`build_api_app` 那套管道的 request_id 只有服务端知道。
  // 这里不额外 `emit()`：赋完值后面必然还有一次 emit（要么下一帧、要么收尾那次），
  // 加一次就只是把「逐帧回调」的读数抬高（`verify-sse.mjs` F3 数的就是它）。
  cur = { ...cur, requestId: resp.headers.get('x-trace-id') ?? '' }

  if (!resp.ok) {
    // 流未开、状态码在 ⇒ 通道一/二走 describeError。§3 明写：鉴权失败不受抑制规则约束。
    // `httpStatus` 与文案同时给：文案给人看，状态码给会话层做那条 401 分支（A8）。
    cur = { ...cur, httpStatus: resp.status }
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
