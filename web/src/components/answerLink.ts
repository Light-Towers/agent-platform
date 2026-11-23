/* ============================================================================
 * answerLink.ts — 单轮 Answer 作用域的三向联动状态（R5a）
 *
 * 不放进全局 Pinia：答案角标、证据卡片、执行轨迹的联动只在当前这一轮有意义，
 * 换轮即重置。三个组件共享同一份模块级 ref，避免 prop 穿透整棵组件树。
 * 高亮色只引 tokens.css 语义令牌（由 base.css 的 .ev--pulse / .md-ref--active 消费）。
 * ==========================================================================*/
import { ref } from 'vue'

export const activeEvidenceIndex = ref<number | null>(null)
export const isEvidenceExpanded = ref(false)
export const forceTimelineOpen = ref(false)

export function selectEvidence(index: number): void {
  activeEvidenceIndex.value = index
  isEvidenceExpanded.value = true
}

export function locateStep(index: number): void {
  activeEvidenceIndex.value = index
  forceTimelineOpen.value = true
}

export function resetLink(): void {
  activeEvidenceIndex.value = null
  isEvidenceExpanded.value = false
  forceTimelineOpen.value = false
}
