<!-- ============================================================================
 * EvidenceList.vue — 依据列表（工单件 §7 PR-2 那句「依据列表」的落点）
 * 数据只读 `session.ts` 的 `evidence`（结构化三字段：node / count / preview），
 * **不在这里再从时间线文本里扒一遍**：PR-1 之所以把片段塞进一句文案，是因为那时
 * 没有消费者；PR-2 交了这张列表，片段的家就在这里 ⇒ 同一段 200 字预览同屏出现两处
 * 是重复（`sse.ts` 的 evidence 分支因此只写「片段见依据列表」）。
 * 两种"没东西"是**不同的事实**，各一句（不许合成一句含糊话）：
 *   · 还没提问 = 这一轮根本没跑过；
 *   · 跑过但列表是空的 = 服务端没给 `count > 0 且 preview 非空` 的 evidence 帧。
 *     后半句刻意写成"没给"而不是"读不到"：客户端无从区分"没有命中"与"命中了但
 *     服务端没带片段"，把它写成后者就是替服务端编造诊断。
 * ⚠ 本件在宽栏与窄栏**被挂载两次**（App.vue 那两格：≥1280 常显、768–1279 进原生
 *   `<details>`），组件因此必须是纯只读的 —— 这里没有任何本地状态，两次挂载读到的
 *   永远是同一个 computed。复审触发条件：一旦本件需要自己的可变状态，两处挂载就会
 *   各持一份真相，那时必须改成单点挂载 + CSS 折叠。
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注；`.evidence` / `.ev-row` 落在
 *   `base.css`。
 * ==========================================================================-->
<script setup lang="ts">
import { evidence, hasRound } from '../stores/session'
</script>

<template>
  <div class="evidence">
    <p
      v-if="!hasRound"
      class="hint"
    >
      还没提问，这一轮没有依据。
    </p>

    <p
      v-else-if="evidence.length === 0"
      class="hint"
    >
      这一轮服务端没有给出可展示的依据片段。
    </p>

    <ul
      v-else
      class="ev-list"
    >
      <li
        v-for="(row, i) in evidence"
        :key="i"
        class="ev-row"
      >
        <span class="ev__name">{{ row.node }}</span>
        <span class="num">{{ row.count }}</span>
        <p class="ev__body">
          {{ row.preview }}
        </p>
      </li>
    </ul>
  </div>
</template>
