/* ============================================================================
 * events.ts — SSE 事件的 TS 联合 + 屏上图例字典
 * 文件头**不写事件条数**：条数由后端源导出，写了就会在后端加一类事件的那天自动变成假话。
 * 派生纪律（工单件 §2.2 / 视觉件 §2.2）：
 *   · 联合成员与 poc.html 的 `EVENTS` 必须等于「后端 Literal ∪ 实现里下发的字面量」，
 *     这条相等关系由 web/scripts/check-tokens.mjs 断言 6 每次构建现读后端源校验，
 *     所以后端加一类事件而这里没动 ⇒ 门禁红，而不是界面上少一行还"看起来正常"。
 *   · `Record<StreamEventType, LegendRow>` 让 TS 自己再兜一层：联合里新增成员而字典少一项，
 *     typecheck 直接不通过（与门禁互为两套独立机制，不是同一条查两遍）。
 * fam / sw 两列与 poc.html 逐字同值也是校验项（两份图例副本只能有一个真相）。
 * ==========================================================================*/

/** 与后端 `StreamEventType` Literal ∪ router 直发字面量 一一对应（派生集，不写死条数）。 */
export type StreamEventType =
  | 'admission'
  | 'answer'
  | 'cache_hit'
  | 'coordination'
  | 'done'
  | 'error'
  | 'evidence'
  | 'memory'
  | 'replan'
  | 'route'
  | 'status'
  | 'suspended'

/** events.css 里 `.sw--<name>` 的色卡档名（族色只走图形通道，视觉件 §2.2）。 */
export type SwatchName =
  | 'decision'
  | 'progress'
  | 'source'
  | 'memory'
  | 'answer'
  | 'watch'
  | 'failure'
  | 'gate'
  | 'terminal'

export interface LegendRow {
  readonly fam: string
  readonly sw: SwatchName
}

/**
 * 屏上图例字典。**一行一键**是门禁的读取形状（`check-tokens.mjs` 的 key 抽取按行首缩进
 * 后的第一个标识符算），多键共一行会漏读 —— 这是一条写进代码的耦合，不是隐形假设。
 */
export const EVENT_LEGEND: Record<StreamEventType, LegendRow> = {
  route:        { fam: '决策 · 判给哪个能力', sw: 'decision' },
  evidence:     { fam: '来源 · 命中依据', sw: 'source' },
  memory:       { fam: '记忆读写', sw: 'memory' },
  status:       { fam: '进度', sw: 'progress' },
  replan:       { fam: '需关注 · 推翻前判', sw: 'watch' },
  error:        { fam: '失败', sw: 'failure' },
  suspended:    { fam: '需关注 · 挂起等待', sw: 'watch' },
  coordination: { fam: '进度 · 调度排队', sw: 'progress' },
  admission:    { fam: '平台闸门 · 准入判定', sw: 'gate' },
  cache_hit:    { fam: '来源 · 缓存命中', sw: 'source' },
  answer:       { fam: '输出流（正文流式）', sw: 'answer' },
  done:         { fam: '终止定稿', sw: 'terminal' },
}

/** 图例渲染顺序 = 后端 Literal 里的声明顺序无关，此处按事件名字母序稳定输出。 */
export const EVENT_NAMES: StreamEventType[] = Object.keys(EVENT_LEGEND).sort() as StreamEventType[]
