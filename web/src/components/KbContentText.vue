<!-- ============================================================================
 * KbContentText.vue — 知识库切片正文的**单一渲染入口**（治本，plan-kb-text-single-render-entry）
 *
 * 把"图片按正文原位内嵌 + Markdown/HTML 标记 extended 渲染"封在组件内部：
 * 调用方只传 content，**没有 extended 开关可传**，不可能忘记解析标记。
 * 历史上每个显示点各自决定要不要剥标记，漏一处就是一个补丁；本件是唯一入口。
 * 零 v-html：文本走 MarkdownText（插值），图片走 AuthImage（:src 绑定）。
 * ==========================================================================-->
<script setup lang="ts">
import { parseContentTokens } from '../stores/sseReducer.ts'
import MarkdownText from './MarkdownText.vue'
import AuthImage from './AuthImage.vue'

defineProps<{ content: string }>()
</script>

<template>
  <div class="kb-chunk-content">
    <template
      v-for="(token, ti) in parseContentTokens(content)"
      :key="ti"
    >
      <MarkdownText
        v-if="token.kind === 'text'"
        :text="token.text"
        extended
        class="kb-chunk-md"
      />
      <AuthImage
        v-else
        :url="token.url"
        :alt="token.alt || '切片图片'"
        img-class="kb-inline-img"
      />
    </template>
  </div>
</template>
