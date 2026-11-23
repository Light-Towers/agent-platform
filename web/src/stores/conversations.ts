/* ============================================================================
 * conversations.ts — 多会话窗口状态（模块级 composable，与 session.ts 同形态）
 *
 * 职责：会话目录（列表/当前/新建/切换/删除）+ 当前会话的历史消息回填。
 * 依赖方向单向：本件在动作内 useSessionStore() 读令牌与 resetRound，session.ts 不 import 本件；
 * App.vue 不再中转 currentSessionId。
 *
 * 存储：无本地存储（2026-11-17 按「服务端权威」统一去掉）——会话列表、历史消息、
 * 当前选中态全部以服务端为准：刷新后 loadSessions 默认选 last_active 最近的一条，
 * 而提问/切换会 touch last_active，所以「最近活跃」就是用户上次用的那个。换设备一致。
 * ==========================================================================*/
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  createSession,
  deleteSession,
  getHistory,
  listSessions,
  updateSessionTitle,
  type ChatHistoryItem,
  type SessionInfo,
} from '../api/sessions.ts'
import { useSessionStore } from './session.ts'


export const useConversationsStore = defineStore('conversations', () => {
const sessions = ref<SessionInfo[]>([])
const currentId = ref<string>('')
const history = ref<ChatHistoryItem[]>([])
const loading = ref(false)
const notice = ref('')

const sessionList = computed<readonly SessionInfo[]>(() => sessions.value)
const activeSessionId = computed(() => currentId.value)
const chatHistory = computed<readonly ChatHistoryItem[]>(() => history.value)
const conversationsBusy = computed(() => loading.value)
const conversationsNotice = computed(() => notice.value)

/** 拉取会话列表；若当前选中已不在列表（被删/越权）则清掉。 */
async function loadSessions(): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    sessions.value = await listSessions(useSessionStore().authToken)
    if (currentId.value && !sessions.value.some((s) => s.session_id === currentId.value)) {
      currentId.value = ''
      history.value = []
    }
    // 默认选最近活跃的一条（服务端按 last_active_at 降序返回第一条）
    if (!currentId.value && sessions.value.length) {
      currentId.value = sessions.value[0]?.session_id ?? ''
      await loadHistory()
    }
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

/** 新建会话并选中（纯空会话，title 用时间戳文案）。 */
async function newSession(): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    const created = await createSession(
      useSessionStore().authToken, `新会话 ${new Date().toLocaleString()}`, 'default',
    )
    sessions.value = [created, ...sessions.value]
    await selectSession(created.session_id)
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

/** 切换会话：更新选中态并回填该会话的历史消息。 */
async function selectSession(id: string): Promise<void> {
  if (id === currentId.value && history.value.length) return
  useSessionStore().resetRound()
  currentId.value = id
  await loadHistory()
}

/** 手动改会话标题；成功用服务端返回值回填（拿到 title_source=manual），失败给出提示。 */
async function renameSession(id: string, title: string): Promise<void> {
  const trimmed = title.trim()
  if (!trimmed) return
  if (!sessions.value.some((s) => s.session_id === id)) return
  notice.value = ''
  try {
    const updated = await updateSessionTitle(useSessionStore().authToken, id, trimmed)
    sessions.value = sessions.value.map((s) => s.session_id === id ? updated : s)
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
  }
}

/** 删除会话；删的是当前会话则清空选中与历史并重选最近一条。 */
async function removeSession(id: string): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    await deleteSession(useSessionStore().authToken, id)
    sessions.value = sessions.value.filter((s) => s.session_id !== id)
    if (id === currentId.value) {
      currentId.value = ''
      history.value = []
      const next = sessions.value[0]
      if (next) await selectSession(next.session_id)
    }
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

/** 回填当前会话历史（服务端权威原文）。 */
async function loadHistory(): Promise<void> {
  if (!currentId.value) {
    history.value = []
    return
  }
  notice.value = ''
  try {
    history.value = await getHistory(useSessionStore().authToken, currentId.value)
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
    history.value = []
  }
}

/** R3：提问入口收口到会话目录 —— App.vue 不再中转 currentSessionId。
 * 没有当前会话时先自动建一个，确保每轮问答都归属某个会话窗口；随后直接调会话层的 ask。 */
async function askCurrent(fetchImpl?: typeof fetch): Promise<void> {
  if (!currentId.value) await newSession()
  await useSessionStore().ask(fetchImpl, currentId.value || undefined)
}

/** 登出/换账号时清空会话态（当前 id 也清，避免把上一人的选中态带给下一人）。 */
function clearConversations(): void {
  sessions.value = []
  history.value = []
  notice.value = ''
  currentId.value = ''
}

  return {
    sessionList,
    activeSessionId,
    chatHistory,
    conversationsBusy,
    conversationsNotice,
    loadSessions,
    newSession,
    selectSession,
    renameSession,
    removeSession,
    loadHistory,
    clearConversations,
    askCurrent,
  }
})
