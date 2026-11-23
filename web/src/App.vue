<!-- ============================================================================
 * App.vue — RuoYi 三段式后台框架外壳（R4 起只排格位 + 路由出口）
 * 内容区由 <RouterView /> 承载：chat / role / kb / datasource / health 五视图。
 * 视图显隐由路由守卫按服务端断言的能力码决定；无权限回落 /chat。
 * 本件无 <style> 块，形状类落 base.css（理由见 ThemeToggle.vue 头注）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import LoginView from './components/LoginView.vue'
import ThemeToggle from './components/ThemeToggle.vue'
import { useConversationsStore } from './stores/conversations.ts'
import { useSessionStore } from './stores/session.ts'

const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const sessionStore = useSessionStore()
const { banners, canChat, dropped, identityNote, loggedIn } = storeToRefs(sessionStore)
const { clearBanners, hasFeature, resumeSession, signOut } = sessionStore
const { clearConversations, loadSessions } = conversationsStore

/** 与旧 effectiveView 同一组渲染映射：判定仍在服务端 /auth/me，这里只决定菜单显隐。 */
const showRoleGate = computed(() =>
  hasFeature('kb.upload') || hasFeature('datasource.manage')
  || hasFeature('execution.control') || hasFeature('human_task.decide'))
const showKb = computed(() => hasFeature('kb.upload') || hasFeature('kb.publish'))
const showDatasource = computed(() => hasFeature('datasource.manage'))
const showHealth = computed(() => true)

const VIEW_LABELS: Record<string, string> = {
  chat: '对话页', role: '角色页', kb: '知识库页', datasource: '数据源页', health: '平台健康',
}
const viewLabel = computed(() => canChat.value ? (VIEW_LABELS[String(route.name ?? '')] ?? '对话页') : '登录面')

onMounted(async () => {
  await resumeSession()
  if (canChat.value) await loadSessions()
})

/* 同页登录/掉态：登录后拉目录，掉态清目录，避免把上一人的会话选中态带给下一个人。 */
watch(canChat, (ok) => {
  if (ok) void loadSessions()
  else clearConversations()
})

/* 能力码在导航之后才回读完成 ⇒ 守卫当时放行，这里补一次回落（对齐旧 effectiveView 的响应式语义）。 */
watch(() => [sessionStore.canChat, sessionStore.authFeatures], () => {
  if (!sessionStore.canChat) return
  const one = route.meta.feature as string | undefined
  const any = (route.meta.anyFeature as string[] | undefined) ?? []
  const required = one ? [one, ...any] : any
  if (required.length && !required.some((code) => sessionStore.hasFeature(code))) {
    void router.replace({ name: 'chat' })
  }
})

function onSignOut(): void {
  clearConversations()
  void signOut()
}
</script>

<template>
  <LoginView v-if="!canChat" />

  <div
    v-else
    class="ry-layout"
  >
    <aside class="ry-aside">
      <div class="ry-aside__logo">
        Agent Platform 控制台
      </div>
      <nav
        class="ry-menu"
        aria-label="主导航"
      >
        <RouterLink
          to="/chat"
          class="ry-menu-item"
          active-class="is-active"
        >
          对话
        </RouterLink>
        <RouterLink
          v-if="showRoleGate"
          to="/role"
          class="ry-menu-item"
          active-class="is-active"
        >
          角色与能力
        </RouterLink>
        <RouterLink
          v-if="showKb"
          to="/kb"
          class="ry-menu-item"
          active-class="is-active"
        >
          知识库
        </RouterLink>
        <RouterLink
          v-if="showDatasource"
          to="/datasource"
          class="ry-menu-item"
          active-class="is-active"
        >
          数据源
        </RouterLink>
        <RouterLink
          v-if="showHealth"
          to="/health"
          class="ry-menu-item"
          active-class="is-active"
        >
          平台健康
        </RouterLink>
      </nav>
    </aside>

    <header class="ry-header">
      <span class="ry-header__title">{{ viewLabel }}</span>
      <span class="spacer" />
      <span
        class="ry-header__user"
        role="status"
      >{{ identityNote }}</span>
      <button
        v-if="loggedIn"
        type="button"
        class="ry-btn ry-btn--text"
        @click="onSignOut"
      >
        退出
      </button>
      <ThemeToggle />
    </header>

    <main class="ry-main">
      <!-- 错误态 banner 跨轮累积（四条要在同一屏可对比） -->
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
          class="ry-btn"
          @click="clearBanners"
        >
          清除提示
        </button>
      </section>

      <RouterView />
    </main>
  </div>
</template>
