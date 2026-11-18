<!-- ============================================================================
 * App.vue — RuoYi 三段式后台框架外壳（顶栏 + 侧边栏 + 内容区），内容区承载对话/角色/知识库/数据源视图。
 * 外壳用 `base.css` 的 `.ry-layout` / `.ry-header` / `.ry-aside` / `.ry-menu` / `.ry-main`；
 * 本件只排**格位**，不写任何形状：组件无 <style> 块（理由见 ThemeToggle.vue 头注）。
 * 三态的落点（视觉件 §3 那三行在这里各自的实物）：
 *   · loading = 提交钮 aria-disabled + 文案「等待 done…」+ `Timeline.vue` 尾部骨架条；
 *   · empty  = `Answer.vue` 的引导与示例按钮 + `Timeline.vue` 的「还没有事件」；
 *   · error  = 顶部 banner 区（`session.ts` 累积，四分支文案互异 = A8）。
 * 两条**刻意没做**的，都要读成"没做"而不是"做完了"：
 *   ① 没有会话历史列表（历史接口属 PR-3，未开工）—— 产品代码里没有可追溯的来源就不许上屏。
 *   ② 平台健康灯阵页（PR-4）已接真实 `/health` 端点（HealthView.vue），不再是演示页；
 *      侧栏「平台健康」入口对所有已登录用户开放（`/health` 是免鉴权探针路径）。
 * ⚠ Tab 顺序与本件 DOM 顺序一致，不靠 `tabindex`/`order` 重排（重排会让"键盘走到的
 *   顺序"与"肉眼看到的顺序"分叉，视觉件 §3 那条线就失去可核对性）。因此实序是
 *   header → 密钥 → 输入 → 提交 →（窄栏才有）展开事件 —— 与 §3 那句「header → 输入
 *   → 提交 → 时间线项」的差值是**密钥栏在前**这一条，已登记在取证件；V6 的判据
 *   （键盘不碰鼠标完成一次提问）不受影响。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import ChatStream from './components/ChatStream.vue'
import EvidenceList from './components/EvidenceList.vue'
import Legend from './components/Legend.vue'
import LoginView from './components/LoginView.vue'
import RoleGate from './components/RoleGate.vue'
import KbUpload from './components/KbUpload.vue'
import KnowledgeBaseAdmin from './components/KnowledgeBaseAdmin.vue'
import DatasourceConfig from './components/DatasourceConfig.vue'
import ThemeToggle from './components/ThemeToggle.vue'
import HealthView from './components/HealthView.vue'
import Timeline from './components/Timeline.vue'
import {
  activeSessionId,
  clearConversations,
  conversationsBusy,
  conversationsNotice,
  loadHistory,
  loadSessions,
  newSession,
  removeSession,
  renameSession,
  selectSession,
  sessionList,
} from './stores/conversations.ts'
import {
  ask,
  authToken,
  banners,
  busy,
  canChat,
  canSubmit,
  clearBanners,
  dropped,
  evidence,
  eventCount,
  hasFeature,
  identityNote,
  knowledgeScope,
  loggedIn,
  question,
  resetRound,
  resumeSession,
  signOut,
  traceNote,
  waiting,
} from './stores/session'
import { listKnowledgeBases, type KbKnowledgeBase } from './api/kb.ts'

/* ---- G1 管理面导航（批 1：对话页 + 角色页；知识库/数据源两页随批 2/批 3 接入）----
 * 视图键是本组件的局部 ref：只有本件读写它，不进会话层（会话层是跨组件共享态，
 * 单组件的 UI 态进会话层 = 把局部事物全局化）。 */
const activeView = ref<'chat' | 'role' | 'kb' | 'kb-admin' | 'datasource' | 'health'>('chat')

/**
 * 「角色」页入口的显隐判据：手里有任一管理向能力码才显示。viewer 只有 chat.run /
 * session.history ⇒ 四码全无 ⇒ 只看到对话页（任务书 §四.1「均无则普通用户只看到对话页」）。
 * 码集对应方案 §4 的管理面格（kb.upload / datasource.manage / execution.control /
 * human_task.decide）；这是**渲染映射**不是判定 —— 判定（谁有什么码）在服务端 /auth/me。
 */
const showRoleGate = computed(() =>
  hasFeature('kb.upload') || hasFeature('datasource.manage')
  || hasFeature('execution.control') || hasFeature('human_task.decide'))

/** 知识库上传页入口（feature `kb.upload`）。G2 交付。 */
const showKb = computed(() => hasFeature('kb.upload'))
/** 知识库管理页入口（P3）：删除走 kb.publish 门控，有发布权或上传权即显示管理入口。 */
const showKbAdmin = computed(() => hasFeature('kb.publish') || hasFeature('kb.upload'))
/** 问数数据源配置页入口（feature `datasource.manage`）。G3 交付。 */
const showDatasource = computed(() => hasFeature('datasource.manage'))

/** 平台健康灯阵页入口（PR-4 真实视图）：`/health` 是免鉴权探针路径，对所有已登录用户开放。 */
const showHealth = computed(() => true)

/** 页眉视图标签（对话/角色/知识库/数据源），供 h1 旁的 hint 显示当前所在面。 */
const viewLabel = computed(() => {
  if (!canChat.value) return '登录面'
  if (activeView.value === 'chat') return '对话页'
  if (activeView.value === 'kb') return '知识库页'
  if (activeView.value === 'kb-admin') return '知识库管理'
  if (activeView.value === 'datasource') return '数据源页'
  return '角色页'
})

/**
 * 对话页是否在屏上。视图键停在管理面页但该页已无权渲染（登录态掉了、或换成无管理向
 * 能力的角色）⇒ 回对话页兜底，不给「无权页面白屏」留缝。
 */
const chatShown = computed(() => activeView.value === 'chat' || (!showRoleGate.value && !showKb.value && !showDatasource.value && !showHealth.value))

/* 挂载时确认一次登录态（A8「刷新仍在登录」那一格的调用点）。本件不自己决定何时确认：
 * 会话层故意不在模块加载时自发请求，否则行为件在 Node 里 import 会话层就会多一个 fetch。 */
onMounted(async () => {
  await resumeSession()
  if (canChat.value) {
    await loadSessions()
    void refreshKnowledgeBases()
  }
})

/* 登录态变化（登录后 / 掉态后）同步会话目录：登录后拉列表，掉态后清空，避免把上一人的
 * 会话选中态带到下一个人。刷新路径 onMounted 已处理，这里只补「同页登录/登出」的跃迁。 */
watch(canChat, (ok) => {
  if (ok) {
    void loadSessions()
    void refreshKnowledgeBases()
  } else {
    clearConversations()
  }
})

/* ---- 知识范围选择器（plan-knowledge-base-model 步骤 4）----
 * 选中值 `knowledgeScope` 住在会话层（ask() 发请求时透传 knowledge_id）；**清单**是
 * 对话页的展示态，留在本组件（局部 UI 态不进会话层，同 activeView 那条理由）。
 * 数据源 GET /kb/knowledge-bases（feature 门 chat.run，与会话层同权可见）。
 * 拉取失败**不拦提问**：选择器退化为只剩「全部知识库」一项，失败原因给一句 hint，
 * 与「登记列表是补充项」同一条纪律 —— 检索主链路不为辅助清单买单。 */
const knowledgeBases = ref<readonly KbKnowledgeBase[]>([])
const knowledgeBasesNotice = ref('')

async function refreshKnowledgeBases(): Promise<void> {
  try {
    knowledgeBases.value = await listKnowledgeBases(authToken.value)
    knowledgeBasesNotice.value = ''
  } catch (err) {
    knowledgeBasesNotice.value = err instanceof Error ? err.message : String(err)
  }
}

/* 提交那一行的第二通道：不可用态只说明"现在不能按"，说不清**为什么**不能按（A4 的
 * 同一条要求在控件上也成立）。两句互斥，所以只可能同时出现一句。 */
const submitHint = computed(() =>
  waiting.value
    ? '等待 done…（判定完成只看 done 帧，转圈不是完成信号）'
    : canSubmit.value ? '' : '输入为空时不能提交')

/** 提问。`ask()` 内部全 catch（两条凭据前置校验也在 `session.ts` 接住了），这里仍
 *  显式 `void` 掉 Promise：模板里的处理器不该有未处理的 promise（lint 的
 *  `no-floating-promises` 只看得到这一层，看不到组件里）。 */
/** 主流 chat 行为：没有当前会话时先自动建一个，确保每轮问答都归属某个会话窗口。
 * 第二参数是 sessionId（保持 ask(fetchImpl) 兼容 verify-sse.mjs）。 */
async function submit(): Promise<void> {
  let sid = activeSessionId.value
  if (!sid) {
    await newSession()
    sid = activeSessionId.value
  }
  await ask(undefined, sid || undefined)
  // 本轮已落库：用服务端权威历史回填消息区，再清掉本轮流式快照（否则同一轮显示两遍）。
  // 治本点：历史以 chatHistory 为唯一显示源；ask 后不回填就会出现「问第二句第一句没了」。
  await loadHistory()
  resetRound()
  // 首轮问答后服务端按内容生成了标题，刷新列表让它上屏（后续轮次幂等无副作用）。
  await loadSessions()
}

/* ---- 会话标题内联编辑 ----
 * 编辑态是纯本组件 UI 态（不进 store）：editingId 标记正在改哪一项，draft 存草稿。
 * 保存走 store 的 renameSession（PATCH + 回填 title_source=manual），失败提示留在 store。 */
const editingId = ref<string>('')
const draftTitle = ref('')

function startRename(s: { session_id: string; title: string }): void {
  editingId.value = s.session_id
  draftTitle.value = s.title
}

function cancelRename(): void {
  editingId.value = ''
  draftTitle.value = ''
}

async function commitRename(id: string): Promise<void> {
  const title = draftTitle.value.trim()
  if (!title) {
    cancelRename()
    return
  }
  await renameSession(id, title)
  cancelRename()
}

function onSignOut(): void {
  clearConversations()
  void signOut()
}
</script>

<template>
  <!-- 未登录：仅登录面（不套后台框架，避免展示空侧栏） -->
  <LoginView v-if="!canChat" />

  <!-- 已登录：RuoYi 三段式后台（顶栏 + 侧边栏 + 内容区） -->
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
        <div
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'chat' }"
          @click="activeView = 'chat'"
        >
          对话
        </div>
        <div
          v-if="showRoleGate"
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'role' }"
          @click="activeView = 'role'"
        >
          角色与能力
        </div>
        <div
          v-if="showKb"
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'kb' }"
          @click="activeView = 'kb'"
        >
          知识库
        </div>
        <div
          v-if="showKbAdmin"
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'kb-admin' }"
          @click="activeView = 'kb-admin'"
        >
          知识库管理
        </div>
        <div
          v-if="showDatasource"
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'datasource' }"
          @click="activeView = 'datasource'"
        >
          数据源
        </div>
        <div
          v-if="showHealth"
          class="ry-menu-item"
          :class="{ 'is-active': activeView === 'health' }"
          @click="activeView = 'health'"
        >
          平台健康
        </div>
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

      <!-- 对话页 = 主流 chat 三栏：左会话侧栏 / 中连续消息流+输入 / 右可核抽屉 -->
      <div
        v-if="chatShown"
        class="chat-shell"
      >
        <!-- 左：会话侧栏（新建 / 切换 / 删除，当前高亮，刷新后恢复） -->
        <aside class="chat-shell__sidebar ry-card">
          <div class="chat-shell__side-head">
            <h2 id="hSessions">
              会话
              <span class="count-badge">{{ sessionList.length }}</span>
            </h2>
            <button
              type="button"
              class="ry-btn ry-btn--primary"
              :aria-disabled="conversationsBusy"
              @click="newSession"
            >
              {{ conversationsBusy ? '…' : '+ 新建' }}
            </button>
          </div>
          <p
            v-if="conversationsNotice"
            class="banner"
          >
            <strong>{{ conversationsNotice }}</strong>
          </p>
          <ul class="session-list">
            <li
              v-for="s in sessionList"
              :key="s.session_id"
              class="session-list__item"
              :class="{ 'is-active': s.session_id === activeSessionId }"
            >
              <template v-if="editingId === s.session_id">
                <input
                  v-model="draftTitle"
                  class="ry-input session-list__edit"
                  type="text"
                  maxlength="200"
                  :aria-label="`修改会话标题 ${s.title}`"
                  @keydown.enter="commitRename(s.session_id)"
                  @keydown.esc="cancelRename"
                >
                <button
                  type="button"
                  class="ry-btn ry-btn--text session-list__edit-ok"
                  :aria-label="`保存标题 ${s.title}`"
                  @click="commitRename(s.session_id)"
                >
                  ✓
                </button>
                <button
                  type="button"
                  class="ry-btn ry-btn--text session-list__edit-cancel"
                  :aria-label="'取消修改标题'"
                  @click="cancelRename"
                >
                  ✕
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="ry-btn ry-btn--text session-list__pick"
                  :aria-current="s.session_id === activeSessionId ? 'true' : undefined"
                  @click="selectSession(s.session_id)"
                >
                  {{ s.title || s.session_id }}
                </button>
                <button
                  type="button"
                  class="ry-btn ry-btn--text session-list__rename"
                  :aria-label="`修改标题 ${s.title}`"
                  @click="startRename(s)"
                >
                  ✎
                </button>
                <button
                  type="button"
                  class="ry-btn ry-btn--text session-list__del"
                  :aria-label="`删除会话 ${s.title}`"
                  @click="removeSession(s.session_id)"
                >
                  ×
                </button>
              </template>
            </li>
          </ul>
          <p
            v-if="!sessionList.length"
            class="hint"
          >
            还没有会话。直接提问会自动建一个。
          </p>
        </aside>

        <!-- 中：连续消息流（历史 + 本轮同一条流）+ 底部输入 -->
        <section class="chat-shell__main ry-card">
          <ChatStream />
          <p
            v-if="busy || eventCount > 0"
            class="hint chat-shell__trace"
          >
            {{ traceNote }}
          </p>
          <form
            class="composer chat-shell__composer"
            @submit.prevent="submit"
          >
            <input
              v-model="question"
              class="ry-input"
              type="text"
              placeholder="输入问题，Enter 发送…"
              autocomplete="off"
              aria-label="问题"
            >
            <div class="composer__row">
              <label class="o-head-sm">
                知识范围
                <select
                  v-model="knowledgeScope"
                  class="ry-input"
                  aria-label="知识范围（检索收窄到所选知识库）"
                >
                  <option value="">
                    全部知识库
                  </option>
                  <option
                    v-for="kb in knowledgeBases"
                    :key="kb.knowledge_id"
                    :value="kb.knowledge_id"
                  >
                    {{ kb.knowledge_id }}（{{ kb.doc_count }} 篇）
                  </option>
                </select>
              </label>
              <button
                type="submit"
                class="ry-btn ry-btn--primary"
                :aria-disabled="!canSubmit"
              >
                {{ busy ? '等待 done…' : '发送' }}
              </button>
              <span
                v-if="submitHint !== ''"
                class="hint"
              >{{ submitHint }}</span>
            </div>
            <p
              v-if="knowledgeBasesNotice !== '' || knowledgeBases.length === 0"
              class="hint"
            >
              {{ knowledgeBasesNotice !== ''
                ? `知识库清单未取到：${knowledgeBasesNotice}（不影响提问，检索仍覆盖全部知识库）`
                : '服务端暂无已登记知识库；在知识库页上传并填写知识库 ID 后，这里会出现候选项。' }}
            </p>
          </form>
        </section>

        <!-- 右：可核对抽屉（依据 + 时间线，默认收起，展开看细节） -->
        <aside class="chat-shell__inspector">
          <details class="ry-card">
            <summary>
              <span class="o-head-sm">依据列表</span>
              <span class="count-badge">{{ evidence.length }}</span>
            </summary>
            <EvidenceList />
          </details>
          <details class="ry-card">
            <summary>
              <span class="o-head-sm">事件时间线</span>
              <span class="count-badge">{{ eventCount }}</span>
            </summary>
            <Timeline />
          </details>
        </aside>
      </div>

      <RoleGate v-else-if="activeView === 'role'" />

      <KbUpload v-else-if="activeView === 'kb'" />

      <KnowledgeBaseAdmin v-else-if="activeView === 'kb-admin'" />

      <DatasourceConfig v-else-if="activeView === 'datasource'" />

      <HealthView v-else-if="activeView === 'health'" />

      <Legend v-if="chatShown" />
    </main>
  </div>
</template>
