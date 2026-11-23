<!-- ============================================================================
 * CitationList.vue — 回答的结构化引用卡片（plan-image-citation-e2e-2026-11-23）
 * 只渲染后端 rich.citations（会展/RAG 已归一成同一形状）。这对用户是"可点的来源"：
 * 文档名 + 章节 + 片段。知识文档无独立 URL，故不做外链跳转，title 展示片段供核对。
 * 本件无 <style> 块；形状类落 base.css。
 * ==========================================================================-->
<script setup lang="ts">
import type { RichCitation } from '../api/sse.ts'

defineProps<{ citations: readonly RichCitation[] }>()
</script>

<template>
  <div
    v-if="citations.length > 0"
    class="rich-citations"
  >
    <div class="rich-citations__label">
      引用来源（{{ citations.length }}）
    </div>
    <ul class="rich-citations__list">
      <li
        v-for="(cite, i) in citations"
        :key="`${cite.source.name}-${cite.chunk_id ?? i}`"
        class="rich-citations__item"
        :title="cite.snippet || cite.source.name"
      >
        <span class="rich-citations__index">{{ i + 1 }}</span>
        <span class="rich-citations__name">{{ cite.source.name }}</span>
        <span
          v-if="cite.heading"
          class="rich-citations__heading"
        >· {{ cite.heading }}</span>
        <span
          v-if="cite.snippet"
          class="rich-citations__snippet"
        >{{ cite.snippet }}</span>
      </li>
    </ul>
  </div>
</template>
