<!-- ============================================================================
 * ChatStream.vue — 连续消息流（主流 chat 形态的对话主体）
 *
 * 把两块来源拼成**一条**自顶向下的气泡流：
 *   · 往轮：conversations store 的 /history 原文（切会话时回填，服务端权威）；
 *   · 本轮：session store 的 question（user 气泡）+ Answer.vue（assistant 气泡，流式）。
 * 本轮答案**也作为一条 assistant 气泡**落在流尾 ⇒ 视觉上用户问、助手答是连续的，
 * 而不再像以前那样"往轮在历史卡、本轮在答案卡"割裂。
 * 用 Answer.vue 而非重写答案渲染：三态（未提问/文本未到/无答案）与终态徽标都复用既有件，
 * store 的 ask()/snapshot 语义一点不动（verify-sse.mjs 钉死它）。
 * 本件无 <style> 块：形状类落在 base.css（见 ThemeToggle.vue 头注同一理由）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import Answer from './Answer.vue'
import MarkdownText from './MarkdownText.vue'
import { storeToRefs } from 'pinia'
import { useConversationsStore } from '../stores/conversations.ts'
const conversationsStore = useConversationsStore()
const { chatHistory, conversationsNotice } = storeToRefs(conversationsStore)

import { useSessionStore } from '../stores/session'
const sessionStore = useSessionStore()
const { answerText, busy, hasRound, question } = storeToRefs(sessionStore)
const { useExample } = sessionStore


/** 只展示 user/assistant 的对话轮次；tool/system 原文不铺给用户。 */
const turns = computed(() =>
  chatHistory.value.filter((m) => m.role === 'user' || m.role === 'assistant'),
)

/** 本轮 user 气泡：用提问时的快照文本，不直接绑 question（输入框会继续被编辑）。 */
const currentQuestion = ref('')
watch(hasRound, (round) => {
  if (round) currentQuestion.value = question.value.trim()
})

const scroller = ref<HTMLElement | null>(null)
/** 新消息或答案文本增长时滚到底（chat 的预期行为）。 */
watch([() => turns.value.length, answerText, busy], async () => {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<template>
  <div class="chat-stream">
    <p
      v-if="conversationsNotice"
      class="banner"
    >
      <strong>{{ conversationsNotice }}</strong>
    </p>

    <div
      ref="scroller"
      class="chat-stream__scroll"
    >
      <div
        v-if="!turns.length && !hasRound"
        class="chat-stream__empty"
      >
        <p class="hint">
          还没有消息。在下面输入框提问（会自动建会话），或试试示例：
        </p>
        <button
          type="button"
          class="ry-btn"
          @click="useExample"
        >
          这个平台能帮我查什么？
        </button>
      </div>

      <ol
        v-else
        class="chat-stream__list"
      >
        <li
          v-for="m in turns"
          :key="`${m.index}-${m.id ?? ''}`"
          class="msg"
          :class="m.role === 'user' ? 'msg--user' : 'msg--assistant'"
        >
          <span class="msg__label">{{ m.role === 'user' ? '我' : '助手' }}</span>
          <div class="msg__bubble msg__bubble--md">
            <MarkdownText :text="m.content" />
          </div>
        </li>

        <!-- 本轮：user 气泡 + assistant 气泡（Answer.vue 流式填内容） -->
        <template v-if="hasRound">
          <li
            v-if="currentQuestion !== ''"
            class="msg msg--user"
          >
            <span class="msg__label">我</span>
            <div class="msg__bubble msg__bubble--md">
              <MarkdownText :text="currentQuestion" />
            </div>
          </li>
          <li class="msg msg--assistant">
            <span class="msg__label">助手</span>
            <div class="msg__bubble msg__bubble--live">
              <Answer />
            </div>
          </li>
        </template>
      </ol>
    </div>
  </div>
</template>
