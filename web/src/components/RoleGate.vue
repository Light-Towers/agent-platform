<!-- ============================================================================
 * RoleGate.vue — 「角色与能力」页（任务书 §四.1 的三件管理面视图组件之一，批 1 交付）
 *
 * 这一页是 G1（角色显隐）的**屏面读数**：当前角色码、服务端断言的能力集、两条给人读的
 * 说明（N3 下次登录生效 / 控制面占位）。它自己不做任何判定 —— 显隐的判据全在
 * `hasFeature`（会话层单一问法），本页只是把 /auth/me 回读到的值摊开给人核对。
 *
 * 两条刻意没做，都要读成"没做"而不是"做完了"：
 *  ① 本页**不发任何请求**（没有按钮、没有刷新动作）：登录态与能力集的刷新点只有一个
 *     —— 会话层的 resumeSession / backfillIdentityAfterLogin。这里再发一发就是第二个
 *     身份确认点，两处各自解释 503/401 会漂出两套读法。
 *  ② 能力码**不带中文释义**：码→含义的表住在服务端 authorization.py，抄一份就是造出
 *     第二个事实源（auth.ts 纪律④同源）。屏上给的是码本身，那正是显隐判据的原文。
 *  入口显隐在 App.vue（showRoleGate）：viewer 没有任何管理向能力码 ⇒ 连本页的页签都不渲染。
 * ⚠ 本件没有 <style> 块（理由见 ThemeToggle.vue 头注）；用到的类全在 base.css。
 * ==========================================================================-->
<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useSessionStore } from '../stores/session'
const sessionStore = useSessionStore()
const { authFeatures, authRole } = storeToRefs(sessionStore)

</script>

<template>
  <main class="grid">
    <div class="col">
      <section
        class="ry-card"
        aria-labelledby="hRole"
      >
        <h2 id="hRole">
          角色与能力
        </h2>
        <p class="hint">
          本页只渲染服务端断言回读的 role 与 features，不做任何判定、不发任何请求。
        </p>

        <p>
          当前角色：<code class="t-name">{{ authRole }}</code>
        </p>

        <p class="o-head-sm">
          能力码（界面显隐的唯一判据，原文即下表）
        </p>
        <ul class="stack">
          <li
            v-for="f in authFeatures"
            :key="f"
          >
            <code class="t-name">{{ f }}</code>
          </li>
        </ul>

        <p class="hint">
          角色改动<strong>下次登录生效</strong>：管理员改了你的角色后，本页显示的是当前令牌
          签发时断言到的值；重新登录（换新令牌）才会看到新角色。这页不会在你不知情时变出能力。
        </p>
        <p class="hint">
          控制面（execution.control / human_task.decide 两枚能力码对应的执行控制与人工审批
          界面）本轮未建：没有可点的入口，也没有占位按钮 —— 不给指不到东西的引导。
        </p>
      </section>
    </div>
  </main>
</template>
