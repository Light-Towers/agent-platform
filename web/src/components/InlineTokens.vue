<!-- ============================================================================
 * InlineTokens.vue — 行内 Markdown token 渲染（加粗 / 行内码 / 文本）
 *
 * 只渲染 markdown.ts 的 InlineToken[]，全插值无 v-html。抽成组件是为了让
 * MarkdownText.vue 的段落/列表模板保持干净（不在一行里塞 v-for 序列触发 format 门禁）。
 * 本件无 <style> 块：.md-text__code 样式在 base.css。
 * ==========================================================================-->
<script setup lang="ts">
import type { InlineToken } from '../utils/markdown.ts'

defineProps<{ tokens: readonly InlineToken[]; activeRef?: number | null | undefined }>()
const emit = defineEmits<{ refClick: [index: number] }>()
</script>

<template>
  <template
    v-for="(tok, i) in tokens"
    :key="i"
  >
    <strong v-if="tok.kind === 'strong'">
      {{ tok.text }}
    </strong>
    <code
      v-else-if="tok.kind === 'code'"
      class="md-text__code"
    >{{ tok.text }}</code>
    <button
      v-else-if="tok.kind === 'ref'"
      type="button"
      class="md-ref"
      :class="{ 'md-ref--active': activeRef === Number(tok.text) - 1 }"
      :aria-label="`查看依据 ${tok.text}`"
      @click="emit('refClick', Number(tok.text) - 1)"
    >
      {{ tok.text }}
    </button>
    <template v-else>
      {{ tok.text }}
    </template>
  </template>
</template>
