/* ============================================================================
 * sseReducer.ts — SSE 纯归约内核（R3 / docs/plans/web-refactor）
 *
 * 从 api/sse.ts 原子迁入：事件分支表、逐帧归约、快照类型与富回答解析。
 * 三条纪律不变：纯函数（不碰网络/DOM/全局状态）、逐帧快照不回改、未知事件只报名不 dump。
 * 另收 banner 上限逻辑（8 条、去重、溢出计数）为纯函数，供 Pinia store 与 Node 门禁共用。
 * 本件被 web/scripts/verify-sse.mjs 在 Node 里直接喂帧断言，故不得引入任何浏览器/Store 依赖。
 * ==========================================================================*/
import type { StreamEventType } from '../api/events.ts'
import { describeStreamError } from '../api/errors.ts'

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

/* ---- 富回答（plan-image-citation-e2e-2026-11-23）：前端只认这一套形状 ----
 * 逐字段对应后端 shared_schemas.RichAnswer（Source/Citation/ImageRef）。
 * 图片渲染前必须过 isSafeImageUrl —— 服务端已过域名白名单，这里是防伪协议的第二道闸。
 */
export interface RichSource {
  readonly type: 'knowledge' | 'table' | 'api' | 'web'
  readonly name: string
  readonly source_doc?: string | null
  readonly as_of?: string | null
}
export interface RichCitation {
  readonly source: RichSource
  readonly chunk_id?: string | null
  readonly heading?: string | null
  readonly snippet?: string | null
}
export interface RichImage {
  readonly url: string
  readonly source_doc?: string | null
  readonly caption?: string | null
}
export interface RichAnswer {
  readonly answer: string
  readonly sources: readonly RichSource[]
  readonly citations: readonly RichCitation[]
  readonly images: readonly RichImage[]
}

/** 前端二次校验：只接受绝对 http(s) URL（相对协议 / data: / javascript: 一律拒）。 */
export function isSafeImageUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value === '') return false
  try {
    const u = new URL(value)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * 把集群内 MinIO 图片 URL 改写为同源代理路径（plan-image-qa-fullstack D1=B）。
 * 浏览器无法直连 `minio:9000`（私有桶 + 集群内 DNS），agent_server 的 /img/{bucket}/{path}
 * 端点用凭证取字节流式回。只对已知内部 host 改写；其他 URL 原样返回（白名单由 isSafeImageUrl 把关）。
 * - `http://minio:9000/kb-import-bucket/images/a.png` → `/img/kb-import-bucket/images/a.png`
 * - 已是 `/img/...` 的不再重复改写。
 */
const INTERNAL_IMAGE_HOSTS = new Set(['minio'])

export function toProxyImageUrl(url: string): string {
  if (url.startsWith('/img/')) return url
  try {
    const u = new URL(url)
    if (!INTERNAL_IMAGE_HOSTS.has(u.hostname)) return url
    return `/img${u.pathname}`
  } catch {
    return url
  }
}

function _isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 防御性解析后端 rich 载荷：字段缺失/类型不对不炸界面，图片过二次校验。 */
export function parseRichAnswer(payload: unknown): RichAnswer | null {
  if (!_isRecord(payload)) return null
  const sources: RichSource[] = []
  if (Array.isArray(payload.sources)) {
    for (const item of payload.sources) {
      if (!_isRecord(item) || typeof item.name !== 'string') continue
      const type = item.type
      sources.push({
        type: type === 'knowledge' || type === 'table' || type === 'web' ? type : 'api',
        name: item.name,
        source_doc: typeof item.source_doc === 'string' ? item.source_doc : null,
        as_of: typeof item.as_of === 'string' ? item.as_of : null,
      })
    }
  }
  const citations: RichCitation[] = []
  if (Array.isArray(payload.citations)) {
    for (const item of payload.citations) {
      if (!_isRecord(item) || !_isRecord(item.source)) continue
      const src = item.source
      const name = src.name
      if (typeof name !== 'string') continue
      const type = src.type
      citations.push({
        source: {
          type: type === 'knowledge' || type === 'table' || type === 'web' ? type : 'api',
          name,
          source_doc: typeof src.source_doc === 'string' ? src.source_doc : null,
        },
        chunk_id: typeof item.chunk_id === 'string' ? item.chunk_id : null,
        heading: typeof item.heading === 'string' ? item.heading : null,
        snippet: typeof item.snippet === 'string' ? item.snippet : null,
      })
    }
  }
  const images: RichImage[] = []
  if (Array.isArray(payload.images)) {
    for (const item of payload.images) {
      if (!_isRecord(item) || !isSafeImageUrl(item.url)) continue
      images.push({
        url: item.url,
        source_doc: typeof item.source_doc === 'string' ? item.source_doc : null,
        caption: typeof item.caption === 'string' ? item.caption : null,
      })
    }
  }
  return {
    answer: typeof payload.answer === 'string' ? payload.answer : '',
    sources, citations, images,
  }
}

/** 每次事件到达都会回调这个快照；页面不需要自己维护流状态。 */
export interface StreamSnapshot {
  readonly timeline: readonly TimelineEntry[]
  readonly evidence: readonly EvidenceEntry[]
  /** 富回答（图片/引用/来源）；无富信息时为 null。 */
  readonly rich: RichAnswer | null
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
  rich: RichAnswer | null
  answer: string
  terminal: Terminal
  threadId: string
  requestId: string
  httpStatus: number
  sawError: boolean
  doneReceived: boolean
}

export type Payload = Record<string, unknown>
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
    timeline: [], evidence: [], rich: null, answer: '', terminal: 'open',
    threadId: '', requestId: '', httpStatus: 0, sawError: false, doneReceived: false,
  })
}

export function withPush(s: StreamSnapshot, event: string, kind: TimelineEntry['kind'], text: string): StreamSnapshot {
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
  rich: (s, p) => {
    const parsed = parseRichAnswer(p.rich)
    if (parsed !== null) s.rich = parsed
    s.timeline.push({
      event: 'rich',
      kind: 'event',
      text: `富回答：${parsed?.images.length ?? 0} 张图片、${parsed?.citations.length ?? 0} 条引用`,
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


/** banner 上限：四条分支各出现两次仍全留在屏上，再多丢最旧并计数。 */
export const MAX_BANNERS = 8

export interface BannerState {
  readonly banners: readonly string[]
  readonly folded: number
}

/** 纯归约：去重 → 追加 → 溢出丢最旧并如实计数；不修改传入状态。 */
export function pushBanner(state: BannerState, text: string): BannerState {
  if (text === '' || state.banners.includes(text)) return state
  const next = [...state.banners, text]
  if (next.length > MAX_BANNERS) {
    return { banners: next.slice(1), folded: state.folded + 1 }
  }
  return { banners: next, folded: state.folded }
}
