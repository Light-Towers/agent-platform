<!-- ============================================================================
 * Legend.vue — 屏上事件图例（V2 判据的那半：图例行数与代码一一对应）
 * 数据源是 `src/api/events.ts` 的 EVENT_LEGEND，**不在这里另写一份文案**：
 * POC 宿主页已经证明"两份图例"会漂（视觉件 §2.2 的同一条），所以这里只渲染。
 * 标题里的两个数是**现算的**（`EVENT_NAMES.length` / sw 去重后的 size），
 * 不是抄来的 —— 抄一个 12 在那天后端加事件时就成假话，而门禁 6 恰好会抓到那种漂移。
 * 本件同样没有 <style> 块，理由见 ThemeToggle.vue 头注。
 * ==========================================================================-->
<script setup lang="ts">
import { computed } from 'vue'
import { EVENT_LEGEND, EVENT_NAMES } from '../api/events'

const famCount = computed(() => new Set(EVENT_NAMES.map((n) => EVENT_LEGEND[n].sw)).size)
</script>

<template>
  <!-- details/summary 沿用 POC 页形状：图例是参考信息，不占首屏主位（视觉件 §2.1） -->
  <details class="panel">
    <summary>
      <span class="o-head-sm">图例：{{ EVENT_NAMES.length }} 类事件 → {{ famCount }} 族色相</span>
    </summary>
    <ul class="legend">
      <!-- ul/li 是为语义选的（图例就是一列表，读屏会报条数）；li 的默认 marker
           是否会因 .lg-row 的 display:grid 而消失，属屏上判据，随 V2 实拍核，不在这里断言。 -->
      <li
        v-for="name in EVENT_NAMES"
        :key="name"
        class="lg-row"
      >
        <span
          class="lg-swatch"
          :class="`sw--${EVENT_LEGEND[name].sw}`"
          aria-hidden="true"
        />
        <code class="lg-name">{{ name }}</code>
        <span class="lg-fam">{{ EVENT_LEGEND[name].fam }}</span>
      </li>
    </ul>
    <p class="hint">
      本表由 <code>src/api/events.ts</code> 渲染，与 <code>events.css</code> 同源；
      「key 集 == 后端派生事件全集」由 <code>scripts/check-tokens.mjs</code> 断言 6 每次构建校验。
    </p>
  </details>
</template>
