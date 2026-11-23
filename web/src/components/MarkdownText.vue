<!-- ============================================================================
 * MarkdownText.vue — 聊天气泡里的极简 Markdown 渲染（零依赖、零 v-html）
 *
 * 只渲染 markdown.ts 解析出的四种块：段落 / 有序或无序列表 / 代码块 + 行内加粗与行内码。
 * 全部走 Vue 插值（{{}}），模型输出永远是文本节点，绝不进 v-html ⇒ 无 XSS 面。
 * 行内 token 交给 InlineTokens.vue 渲染（模板保持干净、无 format 告警）。
 * 本件无 <style> 块；形状类落在 base.css（见 ThemeToggle.vue 头注同一理由）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed } from 'vue'
import { parseMarkdown } from '../utils/markdown.ts'
import InlineTokens from './InlineTokens.vue'

const props = defineProps<{ text: string; activeRef?: number | null }>()
const emit = defineEmits<{ refClick: [index: number] }>()
const blocks = computed(() => parseMarkdown(props.text))
</script>

<template>
  <div class="md-text">
    <template
      v-for="(block, bi) in blocks"
      :key="bi"
    >
      <p
        v-if="block.kind === 'paragraph'"
        class="md-text__p"
      >
        <template
          v-for="(line, li) in block.lines"
          :key="li"
        >
          <br v-if="li > 0">
          <InlineTokens
            :tokens="line"
            :active-ref="activeRef"
            @ref-click="emit('refClick', $event)"
          />
        </template>
      </p>

      <ol
        v-else-if="block.kind === 'list' && block.ordered"
        class="md-text__list"
      >
        <li
          v-for="(item, ii) in block.items"
          :key="ii"
        >
          <InlineTokens
            :tokens="item"
            :active-ref="activeRef"
            @ref-click="emit('refClick', $event)"
          />
        </li>
      </ol>
      <ul
        v-else-if="block.kind === 'list'"
        class="md-text__list"
      >
        <li
          v-for="(item, ii) in block.items"
          :key="ii"
        >
          <InlineTokens
            :tokens="item"
            :active-ref="activeRef"
            @ref-click="emit('refClick', $event)"
          />
        </li>
      </ul>

      <pre
        v-else
        class="md-text__pre"
      ><code>{{ block.lines.join('\n') }}</code></pre>
    </template>
  </div>
</template>
