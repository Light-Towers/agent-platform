<!-- ============================================================================
 * ChatView.vue — 对话视图（R4 从 App.vue 拆出，路由 `/chat/:sessionId?`）
 * 三栏：左会话目录 / 中消息流+提交 / 右可核抽屉（仅 admin 点开）。
 * URL 的 :sessionId 与 store 的 activeSessionId 双向同步：深链刷新直达、侧栏切换改地址栏。
 * 本件无 <style> 块，形状类落 base.css（理由见 ThemeToggle.vue 头注）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import ChatStream from './ChatStream.vue'
import EvidenceList from './EvidenceList.vue'
import Legend from './Legend.vue'
import Timeline from './Timeline.vue'
import { useConversationsStore } from '../stores/conversations.ts'
import { useSessionStore } from '../stores/session.ts'
import { listKnowledgeBases, type KbKnowledgeBase } from '../api/kb.ts'

const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const sessionStore = useSessionStore()
const {
  activeSessionId, conversationsBusy, conversationsNotice, sessionList,
} = storeToRefs(conversationsStore)
const {
  loadHistory, loadSessions, newSession, removeSession, renameSession, selectSession, askCurrent,
} = conversationsStore
const {
  authRole, authToken, busy, canSubmit, evidence, eventCount, knowledgeScope, question, traceNote, waiting,
} = storeToRefs(sessionStore)
const { resetRound } = sessionStore

/** 「查看过程」开关：仅 admin 可见，判据用服务端回读的角色码。 */
const canInspect = computed(() => authRole.value === 'admin')
const showInspector = ref(false)

/* 知识范围清单：本视图的局部 UI 态。拉取失败不拦提问，只退化成「全部知识库」一项。 */
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

/* 深链 → store：子组件的 mounted 先于父组件 App 的 mounted，故这里先落选中 id，
 * App 随后的 loadSessions 不会用「最近活跃」把深链覆盖掉。 */
watch(() => route.params.sessionId, async (sid) => {
  if (typeof sid === 'string' && sid !== '' && sid !== activeSessionId.value) {
    await selectSession(sid)
  }
}, { immediate: true })

/* store → 地址栏：侧栏切换与新建后把当前会话写进 URL，前进/后退因此可还原。 */
async function pickSession(id: string): Promise<void> {
  await selectSession(id)
  await router.push({ name: 'chat', params: { sessionId: id } })
}
async function createSession(): Promise<void> {
  await newSession()
  if (activeSessionId.value) await router.push({ name: 'chat', params: { sessionId: activeSessionId.value } })
}

onMounted(() => { void refreshKnowledgeBases() })

const submitHint = computed(() =>
  waiting.value
    ? '等待 done…（判定完成只看 done 帧，转圈不是完成信号）'
    : canSubmit.value ? '' : '输入为空时不能提交')

async function submit(): Promise<void> {
  await askCurrent()
  await loadHistory()
  resetRound()
  await loadSessions()
  if (activeSessionId.value && route.params.sessionId !== activeSessionId.value) {
    await router.replace({ name: 'chat', params: { sessionId: activeSessionId.value } })
  }
}

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
  if (!title) { cancelRename(); return }
  await renameSession(id, title)
  cancelRename()
}
</script>

<template>
  <div
    class="chat-shell"
    :class="{ 'chat-shell--no-inspector': !showInspector }"
  >
    <!-- 左：会话目录 -->
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
          @click="createSession"
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
              @click="pickSession(s.session_id)"
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

    <!-- 中：消息流 + 提交区 -->
    <section class="chat-shell__main ry-card">
      <ChatStream />
      <div
        v-if="canInspect"
        class="chat-shell__inspect-toggle"
      >
        <button
          type="button"
          class="ry-btn ry-btn--text"
          :aria-expanded="showInspector"
          @click="showInspector = !showInspector"
        >
          {{ showInspector ? '收起过程（依据/事件/图例）' : '查看过程（依据/事件/图例 · 仅管理员）' }}
        </button>
      </div>
      <p
        v-if="showInspector && (busy || eventCount > 0)"
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
                {{ kb.name || kb.knowledge_id }}（{{ kb.doc_count }} 篇）
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

    <!-- 右：可核对抽屉 -->
    <aside
      v-if="showInspector"
      class="chat-shell__inspector"
    >
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
  <Legend v-if="showInspector" />
</template>
