/* ============================================================================
 * session.ts — 对话页的会话状态（工单件 §9.3 登记的 `src/stores/session.ts`）
 *
 * ⚠ **形态：模块级 composable，不是 Pinia。** 工单件 §9.3 那行原写「Pinia：对话态与事件
 *   时间线」，本批按**最终实现效果**改判为就地 composable，理由三条，都不是"少装一个包"：
 *   ① PR-2 的可变对象只有一个：`streamQuery` 每帧返回的**不可变快照**。没有跨组件写、
 *      没有派生状态图、没有 action 日志 —— Pinia 的三项收益在这里都不兑现。
 *   ② PR-4（灯阵页）按形态订正是**独立 HTML 入口**，跨文档本来就不共享内存状态，
 *      "全局 store 让两个页面共享一份状态"这一条主要收益在这个应用形态里落不了地。
 *   ③ 可测性持平甚至更好：本件的导出可以直接被 `web/scripts/verify-sse.mjs` 在 Node 里
 *      驱动（实测 Node 能 import `vue` 的 ref/computed），而 Pinia 还要 `createPinia` +
 *      `setActivePinia` 的仪式才能拿到同一个 instance。
 *   代价与义务：这是**模块级单例**，同一份状态不能被实例化两次 —— 与 Pinia 同一条限制，
 *   所以它没有因此多丢什么；工单件 §9.3 那行已随批订正。**复审触发条件**：出现第二个
 *   需要跨页/跨组件共享的可变状态（或需要 devtools 时间旅行）时，本件换 Pinia 是正解。
 *
 * 三条纪律的落点：
 *   · 密钥只活在本模块的 ref 里，**不写 localStorage**（工单件 §2.3）。本模块自己一个存储 API
 *     都不调：登录令牌的存取全部代理给 `api/auth.ts`（那里是白名单件）。全仓 `web/src/**`
 *     的存储写者只有两件：`theme.ts`（`ap.ui.theme`，非凭据）与 `auth.ts`（`ap.auth.token`，
 *     sessionStorage）—— 这条由 `check-events.mjs` 的凭据齿双向校，不靠自觉。
 *   · banner **跨轮累积**：一次 `streamQuery` 只可能命中四条错误分支里的一条（HTTP 早退
 *     或流内，见 sse.ts），所以单轮屏上最多只出现一支 ⇒ A8「四条分支文案互异」要能在
 *     同一屏上对比，只能靠累积。上限 8，超出丢最旧并**如实报折叠条数**（不静默丢）。
 *   · `streamQuery` 仍会抛的那两条（密钥/令牌含非 ASCII）在这里接住 —— A2 的"不白屏"要求
 *     页面最后一道有 catch，而不是让它冒到渲染之外。
 *
 * PR-2b 在本模块加的是**登录态机**（四值：`anonymous / checking / authenticated / keyMode`）。
 * 三条不是显然的取舍，各自写在这里以免后人当手滑改掉：
 *   ① `ask()` 不加「已登录」前置判断。闸门在服务端（`verify_api_key` / `IdentityMiddleware`），
 *      前端这一层的可见性是 UX 而不是安全边界；给 `ask()` 加闸门的唯一效果是让行为件
 *      `verify-sse.mjs` §H 先伪造一个登录态，那不减风险只增耦合。
 *   ② 401 才掉登录态，403 不掉。后者是「已识别但无权」，把令牌清了等于因权限问题把人登出；
 *      同理 `keyMode` 下的 401 是密钥错，只报提示不跳登录页。
 *   ③ 刷新后的登录态靠 `/auth/me` 回读确认（不是解本地令牌自报身份），且 5xx/网络失败
 *      不等于「未登录」——那一支必须与 401 分开，否则登录面未启用（503）时界面会永久卡在登录页。
 * ==========================================================================*/
import { computed, ref } from 'vue'

import {
  clearStoredToken,
  fetchAuthenticatedIdentity,
  loginWith,
  logoutRequest,
  readStoredToken,
  registerAndSignIn,
  type AuthMode,
  type Credentials,
} from '../api/auth.ts'
import { initialState, streamQuery, type StreamQueryOptions, type StreamSnapshot, type Terminal, type TimelineEntry } from '../api/sse.ts'

/** 终态三值的类型从本件再转一次：组件读的是本件的 `terminal`，不该为了拿一个类型
 *  而去 import 传输层（那条边会把 PR-2 的组件绑回 sse.ts 的形状上）。同一条理由也适用于
 *  登录面两态的名：LoginView 只从会话层取类型，将来凭据面换形状时只改本件一处。 */
export type { Terminal }
export type { AuthMode, Credentials }

/** 登录面四态（见文件头③）：`keyMode` = 未登录但走了密钥通道（机器调用/后端未启用登录面）。 */
export type AuthState = 'anonymous' | 'checking' | 'authenticated' | 'keyMode'

/** banner 上限。8 条 = 四条分支各出现两次仍然全留在屏上，再多才丢最旧。 */
const MAX_BANNERS = 8

/** 空态里那个示例问题按钮填进去的句子。刻意不是问数专属文案（与 poc.html 同一条理由）。 */
export const EXAMPLE_QUESTION = '这个平台能帮我查什么？'

const question = ref('')
const apiKey = ref('')
const streaming = ref(false)
/** 本轮已发起过（区分"空态引导"与"跑完了但答案是空的"两种屏上形态）。 */
const ranOnce = ref(false)
const snap = ref<StreamSnapshot>(initialState())
const bannerList = ref<string[]>([])
const foldedCount = ref(0)

/* ---- 登录态（PR-2b）----
 * `authToken` 是内存位（页面每次读都从这一份走），`sessionStorage` 只是「刷新后还能捡回来」
 * 的副本；两者不同步时以内存为准（`dropSession` 同时清两处，所以漂不了）。 */
const authState = ref<AuthState>(readStoredToken() !== '' ? 'checking' : 'anonymous')
const authToken = ref(readStoredToken())
const authTenant = ref('')
const authUser = ref('')
const authBusy = ref(false)
/** 登录面最近一次需要给人读的句（与 `bannerList` 分开：那些是对话本轮的事实，这一格是入口面的状态）。
 *  本件只到 `authNoticeText` 为止，给组件读的是下面那个 computed（与 `bannerList`/`banners` 同一对形状）。 */
const authNoticeText = ref('')
/** 同页两态（登录 / 创建账号）。默认落在**创建账号**上：部署默认 `SIGNUP_ENABLED=true` 且
 *  首账号即管理员（方案 D-f/D-g），第一屏的人八成还没有账号；已有账号的人提交后拿到 409
 *  会被自动切回登录态（见 `submitCredentials`），这正是用户原话里那两句的顺序。 */
const authMode = ref<AuthMode>('register')

/** 本轮已经晋升到 banner 的时间线条数。时间线在一轮内只追加，所以一个下标就够。 */
let promoted = 0

/** 一条时间线行是否该同时进顶部 banner（= 两个 describe* 收敛点的返回值所在）。 */
function isDiagnostic(row: TimelineEntry): boolean {
  return row.kind === 'transport' || row.event === 'error'
}

function pushBanner(text: string): void {
  if (text === '' || bannerList.value.includes(text)) return
  bannerList.value.push(text)
  // 溢出时丢的是**最旧**那条，并把它计数出来：静默丢弃会让人以为屏上就是全部提示。
  if (bannerList.value.length > MAX_BANNERS) {
    bannerList.value.shift()
    foldedCount.value += 1
  }
}

/**
 * 把这一帧里**新增**的诊断行晋升进 banner。
 * 为什么要晋升而不是让 banner 直接读时间线：窄栏下时间线折叠成计数徽标（视觉件 §2.1），
 * 折叠时错误文案就在里面读不到了 —— 而 error 态的硬约束是「不许白屏」（§3）。
 */
function promote(s: StreamSnapshot): void {
  for (let i = promoted; i < s.timeline.length; i++) {
    const row = s.timeline[i]
    if (row !== undefined && isDiagnostic(row)) pushBanner(row.text)
  }
  promoted = s.timeline.length
}

/* ---- 只读视图（组件只读这些，不各自维护流状态） ---- */
/* 除了 `question` / `apiKey`（两个 v-model 目标必须可写），其余一律走 computed 导出：
 * 模块级 composable 没有 store 实例那层封装，直接把 `ref` 递出去 = 外面能写它。
 * `busy` 只能由 `ask()` 的开/关改，`banners` 只能由 `promote()`/`clearBanners()` 改 ——
 * 这条边界靠类型挡住，不靠注释约定。 */
export const timeline = computed<readonly TimelineEntry[]>(() => snap.value.timeline)
export const evidence = computed(() => snap.value.evidence)
export const answerText = computed(() => snap.value.answer)
export const terminal = computed(() => snap.value.terminal)
export const threadId = computed(() => snap.value.threadId)
export const requestId = computed(() => snap.value.requestId)
export const eventCount = computed(() => snap.value.timeline.length)
export const busy = computed(() => streaming.value)
export const hasRound = computed(() => ranOnce.value)
export const banners = computed<readonly string[]>(() => bannerList.value)
export const dropped = computed(() => foldedCount.value)
export { question, apiKey, authMode }

/** 提交按钮的可用性。只看两态：正在流、输入为空。 */
export const canSubmit = computed(() => !streaming.value && question.value.trim() !== '')

/**
 * 「等待 done…」那句（视觉件 §3 loading 形态）。判据只看 `done`（A7），
 * spinner 不是完成信号 —— 所以这里不能用 `terminal === 'completed'` 之外的任何猜测。
 */
export const waiting = computed(() => streaming.value)

/**
 * 请求号那一行。有就报原文，**没有就明说没有**：`describeStreamError` 的文案引导向
 * 「本页的 request_id」，而流内错误帧所在的响应头里本来就没有 `X-Trace-Id`（200 已发），
 * 这时给一个空占位比给一句指不到东西的引导诚实。
 */
export const traceNote = computed(() =>
  snap.value.requestId === ''
    ? '本次响应未带请求号（流内 error 帧不含诊断细节）⇒ 需服务端按时间窗查日志'
    : `本次请求号 ${snap.value.requestId}`)

/* ---- 登录面的只读视图 ---- */
/** 对话界面是否可见。`checking` 也算不可见：那一瞬给屏上的是「正在确认」而不是一个空对话框。 */
export const canChat = computed(() => authState.value === 'authenticated' || authState.value === 'keyMode')
export const loggedIn = computed(() => authState.value === 'authenticated')
export const authPending = computed(() => authBusy.value || authState.value === 'checking')
/** 登录面那句给人读的提示（只读：本模块里能写它的是 `dropSession`/`submitCredentials`/`resumeSession`）。 */
export const authNotice = computed(() => authNoticeText.value)
/** 手里还有没有令牌（登录页拿它决定要不要给「重试确认登录态」那一枚按钮）。 */
export const hasStoredToken = computed(() => authToken.value !== '')

/**
 * 页眉身份那一行。四种读法各自一句，因为「未确认」与「未登录」与「走的是密钥」是三件不同的事
 * —— 把它们合并成一句「未登录」就是把 503 读成了凭据问题（文件头③）。
 * 已登录那句里写的是**服务端 `/auth/me` 回读到的值**，不是本地令牌解出来的 claim。
 */
export const identityNote = computed(() => {
  switch (authState.value) {
    case 'authenticated':
      return `已登录：${authTenant.value} / ${authUser.value}（身份由服务端 /auth/me 断言回读）`
    case 'checking':
      return '正在向后端确认登录态…'
    case 'keyMode':
      return '未登录，走 API 密钥通道（机器调用兜底；本入口不签发令牌）'
    default:
      return '未登录'
  }
})

/* ---- 动作 ---- */
/**
 * 发一问。`fetchImpl` 是测试注入位（`verify-sse.mjs` §G 靠它喂假流，不发网络）。
 * 返回值不外露 Promise 语义：调用方 `void ask()` 即可，状态全在导出视图里。
 */
export async function ask(fetchImpl?: typeof fetch): Promise<void> {
  const q = question.value.trim()
  if (q === '' || streaming.value) return
  streaming.value = true
  ranOnce.value = true
  snap.value = initialState()
  promoted = 0
  // `fetchImpl` 只能**条件展开**（与 `sse.ts` 里 `signal` 那一条同因，但形状不同）：
  //   ① `exactOptionalPropertyTypes` 下 `T | undefined` 摊进可选属性会当场红（可选≠可写 undefined）；
  //   ② `StreamQueryOptions` 的字段是 `readonly`，也不能先建对象再赋值。
  // ⇒ 写在这里的不是“两个属性”，是“只在不缺时才给那个属性”这一件事的两种写法之一。
  const opts: StreamQueryOptions = {
    query: q,
    apiKey: apiKey.value,
    token: authToken.value,
    onUpdate: onTick,
    ...(fetchImpl !== undefined ? { fetchImpl } : {}),
  }
  try {
    const final = await streamQuery(opts)
    snap.value = final
    promote(final)
    // A8 的「401 跳回登录页」就落在这四行。两个条件都是必要的：
    //   · 只看 401 会把 keyMode（密钥错）也登出，而那一档本来就没有登录态可登；
    //   · 只看「令牌过期」会把 403（已识别但无权）也当过期，结果是权限问题把人踢下页面。
    if (final.httpStatus === 401 && authState.value === 'authenticated') {
      dropSession('登录令牌已被服务端拒绝（过期或换钥），请重新登录')
    }
  } catch (err) {
    // 只有两条「凭据含非 ASCII」会走到这里（sse.ts 明写它们是发出前的前置校验）。
    // 这句必须在屏上，不能只进 console：它就是这一轮的失败原因（A2 不白屏 / A4 可读）。
    const text = err instanceof Error ? err.message : String(err)
    pushBanner(text)
    snap.value = { ...snap.value, terminal: 'failed' }
  } finally {
    streaming.value = false
  }
}

function onTick(s: StreamSnapshot): void {
  snap.value = s
  promote(s)
}

/** 顶部提示区只清提示，**不动时间线**：事件行是本轮事实的记录，提示是给人的提醒。 */
export function clearBanners(): void {
  bannerList.value = []
  foldedCount.value = 0
}

/** 空态那个示例按钮：只填输入框，不直接发请求 —— 发不发由人按提交决定。 */
export function useExample(): void {
  question.value = EXAMPLE_QUESTION
}

/* ---- 登录面动作 ---- */

/**
 * 丢掉登录态的唯一出口。内存与 storage 同时清（只清一个就会出现「屏上说未登录、
 * 刷新又回到 checking」那一种自相矛盾）。为什么不兼清对话内容：那些是已经发生的读数，
 * 登出不抹除历史；而登录页不渲时间线，它们在下一轮 `ask()` 开头就被 `initialState()` 掉了。
 */
function dropSession(notice: string): void {
  clearStoredToken()
  authToken.value = ''
  authTenant.value = ''
  authUser.value = ''
  authState.value = 'anonymous'
  authNoticeText.value = notice
}

/**
 * 提交登录或建号。返回布尔只给控件用（屏上成败以 `loggedIn` / `authNotice` 为准，
 * 不靠调用方自己再推一次）。
 *
 * **一次提交把用户原话那两句走完**（「如果没有用户就创建用户，如果有账号直接登录就行」）：
 * 建号态撞上 409（= 这个登录名已经有人）⇒ 本函数**当场**用同一份凭据改走登录，
 * 不再要人点第二次。2026-11-05 由「只切态、等人工再按」改判为「切态 + 自动补一发」，
 * 拍板与四条边界记在方案 §8 第五项。
 *
 * 三条边界，都是这条链能不能自动的前提，别当保守读：
 *   ① 只有 **409** 触发自动补发。其余状态码一律原样报给人：403 是「本部署未开放注册」，
 *      自动改走登录会把一条真实的配置读数读成「登录失败」；503 是没挂签名密钥，重试也一样红。
 *   ② 自动补发只朝**登录**方向走。反方向（登录 401 ⇒ 去建号）永远不做：后端明写不分
 *      「账号不存在」与「口令错」（A3，不泄露账号存在性），客户端手里根本没有「该建号」
 *      这个信息，自动切过去等于在前端重建一个存在性 oracle，症状是口令打错就静默多出一个人。
 *   ③ 补发失败时屏上落的是**第二发**的服务端文案（那句「登录名或口令不对」比「已被占用」
 *      更可行动），不拼第三份文案 —— 纪律②（`api/auth.ts` 文件头）：上屏的话只来自服务端信封。
 */
export async function submitCredentials(input: Credentials, fetchImpl?: typeof fetch): Promise<boolean> {
  if (authBusy.value) return false
  authBusy.value = true
  authNoticeText.value = ''
  try {
    /* 意图要**在第一发之前**存下来，不能回头再读 `authMode.value`：那两枚切态按钮没被
     * `authBusy` 拦住（它们改的是 UX 态、不是凭据态），在途那一瞬人完全可以点一下。
     * 读当时值会把「建号撞 409」错判成「人自己切去了登录」，而那两条该走的发数不同。 */
    const startedAs = authMode.value
    let result = startedAs === 'register'
      ? await registerAndSignIn(input, fetchImpl)
      : await loginWith(input, fetchImpl)
    if (!result.ok) {
      if (startedAs !== 'register' || result.failure.status !== 409) {
        authNoticeText.value = result.failure.text
        return false
      }
      /* 边界①：只有 409 能走到这里。切态在先、补发在后，所以两件事各自成立：屏上的两态
       * 停在「登录」（人看到的与刚发生的请求一致），而登录那一发就紧跟着同一份凭据。 */
      authMode.value = 'login'
      result = await loginWith(input, fetchImpl)
      if (!result.ok) {
        authNoticeText.value = result.failure.text
        return false
      }
    }
    // 登录/注册成功后的身份直接取响应里那两个服务端给出的字段（不走 /auth/me：那一次往返
    // 已经在刷新路径上了，首登再花一次只会把「点了提交但屏上不动」拉长）。
    authToken.value = result.session.token
    authTenant.value = result.session.tenantId
    authUser.value = result.session.userId
    authState.value = 'authenticated'
    authNoticeText.value = ''
    return true
  } finally {
    authBusy.value = false
  }
}

/**
 * 刷新后确认可用的登录态（A8「刷新仍在登录」那一格的实物）。
 * 本件**不在模块加载时自发请求**：那样的话 `verify-sse.mjs` 在 Node 里 import 会话层就会
 * 当场发一个 fetch（能力声明变成隐形副作用）。调用人是 `App.vue` 的挂载点。
 * 无令牌时早退，不花一次往返去问「我登录了谁」。
 */
export async function resumeSession(fetchImpl?: typeof fetch): Promise<void> {
  const token = readStoredToken()
  if (token === '') {
    authState.value = 'anonymous'
    return
  }
  authToken.value = token
  authState.value = 'checking'
  const probe = await fetchAuthenticatedIdentity(fetchImpl)
  if (probe.kind === 'asserted') {
    authTenant.value = probe.tenantId
    authUser.value = probe.userId
    authState.value = 'authenticated'
    authNoticeText.value = ''
    return
  }
  if (probe.kind === 'expired') {
    dropSession(probe.text)
    return
  }
  // unreachable：令牌**留着**（它可能还是好的，只是后端这一跑没答上来），但界面不能停在
  // 「checking」上转圈，所以退回 anonymous + 一句写明“这不是未登录”的提示 + 重试按钮。
  authState.value = 'anonymous'
  authNoticeText.value = `${probe.text} ⇒ 这不等于未登录：令牌仍在 sessionStorage，可点「重试确认登录态」；`
    + '也可以先走下方「API 密钥兜底」进对话页'
}

/** 不登录、用静态密钥进对话页（D-i 那条回退面的屏上入口；后端未启用登录面时它是唯一通路）。 */
export function enterWithApiKey(): void {
  authState.value = 'keyMode'
  authNoticeText.value = ''
}

/**
 * 退出。**屏上那句必须带着「服务端不撤销」读**（方案 §6 的诚实口径）：后端那个端点是
 * 无状态的，已签发令牌在 exp 前仍可用，真正的撤销属 PR-3。登出能做到的只有「本地不再持有」。
 * 登出请求本身失败也不回滚本地态（否则一个挂掉的后端会让人无法退出当前标签页）。
 */
export async function signOut(fetchImpl?: typeof fetch): Promise<void> {
  const status = await logoutRequest(fetchImpl)
  authToken.value = ''
  dropSession('本标签页已清除登录令牌')
  const sent = status === 0 ? '登出请求未能发出' : `登出请求 HTTP ${status}`
  pushBanner(`已退出：${sent}。服务端不撤销已签发令牌（无状态 RS256，撤销属 PR-3），`
    + '所以令牌在过期前仍可能被接受；本标签页已不再持有它')
}
