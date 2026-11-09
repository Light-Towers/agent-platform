<!-- ============================================================================
 * App.vue — 对话页（工单件 §7 PR-2：两栏视图 = 视觉件 §2.1 视图 A）
 * 骨架是 `minmax(0, 1.1fr) minmax(0, 1.4fr)` 两栏（住在 `base.css` 的 `.grid`），
 * 本件只排**格位**，不写任何形状：组件无 <style> 块（理由见 ThemeToggle.vue 头注）。
 * 三态的落点（视觉件 §3 那三行在这里各自的实物）：
 *   · loading = 提交钮 aria-disabled + 文案「等待 done…」+ `Timeline.vue` 尾部骨架条；
 *   · empty  = `Answer.vue` 的引导与示例按钮 + `Timeline.vue` 的「还没有事件」；
 *   · error  = 顶部 banner 区（`session.ts` 累积，四分支文案互异 = A8）。
 * 两条**刻意没做**的，都要读成"没做"而不是"做完了"：
 *   ① 没有会话历史列表。参照物 `poc.html:56-58` 那三条是**假数据**，而它的宿主
 *      页头已明写"每个数字都是假数据"；产品代码里没有可追溯的来源就不许上屏
 *      （历史接口属 PR-3，未开工）。
 *   ② 没有那条跳 PR-4 灯阵页的 `<a href>` 链接。工单件 §7 PR-2 行要求交它，但
 *      PR-4 未开工 ⇒ 目标不存在，现在加就是一条当场 404 的死链 —— 与 ①同一条纪律
 *      （不给指不到东西的引导）。**复审触发条件**：PR-4 交付批同批把链接接进 header。
 * ⚠ Tab 顺序与本件 DOM 顺序一致，不靠 `tabindex`/`order` 重排（重排会让"键盘走到的
 *   顺序"与"肉眼看到的顺序"分叉，视觉件 §3 那条线就失去可核对性）。因此实序是
 *   header → 密钥 → 输入 → 提交 →（窄栏才有）展开事件 —— 与 §3 那句「header → 输入
 *   → 提交 → 时间线项」的差值是**密钥栏在前**这一条，已登记在取证件；V6 的判据
 *   （键盘不碰鼠标完成一次提问）不受影响。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted } from 'vue'

import Answer from './components/Answer.vue'
import ApiKeyBox from './components/ApiKeyBox.vue'
import EvidenceList from './components/EvidenceList.vue'
import Legend from './components/Legend.vue'
import LoginView from './components/LoginView.vue'
import ThemeToggle from './components/ThemeToggle.vue'
import Timeline from './components/Timeline.vue'
import {
  ask,
  banners,
  busy,
  canChat,
  canSubmit,
  clearBanners,
  dropped,
  evidence,
  eventCount,
  identityNote,
  loggedIn,
  question,
  resumeSession,
  signOut,
  traceNote,
  waiting,
} from './stores/session'

/* 挂载时确认一次登录态（A8「刷新仍在登录」那一格的调用点）。本件不自己决定何时确认：
 * 会话层故意不在模块加载时自发请求，否则行为件在 Node 里 import 会话层就会多一个 fetch。 */
onMounted(() => { void resumeSession() })

/* 提交那一行的第二通道：不可用态只说明"现在不能按"，说不清**为什么**不能按（A4 的
 * 同一条要求在控件上也成立）。两句互斥，所以只可能同时出现一句。 */
const submitHint = computed(() =>
  waiting.value
    ? '等待 done…（判定完成只看 done 帧，转圈不是完成信号）'
    : canSubmit.value ? '' : '输入为空时不能提交')

/** 提问。`ask()` 内部全 catch（两条凭据前置校验也在 `session.ts` 接住了），这里仍
 *  显式 `void` 掉 Promise：模板里的处理器不该有未处理的 promise（lint 的
 *  `no-floating-promises` 只看得到这一层，看不到组件里）。 */
function submit(): void {
  void ask()
}

function onSignOut(): void {
  void signOut()
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <h1>
        Agent Platform 控制台
        <span class="hint">{{ canChat ? '对话页（PR-2）' : '登录面（PR-2b）' }}</span>
      </h1>
      <span class="spacer" />
      <!-- 身份那一行只在页眉出现一次，文案由会话层的 `identityNote` 给（四种读法各自一句，
           其中两种是「未确认」与「走的是密钥」—— 把它们合并成「未登录」就是把 503 读成凭据问题）。 -->
      <span
        class="hint"
        role="status"
      >{{ identityNote }}</span>
      <button
        v-if="loggedIn"
        type="button"
        class="btn"
        @click="onSignOut"
      >
        退出
      </button>
      <ThemeToggle />
    </header>

    <!-- error 态：banner 跨轮累积（一次流最多命中一条分支，四条要在同一屏可对比）。 -->
    <section
      v-if="banners.length > 0"
      class="stack"
      aria-label="本轮提示"
    >
      <div
        v-for="(line, i) in banners"
        :key="i"
        class="banner"
      >
        <strong>{{ line }}</strong>
      </div>
      <p
        v-if="dropped > 0"
        class="hint"
      >
        另有 {{ dropped }} 条更早的提示已折叠（超出上限时丢的是最旧那条，不静默丢）。
      </p>
      <button
        type="button"
        class="btn"
        @click="clearBanners"
      >
        清除提示
      </button>
    </section>

    <!-- 视图闸门（PR-2b）：未确认到登录态时屏上只有登录面，没有空对话框。
         两个 `<main>` 是 v-if / v-else 关系 ⇒ 任一时刻 DOM 里只有一个，语义上仍是一文档一主区。 -->
    <LoginView v-if="!canChat" />

    <main
      v-else
      class="grid"
    >
      <!-- 栏一（1.1fr）：答案 / 依据 / 密钥 -->
      <div class="col">
        <section
          class="panel"
          aria-labelledby="hAnswer"
        >
          <h2 id="hAnswer">
            答案
          </h2>
          <Answer />
          <!-- 请求号那一行：没有就明说没有（`session.ts` 的 traceNote 已含这一支）。 -->
          <p
            v-if="busy || eventCount > 0"
            class="hint"
          >
            {{ traceNote }}
          </p>
        </section>

        <section
          class="panel only-wide"
          aria-labelledby="hEvidence"
        >
          <h2 id="hEvidence">
            依据列表
            <span class="count-badge">{{ evidence.length }}</span>
          </h2>
          <EvidenceList />
        </section>

        <section class="panel">
          <ApiKeyBox />
        </section>

        <!-- 768–1279（含 <768 的单栏档）：依据列表并进原生 details（视觉件 §2.1 表第二行），
             折叠的是"占多高的片段列表"，计数仍在 summary 上读得到。 -->
        <details class="panel only-narrow">
          <summary>
            <span class="o-head-sm">依据列表（窄栏折叠）</span>
            <span class="count-badge">{{ evidence.length }}</span>
          </summary>
          <EvidenceList />
        </details>
      </div>

      <!-- 栏二（1.4fr）：过程时间线 + 输入区 -->
      <div class="col">
        <section
          class="panel"
          aria-labelledby="hTimeline"
        >
          <h2 id="hTimeline">
            事件时间线
            <span class="count-badge">{{ eventCount }}</span>
          </h2>

          <Timeline />

          <form
            class="composer"
            @submit.prevent="submit"
          >
            <input
              v-model="question"
              class="field"
              type="text"
              placeholder="输入问题…"
              autocomplete="off"
              aria-label="问题"
            >
            <div class="composer__row">
              <!-- ⚠ **刻意用 `aria-disabled` 而不是原生 `disabled`**（刀㊲ 实拍量出来的缺陷，
                   不是预防性的好愿望）：原生 `disabled` 把控件从 tab 序里抽掉，于是键盘用户
                   按下 Enter 的那一瞬间焦点被浏览器收回 `body`（V6 那一格实测
                   `activeElement.tagName === 'BODY'`）⇒ 每问一次就要从头 Tab 一遍，
                   「键盘一遍走通」在实物上不成文。换 `aria-disabled` 后控件仍在序里，
                   而“不能提交”仍由 `ask()` 自守（空输入与流中两道早退），不靠属性兼容。 -->
              <button
                type="submit"
                class="btn btn-primary"
                :aria-disabled="!canSubmit"
              >
                {{ busy ? '等待 done…' : '提问' }}
              </button>
              <span
                v-if="submitHint !== ''"
                class="hint"
              >{{ submitHint }}</span>
            </div>
          </form>
        </section>
      </div>
    </main>

    <!-- 事件图例只在对话页出现：登录页一行事件都没得对，把图例放上去就是拿不相干的
         读数占位置（与文件头那句「不给指不到东西的引导」同一条纪律）。 -->
    <Legend v-if="canChat" />
  </div>
</template>
