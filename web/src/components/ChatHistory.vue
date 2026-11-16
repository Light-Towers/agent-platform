<!-- ============================================================================
 * ChatHistory.vue — 当前会话的历史对话原文（服务端 /history 回填，只读）
 *
 * 与 Answer.vue 的分工：Answer.vue 只显示**本轮** SSE 流式答案；本件显示**往轮**已持久化的
 * user/assistant 原文。切换会话时由 conversations store 回填，历史是服务端权威（不是本地
 * 快照），所以刷新后仍在。组件无 <style> 块，形状复用 base.css 的既有类。
 * ==========================================================================-->
<script setup lang="ts">
import { computed } from 'vue'
import { chatHistory, conversationsNotice } from '../stores/conversations.ts'

/** 只展示 user/assistant 两种角色的对话轮次；tool/system 原文不铺给用户。 */
const turns = computed(() =>
  chatHistory.value.filter((m) => m.role === 'user' || m.role === 'assistant'),
)
</script>

<template>
  <section class="ry-card">
    <h2 id="hChatHistory">
      历史对话
      <span class="count-badge">{{ turns.length }}</span>
    </h2>
    <p
      v-if="conversationsNotice"
      class="banner"
    >
      <strong>{{ conversationsNotice }}</strong>
    </p>
    <p
      v-if="!turns.length"
      class="hint"
    >
      该会话还没有历史消息。提问后，往轮对话会保存在这里，刷新或重进仍可查看。
    </p>
    <ol
      v-else
      class="chat-history"
    >
      <li
        v-for="m in turns"
        :key="`${m.index}-${m.id ?? ''}`"
        class="chat-history__item"
        :class="m.role === 'user' ? 'is-user' : 'is-assistant'"
      >
        <span class="o-head-sm">{{ m.role === 'user' ? '我' : '助手' }}</span>
        <div class="chat-history__text">
          {{ m.content }}
        </div>
      </li>
    </ol>
  </section>
</template>
