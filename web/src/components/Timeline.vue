<!-- ============================================================================
 * Timeline.vue — 过程时间线（工单件 §7 PR-2「按类型分色」的落点）
 * 行形状逐字继承 `poc.html:183-187` 的三通道：图标 + 类型徽标（事件名原文）+ 正文。
 * 三通道不是装饰：族色只走图标与 3px 竖条，文本走 `--text-1`（视觉件 §2.2 的实算），
 * 而「事件名原文常显」同时承住工单件 §2.2「未识别事件不得静默吞掉」。
 * class 与图标**不在本件里判**：走 `icons.ts` 的 `rowClassOf` / `iconPathOf`，
 * 那两件是纯函数、能被 `verify-sse.mjs` §G 在 Node 里喂行断言（写在本件的 setup 里就出不来）。
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注；新增的 `.tl-toggle` / `.tl-wrap`
 *   落在 `base.css`，`.ev--transport` / `.term--*` 落在 `events.css`。
 * 窄栏折叠（<768 只留计数徽标，点开看全量）靠 `base.css` 的 `.timeline > .ev` 两条
 *   同文件成对规则 + 这里的 `open` 类；≥768 时 `.tl-toggle` 是 `display:none`，
 *   所以整条时间线常显而按钮不存在（`display:none` 的按钮同时退出 Tab 顺序）。
 * ==========================================================================-->
<script setup lang="ts">
import { ref } from 'vue'

import { busy, eventCount, hasRound, timeline } from '../stores/session'
import { iconPathOf, rowClassOf } from './icons'

const open = ref(false)
</script>

<template>
  <div class="tl-wrap">
    <button
      type="button"
      class="btn tl-toggle"
      :aria-expanded="open"
      aria-controls="tlList"
      @click="open = !open"
    >
      {{ open ? '收起事件' : '展开事件' }}
    </button>

    <div
      id="tlList"
      class="timeline"
      :class="{ open }"
    >
      <p
        v-if="!hasRound && eventCount === 0"
        class="hint col-hint"
      >
        还没有事件。提问后这里会按类型逐条出现过程事件。
      </p>

      <div
        v-for="(row, i) in timeline"
        :key="i"
        class="ev"
        :class="rowClassOf(row)"
      >
        <svg
          class="ico ev__ico"
          viewBox="0 0 16 16"
          aria-hidden="true"
          focusable="false"
        ><path :d="iconPathOf(row)" /></svg>
        <span class="ev__name">{{ row.event }}</span>
        <span class="ev__body">{{ row.text }}</span>
      </div>

      <!-- loading：尾部三行骨架条（视觉件 §3）。三行是形态常量不是数据，不来自快照。 -->
      <template v-if="busy">
        <div class="skel" />
        <div class="skel" />
        <div class="skel" />
      </template>

      <p
        v-if="hasRound && eventCount === 0 && !busy"
        class="hint"
      >
        这一轮没有读到任何事件帧。
      </p>
    </div>
  </div>
</template>
