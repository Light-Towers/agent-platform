<!-- ============================================================================
 * Answer.vue — 答案区（A2 的后半「答案落屏」在这里取屏上读数）
 * 三种屏上形态是**不同的事实**，不能合成一句文案（工单件 §4 A2 / 视觉件 §3）：
 *   · 还没提问（`!hasRound`）= 空态：一句引导 + 一个示例问题按钮，不白屏；
 *   · 正在流但还没有文本 = 明写「答案文本还没到」，而不是留一块空白让人以为读到了；
 *   · 跑完且答案为空 = 明写「本次没有可读的答案文本」（服务端给了 done 但没给 answer
 *     也是真实存在的一种收尾，cache-hit 旁路的 done 就不带 answer）。
 * 终态徽标三值走 `--cat-*` 的**图形通道**（边框 + tint 底），文本仍是 `--text-1`：
 *   视觉件 §3 那句「终态徽标置 failed（--cat-failure）」与 §2.2 那句「族色不得进文字
 *   通道」在这一格里必须同时成立，读法是「徽标以失败族呈现」而不是「徽标文本涂失败色」
 *   —— tint 底上的 `--text-2` 实测只有 4.14:1，所以本仓的既有做法（`.count-badge`、
 *   `.banner`）都是 tint + `--text-1`，这里沿同一形。
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注。
 * ==========================================================================-->
<script setup lang="ts">
import { answerText, busy, hasRound, terminal, threadId, useExample, type Terminal } from '../stores/session'

/** 终态三值的人话。判据只看 `done`（A7）：`open` 那句不得写成「完成」。 */
const TERM_LABEL: Record<Terminal, string> = {
  open: '未完成（没收到 done 帧）',
  completed: '已定稿',
  failed: '失败',
}
</script>

<template>
  <div class="answer">
    <div
      v-if="!hasRound"
      class="empty"
    >
      <p>还没有提问。</p>
      <p class="hint">
        <button
          type="button"
          class="btn"
          @click="useExample"
        >
          试试：这个平台能帮我查什么？
        </button>
      </p>
    </div>

    <template v-else>
      <p
        v-if="answerText === '' && busy"
        class="hint"
      >
        答案文本还没到（已读到 {{ hasRound ? '过程事件' : '' }}{{ busy ? '，仍在等待' : '' }}）。
      </p>
      <p
        v-else-if="answerText === ''"
        class="hint"
      >
        本次没有可读的答案文本。
      </p>
      <p
        v-else
        class="answer__text"
      >
        {{ answerText }}<span
          v-if="busy"
          class="dot-live"
          aria-hidden="true"
        />
      </p>

      <p class="answer__foot">
        <span
          class="term"
          :class="`term--${terminal}`"
        >{{ TERM_LABEL[terminal] }}</span>
        <span
          v-if="threadId !== ''"
          class="hint"
        >会话号 <code class="t-name">{{ threadId }}</code></span>
      </p>
    </template>
  </div>
</template>
