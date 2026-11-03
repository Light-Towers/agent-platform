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
 *   · 密钥只活在本模块的 ref 里，**不写 localStorage**（工单件 §2.3）。全仓 `web/src/**`
 *     唯一的存储写者是 `theme.ts` 的 `ap.ui.theme`（主题偏好不属凭据，视觉件 §1.6），
 *     这条由 `check-events.mjs` 的凭据断言机器校，不靠自觉。
 *   · banner **跨轮累积**：一次 `streamQuery` 只可能命中四条错误分支里的一条（HTTP 早退
 *     或流内，见 sse.ts），所以单轮屏上最多只出现一支 ⇒ A8「四条分支文案互异」要能在
 *     同一屏上对比，只能靠累积。上限 8，超出丢最旧并**如实报折叠条数**（不静默丢）。
 *   · `streamQuery` 唯一仍会抛的那条（密钥含非 ASCII）在这里接住 —— A2 的"不白屏"要求
 *     页面最后一道有 catch，而不是让它冒到渲染之外。
 * ==========================================================================*/
import { computed, ref } from 'vue'

import { initialState, streamQuery, type StreamQueryOptions, type StreamSnapshot, type Terminal, type TimelineEntry } from '../api/sse.ts'

/** 终态三值的类型从本件再转一次：组件读的是本件的 `terminal`，不该为了拿一个类型
 *  而去 import 传输层（那条边会把 PR-2 的组件绑回 sse.ts 的形状上）。 */
export type { Terminal }

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
export { question, apiKey }

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
    onUpdate: onTick,
    ...(fetchImpl !== undefined ? { fetchImpl } : {}),
  }
  try {
    const final = await streamQuery(opts)
    snap.value = final
    promote(final)
  } catch (err) {
    // 只有「密钥含非 ASCII」会走到这里（sse.ts 明写它是唯一仍抛的一条）。
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
