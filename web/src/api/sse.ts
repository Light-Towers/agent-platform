/* ============================================================================
 * sse.ts — /query 的 SSE 客户端（工单件 §7 PR-1：fetch + eventsource-parser 解帧）
 *
 * 三条已定死的纪律都在这个文件里落地，落地方式各自可核：
 *   ① §2.1 传输：必须走 `fetch`（要携带 `Authorization` 头，`EventSource` 不支持自定义头）；
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
 *   · `StreamQueryOptions.token` —— 唯一入口凭据（静态 X-API-Key 通道已退役），
 *     装配规则**不在本件**（在 `auth.ts` 的 `applyCredentialHeaders`，理由见那里的注释）；
 *   · `StreamSnapshot.httpStatus` —— 会话层需要一个能区分「401 = 令牌不可用」与其它失败的
 *     读数，才能把 A8 那条「401 跳回登录页」落到实处而不是靠猜文案。
 * ==========================================================================*/
import { createParser } from 'eventsource-parser'
import type { EventSourceMessage } from 'eventsource-parser'

import { applyCredentialHeaders, isCredentialPreflightError } from './auth.ts'
import { describeError } from './errors.ts'


import { applyFrame, initialState, withPush, type Payload, type StreamSnapshot } from '../stores/sseReducer.ts'

/** 传输与鉴权参数。唯一凭据是登录令牌（静态 X-API-Key 通道已退役）。 */
export interface StreamQueryOptions {
  readonly query: string
  readonly sessionId?: string
  readonly tenantId?: string
  /**
   * 知识范围（plan-knowledge-base-model 步骤 4）：知识库 ID 过滤，空/缺省 = 全部知识库。
   * 服务端字段 `knowledge_id`（QueryRequest），随 rag capability 检索收窄召回范围。
   */
  readonly knowledgeId?: string
  /**
   * 会话上传图片的不透明引用（plan-image-qa-fullstack）。服务端按 ref 取字节转 data URI
   * 喂 VL 模型。空/缺省 = 纯文本请求。
   */
  readonly images?: readonly string[]
  /**
   * 登录令牌（PR-2b，方案 D-a/D-i）。非空 ⇒ 本请求带 `Authorization: Bearer`；
   * 空 ⇒ 不发入口凭据头（生产现网后端会回 401）。
   * 装配规则不在这里写，在 `auth.ts` 的 `applyCredentialHeaders`。
   */
  readonly token?: string
  readonly signal?: AbortSignal
  /** 测试注入位；生产走全局 fetch。缺省即 `globalThis.fetch`，不藏第二套实现。 */
  readonly fetchImpl?: typeof fetch
  readonly onUpdate?: (snap: StreamSnapshot) => void
}

function buildHeaders(token: string): Headers {
  const h = new Headers({ 'Content-Type': 'application/json' })
  // 装配规则住在 `auth.ts`（与 `/auth/*` 四个端点同一个实现位）：这里只交令牌。
  // 非 ASCII 前置校验也在那边（抛出的文案以「登录令牌含非 ASCII」开头，
  // `streamQuery` 靠 `isCredentialPreflightError` 把它与后端失败分开）。
  applyCredentialHeaders(h, { token })
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
    if (opts.knowledgeId !== undefined && opts.knowledgeId !== '') body.knowledge_id = opts.knowledgeId
    if (opts.images !== undefined && opts.images.length > 0) {
      body.context = { images: [...opts.images] }
    }
    const doFetch = opts.fetchImpl ?? globalThis.fetch
    // `signal` 单独条件赋值：`RequestInit.signal` 在 exactOptionalPropertyTypes 下接
    // `AbortSignal | null`，把 `AbortSignal | undefined` 直接摊进对象字面量会当场红。
    const init: RequestInit = {
      method: 'POST',
      headers: buildHeaders(opts.token ?? ''),
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
