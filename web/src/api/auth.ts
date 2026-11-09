/* ============================================================================
 * auth.ts — 凭据面客户端（方案 docs/plans/plan-web-auth-user-minimal-2026-11-05.md 的 D-a/D-k/D-j/§7 PR-2b）
 *
 * 本件管两件本来就是一件事的东西：**入口凭据的存取** 与 **入口凭据怎么变成请求头**。
 * 合成一件的理由不是省一个文件，是「同一请求最多带一把入口凭据」这条判据（见
 * `applyCredentialHeaders` 的注释）只能有一个实现位；分两处写就会各漂一份。
 * 因此 sse.ts（/query 的传输层）**从本件取装配**，而不是自己再拼一次头。
 *
 * 三条落死的纪律：
 *   ① **令牌落 sessionStorage、密钥仍只落内存**（D-k）。这两句不冲突，但必须分开读：
 *      工单件 §2.3 那条「密钥只存内存」管的是 `X-API-Key`（人粘贴进来的那把），它一个字节
 *      都没进存储；进存储的是**服务端签发的登录令牌**，档位是「关标签即失效」。
 *      为什么不是 localStorage：那会把凭据活期从一次会话拉长到整台浏览器（含重启后）。
 *      ⚠ 残余风险照方案如实写：sessionStorage 是 JS 可读的 ⇒ 一次 XSS 即失令牌，本轮没有
 *      CSP 面（方案 §9 在册）。这一句不许被读成「已加固」。
 *   ② **口令只在调用那一刻进请求体**：本件不把它存进任何变量副本、不写进 storage、
 *      不拼进任何上屏文案（失败文案一律来自 `describeError`，它读的是服务端信封）。
 *      对应验收 A7 的前端侧；`verify-sse.mjs` §I 用 canary 口令机器校这一条。
 *   ③ **按 HTTP 状态分支、按 `msg` 上屏**：后端的 `AUTH_*` 码表不抄进前端（抄一份 = 造出
 *      第二个事实源，而本仓没有任何跨语言派生校能钉住它）。`code` 只随失败对象带走给人读，
 *      前端不 `=== 'AUTH_LOGIN_TAKEN'` 这种串做分支。
 *
 * ⚠ 路径基准与 `sse.ts` 同一条坑：页面挂在 `/ui/` 下（`vite.config.ts` 的 `base`），
 *   所以这里全部写**绝对路径** `/auth/*`。写成相对会拼成 `/ui/auth/login`（后端没这条路由）。
 *
 * ⚠ 存储调用保持 `sessionStorage.getItem/setItem/removeItem` 的**字面形状**（不抽成
 *   `const s = sessionStorage` 再 `s?.getItem`）：`web/scripts/check-events.mjs` 的凭据齿判的
 *   就是这个字面形，抽走会让本件从白名单里"读不到"，把一条在册判据弄成空转。
 * ==========================================================================*/
import { describeError } from './errors.ts'

/** 令牌在浏览器侧的唯一键名。另一个在册存储键是 `theme.ts` 的 `ap.ui.theme`（非凭据）。 */
const TOKEN_KEY = 'ap.auth.token'

const LOGIN_PATH = '/auth/login'
const REGISTER_PATH = '/auth/register'
const ME_PATH = '/auth/me'
const LOGOUT_PATH = '/auth/logout'

/** 前置校验（发出之前）失败的两句文案。前缀是 `isCredentialPreflightError` 的判据，别改前四字。 */
export const API_KEY_PREFLIGHT_MSG = '接口密钥含非 ASCII 字符（HTTP 请求头不允许），请确认粘贴的是密钥本身而不是中文说明'
export const TOKEN_PREFLIGHT_MSG = '登录令牌含非 ASCII 字符（HTTP 请求头不允许），请退出登录后重新登录'

/** 登录面的两态名字（同一个屏、两个动作），会话层与 LoginView 共用这一个类型。 */
export type AuthMode = 'login' | 'register'

/** 表单三值。`displayName` 只有注册端点会用到（登录时服务端不读它）。 */
export interface Credentials {
  readonly login: string
  readonly password: string
  readonly displayName: string
}

/** 一次成功登录拿到的全部可断言信息（值来自**服务端响应**，不是客户端自报）。 */
export interface AuthSession {
  readonly token: string
  readonly tenantId: string
  readonly userId: string
  readonly isAdmin: boolean
}

/** 一次失败的三值：状态码（分支用）、服务端 code（给人读）、可上屏文案。 */
export interface AuthFailure {
  readonly status: number
  readonly code: string
  readonly text: string
}

export type AuthResult =
  | { readonly ok: true; readonly session: AuthSession }
  | { readonly ok: false; readonly failure: AuthFailure }

/* ---- 存储面（本仓 web/src 里除 theme.ts 之外唯一的存储写者，靠白名单钉，不靠自觉） ---- */

/**
 * 读回本标签页的登录令牌；没有/读不到一律给空串。
 * 为什么 try/catch 而不是先判 `null`：隐私模式与「禁用站点数据」下**访问** sessionStorage 本身
 * 就抛（不是返回 null），而首屏不许因为一个读不到的令牌崩掉（A2 不白屏同一条要求）。
 * `typeof` 那一层是给 Node 的：行为件 `verify-sse.mjs` 在 Node 里 import 本件，那里根本没有
 * 这个名字，直接访问是 ReferenceError 而不是 undefined。
 */
export function readStoredToken(): string {
  if (typeof sessionStorage === 'undefined') return ''
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

/** 落令牌。**只写 sessionStorage**（D-k）；写不进去时不假装成功（下面 clear 同理）。 */
export function storeToken(token: string): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
  } catch {
    // 存不进去 = 隐私模式/禁用存储。这一档的后果是「刷新即需重新登录」，不是「登录失败」，
    // 所以这里不惊动人：令牌仍在内存 ref 里，本标签页内一切照常用。
  }
}

export function clearStoredToken(): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // 同上：清不掉也已经在会话层把内存里的令牌丢了，屏上的登录态以内存为准。
  }
}

/* ---- 装配面 ---- */

/** HTTP 头值只接可见 ASCII。不合规时抛**调用方给定的那一句**，而不是让 fetch 抛裸参数错误。 */
function requireHeaderSafe(value: string, message: string): void {
  if (!/^[\x20-\x7E]*$/.test(value)) throw new Error(message)
}

/**
 * 异常是否是「凭据写错了」这一型（= 发出之前就拦下，不是服务端状态）。
 * `streamQuery` 用它决定「原样抛给页面」还是「折成时间线一条」：前者是调用方写错，
 * 后者是后端给的读数，混在一起就会把「你粘了中文说明」显示成「服务返回 HTTP 500」。
 */
export function isCredentialPreflightError(err: unknown): boolean {
  return err instanceof Error
    && (err.message.startsWith('接口密钥含非 ASCII') || err.message.startsWith('登录令牌含非 ASCII'))
}

/**
 * 把入口凭据装进请求头：**有令牌 ⇒ 只发 Bearer；无令牌有密钥 ⇒ 只发 X-API-Key**。
 * 为什么不同时发两把（这是 D-i「两条通道并存」最容易读错的一处）：后端 `verify_api_key` 的
 * 分支是「已断言到人 ⇒ 直接放行」，两把都发时**密钥错也不会红** ⇒ 出问题时读数分不清是哪把
 * 起效的。并存指的是「两条路各自能走」，不是「一个请求同时试两条」。
 * 两把都为空时两个头都不发 —— 那是 observe 档/开发模式的现状，不是本件新增的行为。
 */
export function applyCredentialHeaders(h: Headers, cred: { apiKey: string; token: string }): void {
  if (cred.token !== '') {
    requireHeaderSafe(cred.token, TOKEN_PREFLIGHT_MSG)
    h.set('Authorization', `Bearer ${cred.token}`)
    return
  }
  if (cred.apiKey !== '') {
    requireHeaderSafe(cred.apiKey, API_KEY_PREFLIGHT_MSG)
    h.set('X-API-Key', cred.apiKey)
  }
}

/* ---- 传输面 ---- */

/** 一次往返的读法结果：状态码 + 是否 2xx + 解析出的 JSON 对象（非对象/读不出 ⇒ null）+ 可上屏文案。 */
interface Envelope {
  readonly status: number
  readonly ok: boolean
  readonly json: Record<string, unknown> | null
  readonly text: string
  readonly code: string
}

/**
 * 把响应读成信封。三个不显然的写法，各有一个理由：
 *  ① 体只读**一次**（`resp.text()`），成功侧从这份原文解析、失败侧把它重放给 `describeError`。
 *     直接 `resp.json()` 之后再调 `describeError(resp)` 会读到空体，把一条真实的 401 文案
 *     读成「响应体不是可解析的错误信封」—— 那是把真信号弄丢，比不报更坏。
 *  ② 失败文案仍走 `describeError`（工单件 §3 那条「唯一收敛点」），本件不自己拼第二份文案。
 *  ③ 重放时 `headers` 一起带上：`describeError` 里有按状态码分派的分支，状态码必须留住。
 */
async function readEnvelope(resp: Response): Promise<Envelope> {
  let raw: string
  try {
    raw = await resp.text()
  } catch (err) {
    return { status: resp.status, ok: resp.ok, json: null, text: `响应体读取失败：${String(err)}`, code: '' }
  }

  let json: Record<string, unknown> | null
  try {
    const parsed: unknown = JSON.parse(raw)
    json = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    // 不是 JSON（网关页、纯文本 500 等）：留给 describeError 那句兜底文案，这里不猜。
    json = null
  }
  const code = json !== null && typeof json.code === 'string' ? json.code : ''
  if (resp.ok) return { status: resp.status, ok: true, json, text: '', code }

  let replay: Response
  try {
    replay = new Response(raw === '' ? null : raw, { status: resp.status, headers: resp.headers })
  } catch {
    // 204/205/304 这类「不允许带体」的状态码：换成空体重放，让 describeError 走它自己的兜底支。
    replay = new Response(null, { status: resp.status })
  }
  return { status: resp.status, ok: false, json, text: await describeError(replay), code }
}

async function postEnvelope(path: string, body: Record<string, string>, fetchImpl?: typeof fetch): Promise<Envelope> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const h = new Headers({ 'Content-Type': 'application/json' })
  let resp: Response
  try {
    resp = await doFetch(path, { method: 'POST', headers: h, body: JSON.stringify(body), cache: 'no-store' })
  } catch (err) {
    // 与 sse.ts 同一条口径：「请求根本没发出去」要给可读原因，不给 `TypeError: Failed to fetch`。
    return { status: 0, ok: false, json: null, text: `请求未能发出（服务端不可达或地址错误）：${String(err)}`, code: '' }
  }
  return await readEnvelope(resp)
}

/**
 * 从成功响应里取会话。三值缺一律判**失败**：200 而形状不对时给一个「登录成功」的读数，
 * 就是让屏上出现「已登录」而手里没有身份 —— 那正是本仓最反对的「看起来绿」的形状。
 * `is_admin` 缺失按 false（不是 fail-open 的 true）。
 */
function sessionFrom(json: Record<string, unknown> | null): AuthSession | null {
  if (json === null) return null
  const token = typeof json.access_token === 'string' ? json.access_token : ''
  const tenantId = typeof json.tenant_id === 'string' ? json.tenant_id : ''
  const userId = typeof json.user_id === 'string' ? json.user_id : ''
  const isAdmin = json.is_admin === true
  if (token === '' || tenantId === '' || userId === '') return null
  return { token, tenantId, userId, isAdmin }
}

/** 登录/注册共用的那一趟往返。注册成功 = 已登录（后端 201 直接回令牌，不需要第二次点击）。 */
async function exchangeCredentials(path: string, input: Credentials, fetchImpl?: typeof fetch): Promise<AuthResult> {
  const body: Record<string, string> = { login: input.login, password: input.password }
  // 只有注册端点读 display_name；登录时多发一个键不改变服务端行为，但会让两条请求体不同形。
  if (path === REGISTER_PATH && input.displayName !== '') body.display_name = input.displayName

  const env = await postEnvelope(path, body, fetchImpl)
  if (!env.ok) {
    return { ok: false, failure: { status: env.status, code: env.code, text: env.text } }
  }
  const session = sessionFrom(env.json)
  if (session === null) {
    return {
      ok: false,
      failure: {
        status: env.status,
        code: env.code,
        text: `服务端返回 HTTP ${env.status} 但登录响应缺少可断言的身份字段（access_token/tenant_id/user_id）⇒ 不读成登录成功`,
      },
    }
  }
  storeToken(session.token)
  return { ok: true, session }
}

/** 口令换令牌（有账号的那一路）。 */
export async function loginWith(input: Credentials, fetchImpl?: typeof fetch): Promise<AuthResult> {
  return await exchangeCredentials(LOGIN_PATH, input, fetchImpl)
}

/** 建号并直接登录（没账号的那一路）；名字里带上「即登录」是为了让它无法被读成「只建号」。 */
export async function registerAndSignIn(input: Credentials, fetchImpl?: typeof fetch): Promise<AuthResult> {
  return await exchangeCredentials(REGISTER_PATH, input, fetchImpl)
}

/**
 * 刷新后确认登录态的三值结果。**第三支是本件存在的理由**：
 * `expired` 与 `unreachable` 必须分开 —— 后者把 503（后端未启用登录面：无库/无私钥）或网络故障
 * 读成「你没登录」，症状是「明明有令牌却被踢回登录页，而重登也进不去」。方案 §5.4 明写这种
 * 配置态是 503 + 固定 code，所以前端必须有一条不跳登录的分支接住它。
 */
export type IdentityProbe =
  | { readonly kind: 'asserted'; readonly tenantId: string; readonly userId: string }
  | { readonly kind: 'expired'; readonly status: number; readonly text: string }
  | { readonly kind: 'unreachable'; readonly status: number; readonly text: string }

/**
 * 拿手里的令牌去 `/auth/me` 回读**服务端已断言**的身份（验收 A4 的前端侧实物）。
 * 这里不读 sessionStorage 里那份令牌的 claim 来"算"身份：客户端解自己的令牌 = 客户端自报，
 * 而 A4 要证的正是「断言发生在服务端」。一次 GET 换一条能核对的读数，值这个价。
 */
export async function fetchAuthenticatedIdentity(fetchImpl?: typeof fetch): Promise<IdentityProbe> {
  const token = readStoredToken()
  if (token === '') return { kind: 'expired', status: 0, text: '本标签页没有登录令牌' }

  const h = new Headers()
  applyCredentialHeaders(h, { apiKey: '', token })
  const doFetch = fetchImpl ?? globalThis.fetch
  let resp: Response
  try {
    resp = await doFetch(ME_PATH, { method: 'GET', headers: h, cache: 'no-store' })
  } catch (err) {
    if (isCredentialPreflightError(err)) throw err
    return { kind: 'unreachable', status: 0, text: `请求未能发出（服务端不可达或地址错误）：${String(err)}` }
  }

  const env = await readEnvelope(resp)
  if (env.status === 401 || env.status === 403) {
    return { kind: 'expired', status: env.status, text: env.text }
  }
  if (!env.ok) {
    // 5xx 与「200 但体不是对象」都归这一支：后端没答上来，不等于用户没登录。
    return { kind: 'unreachable', status: env.status, text: env.text }
  }
  const tenantId = env.json !== null && typeof env.json.tenant_id === 'string' ? env.json.tenant_id : ''
  const userId = env.json !== null && typeof env.json.user_id === 'string' ? env.json.user_id : ''
  if (tenantId === '' || userId === '') {
    return { kind: 'unreachable', status: env.status, text: '/auth/me 返回 2xx 但没有身份字段 ⇒ 不读成已断言' }
  }
  return { kind: 'asserted', tenantId, userId }
}

/**
 * 通知服务端登出，并清掉本地令牌。**返回状态码而不是布尔**，因为「服务端撤销了」这件事
 * 根本没发生：后端那句 `revoked: "false"` 是自陈无状态 RS256 不撤销（`auth_router.py` 的
 * `/auth/logout` 文档串），已签发令牌在 exp 前仍可用，真正的撤销属 PR-3。
 * 所以调用方（会话层）必须把这条差值写进屏上文案，不许把 200 读成「已撤销」。
 * 令牌一律清：无论这一趟成功、401 还是没发出去，本地这份都得丢。
 */
export async function logoutRequest(fetchImpl?: typeof fetch): Promise<number> {
  const token = readStoredToken()
  clearStoredToken()
  if (token === '') return 0

  const h = new Headers({ 'Content-Type': 'application/json' })
  applyCredentialHeaders(h, { apiKey: '', token })
  const doFetch = fetchImpl ?? globalThis.fetch
  try {
    const resp = await doFetch(LOGOUT_PATH, { method: 'POST', headers: h, body: '{}', cache: 'no-store' })
    // 状态码到手后不再读体：本件不需要它，而读了就得在失败分支再造一份文案（第 ② 条纪律）。
    return resp.status
  } catch (err) {
    if (isCredentialPreflightError(err)) throw err
    return 0
  }
}
