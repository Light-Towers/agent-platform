/* ============================================================================
 * icons.ts — 时间线行的「图标 path + 用哪个 class」两处映射（视觉件 §2.2 表 / §1.4）
 *
 * 为什么单独立一件而不是写进 `Timeline.vue`：这两个函数是**纯映射**，能喂进
 * `web/scripts/verify-sse.mjs` 的 §G 在 Node 里断言。住在 `.vue` 的 `<script setup>`
 * 里就出不来（SFC 的 setup 绑定不外露），只能靠浏览器实拍才测得到 —— 而「一个后端
 * 新增的事件名会被拼成不存在的 class」这条正是能在数据层判死的形状，不该等截图。
 *
 * path 数据逐字继承 `web/poc.html:116-129` 的 `ICONS`（描边四属性住在 `base.css` 的
 * `.ico`，不逐图标写，视觉件 §1.4）。本件多两枚：`unknown` 宿主页已有，`transport`
 * 是 PR-2 才有的行形状（`sse.ts` 里 `kind='transport'` 那四条文案共用一枚图标）。
 *
 * ⚠ `transport` 与 `unknown` **故意不进图例**：`EVENT_LEGEND` 的 key 集必须 ==
 *   后端派生事件全集（`check-tokens.mjs` 断言 6 双向校），加进去就是「前端声称后端
 *   产出一种后端没有的行」。它们是**客户端侧的行种类**，不是后端事件类型 —— 所以
 *   它们各自有 class、有图标，但没有族色说明行。
 *
 * `Record<IconKey, string>` 是这台的**第一道**机制：联合里新增成员而这里少一项 ⇒
 * typecheck 当场红。`check-events.mjs` 的「消费面链」断言是**第二道独立**机制（它按
 * 后端源派生，不看 TS 类型），两道不是同一条查两遍 —— 前者拦「TS 侧改了实现没改」，
 * 后者拦「后端改了两侧都没改」。
 * ==========================================================================*/
import type { StreamEventType } from '../api/events.ts'
import { EVENT_NAMES } from '../api/events.ts'
import type { TimelineEntry } from '../api/sse.ts'

/** 一行时间线能拿到的图标种类 = 后端派生事件全集 + 两种客户端侧行。 */
export type IconKey =
  | StreamEventType
  | 'unknown'
  | 'transport'

/** 键集 == `IconKey` 联合（typecheck 保），值 == poc.html 的 path 原文。 */
export const ICON_PATHS: Record<IconKey, string> = {
  route: 'M5 3l6 5-6 5z',
  evidence: 'M2 4h12M2 8h12M2 12h12',
  memory: 'M8 2l6 6-6 6-6-6z',
  status: 'M13 8a5 5 0 11-10 0 5 5 0 0110 0',
  replan: 'M13 8a5 5 0 11-1.5-3.6M13 2.5V5h-2.5',
  suspended: 'M6 3v10M10 3v10',
  coordination: 'M13 8a5 5 0 11-10 0 5 5 0 0110 0',
  admission: 'M3 8l5-5 5 5M4.5 7.5V13h7V7.5',
  cache_hit: 'M2 4h12M2 8h12M2 12h12',
  answer: 'M3 13l1-3 6-6 2 2-6 6zM10 4l2 2',
  done: 'M3 9l3 3 7-7',
  error: 'M4 4l8 8M12 4l-8 8',
  unknown: 'M4 4l8 8M12 4l-8 8',
  transport: 'M8 2l6 11H2zM8 6v3.5M8 11.5v.5',
}

/**
 * 派生全集的**运行态**副本。类型层已经保证 `StreamEventType` 的每一项都在 `ICON_PATHS`
 * 里，但运行态收到的事件名是**服务端给的字符串**，类型管不到它 —— 所以这里要一个 Set，
 * 而且要 `has` 而不是 `in`/直取：一个叫 `constructor` 的事件名会命中原型上的函数
 * （`sse.ts` 的 `handlerFor` 同一道坑，那条已有一枚 D4 断言）。
 */
const KNOWN_EVENTS: ReadonlySet<string> = new Set<string>(EVENT_NAMES)

function isEventName(name: string): name is StreamEventType {
  return KNOWN_EVENTS.has(name)
}

/**
 * 行种类 → `events.css` 里的 accent class。
 * 三种失败形状都收敛到 `ev--unknown`（`kind='event'` 但名字不在派生全集里 = 后端加了类
 * 型而这一层没跟上，此时**不能**拼出 `ev--<新名>`：那是一个 CSS 里不存在的 class，
 * 症状是「这一行没有 accent 色」，而不是「门禁报红」—— 静默降级比报错难查）。
 */
export function rowClassOf(row: TimelineEntry): string {
  if (row.kind === 'transport') return 'ev--transport'
  if (row.kind === 'unknown') return 'ev--unknown'
  return isEventName(row.event) ? `ev--${row.event}` : 'ev--unknown'
}

/** 行种类 → 图标键。与 `rowClassOf` 同一套判据，两者不许各写一份条件（会漂）。 */
export function iconKeyOf(row: TimelineEntry): IconKey {
  if (row.kind === 'transport') return 'transport'
  if (row.kind === 'unknown') return 'unknown'
  return isEventName(row.event) ? row.event : 'unknown'
}

/** 取 path 原文。模板里直接 `ICON_PATHS[iconKeyOf(row)]` 也行，但那样每行两次调用。 */
export function iconPathOf(row: TimelineEntry): string {
  return ICON_PATHS[iconKeyOf(row)]
}
