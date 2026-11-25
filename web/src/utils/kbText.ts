/* ============================================================================
 * kbText.ts — 知识库文本「显示字段」单一归一化实现
 *
 * 为什么需要：KS 按 Markdown 原文切块（title 字面带 '## '），PDF→MD 产物还可能带
 * <table> / Wingdings / $$。历史上每个显示点各自剥标记，漏一个就是一个补丁
 * （2026-11-25 连补两处）。本件把"标题怎么显示"收敛到一处（P3），调用方拿到的
 * display 字段天然干净，不必记得自己处理。
 *
 * 边界（P4）：只剥行首 '#{1,6} ' 标题标记，**保留正文里的 #**（如关系元组、话题标签）。
 * 不碰 raw 字段（title/content）—— 那是检索原文，保真由 KS 负责。
 * ==========================================================================*/

/** 剥掉行首 Markdown 标题标记（`## 本章大纲` → `本章大纲`）；非标题文本原样返回。 */
export function stripHeadingMarks(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw.replace(/^#{1,6}\s+/, '')
}

/** 从正文里取第一个 Markdown 标题（已剥 `#`）；无标题返回空串。
 *  供"title 字段为空、但正文明明有标题"的回退使用——同一处解析，不在组件里重复写正则。 */
export function firstHeadingOf(content: string | null | undefined): string {
  if (!content) return ''
  const m = content.match(/^#{1,6}\s+(.+)$/m)
  return stripHeadingMarks(m?.[1] ?? '').trim()
}
