/* ============================================================================
 * router/index.ts — 视图与会话深链（R4 / docs/plans/web-refactor）
 *
 * base '/ui/' + hash 历史（D-1 拍板）：URL 形如 /ui/#/chat/<sessionId>。
 * 不启用 history 模式：后端 /ui/* 仍保持「未知路径 404」的反假绿判据，
 * SPA fallback 属 D2，需另立 ADR 才能做。
 * 守卫复用 session 层的 hasFeature 单一问法；能力码未回读时不永久重定向。
 * ==========================================================================*/
import { createRouter, createWebHashHistory } from 'vue-router'

import ChatView from '../components/ChatView.vue'
import RoleGate from '../components/RoleGate.vue'
import KnowledgeWorkspace from '../components/KnowledgeWorkspace.vue'
import DatasourceConfig from '../components/DatasourceConfig.vue'
import HealthView from '../components/HealthView.vue'
import { useSessionStore } from '../stores/session.ts'

const ROLE_FEATURES = ['kb.upload', 'datasource.manage', 'execution.control', 'human_task.decide']

export const router = createRouter({
  history: createWebHashHistory('/ui/'),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat/:sessionId?', name: 'chat', component: ChatView },
    { path: '/role', name: 'role', component: RoleGate, meta: { anyFeature: ROLE_FEATURES } },
    { path: '/kb', name: 'kb', component: KnowledgeWorkspace, meta: { feature: 'kb.upload' } },
    {
      path: '/datasource', name: 'datasource', component: DatasourceConfig,
      meta: { feature: 'datasource.manage' },
    },
    { path: '/health', name: 'health', component: HealthView },
  ],
})

router.beforeEach((to) => {
  const session = useSessionStore()
  // 能力集跟随 /auth/me 回读；尚未回读完成时 features 为空，此时不判无权，
  // 让路由先渲染，等回读完成后由同一守卫在下次导航生效（与旧 effectiveView 的时序口径一致）。
  if (session.authPending) return true
  const one = to.meta.feature as string | undefined
  const any = (to.meta.anyFeature as string[] | undefined) ?? []
  const required = one ? [one, ...any] : any
  if (required.length === 0) return true
  if (required.some((code) => session.hasFeature(code))) return true
  return { name: 'chat' }
})
