<!-- ============================================================================
 * App.vue — PR-0 的骨架壳（刻意是"半个界面"，不是成品）
 * 本批射程内它只证四件事：① tokens→base→events 这条装配链在浏览器里成立；
 * ② 主题三档真的改 <html> 上的属性；③ 图例由 events.ts 的代码渲染而不是手抄；
 * ④ `pnpm build` 的产物能被 agent_server 挂在 /ui 下打开（A1）。
 * 会话列表 / 时间线 / 答案区 / 密钥框**都不在这里**：它们属 PR-1（SSE 消费）与
 * PR-2（对话页），现在放上去就只能放假数据 —— 而 POC 宿主页已经干过这件事并
 * 在页头明写"每个数字都是假数据"，产品代码里不该带这种东西出厂。
 * 本件同样没有 <style> 块，理由见 ThemeToggle.vue 头注。
 * ==========================================================================-->
<script setup lang="ts">
import Legend from './components/Legend.vue'
import ThemeToggle from './components/ThemeToggle.vue'
</script>

<template>
  <div class="app">
    <header class="topbar">
      <h1>
        Agent Platform 控制台
        <span class="hint">骨架（PR-0）</span>
      </h1>
      <span class="spacer" />
      <ThemeToggle />
    </header>

    <main class="stack">
      <section
        class="panel"
        aria-labelledby="hScope"
      >
        <h2 id="hScope">
          本批射程
        </h2>
        <div class="empty">
          <p>这里还没有会话。</p>
          <p class="hint">
            对话页属 <strong>PR-2</strong>，SSE 消费属 <strong>PR-1</strong>；
            本页只交骨架 —— 缺的那两块在此留白，不拿假数据顶位。
          </p>
        </div>
      </section>

      <Legend />
    </main>
  </div>
</template>
