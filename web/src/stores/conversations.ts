/* ============================================================================
 * conversations.ts — 多会话窗口状态（模块级 composable，与 session.ts 同形态）
 *
 * 职责：会话目录（列表/当前/新建/切换/删除）+ 当前会话的历史消息回填。
 * 依赖方向单向：本件 import session.ts 的 authToken（只读取令牌），session.ts 不 import 本件；
 * ask(sessionId) 由 App.vue 在提交时把 currentSessionId 传进去，避免两 store 互相引用。
 *
 * 存储：只把「当前会话 id」写 localStorage（ap.chat.session，非凭据，刷新恢复选中态）；
 * 会话列表与历史消息每次从服务端重载（服务端是归属权威，不缓存他处）。登出时清空。
 * ==========================================================================*/
import { computed, ref } from 'vue'

import {
  createSession,
  deleteSession,
  getHistory,
  listSessions,
  type ChatHistoryItem,
  type SessionInfo,
} from '../api/sessions.ts'
import { authToken } from './session.ts'
import { readUiState, writeUiState } from '../theme.ts'

const CURRENT_KEY = 'ap.chat.session'

const sessions = ref<SessionInfo[]>([])
const currentId = ref<string>(readCurrent())
const history = ref<ChatHistoryItem[]>([])
const loading = ref(false)
const notice = ref('')

function readCurrent(): string {
  return readUiState(CURRENT_KEY) ?? ''
}

function persistCurrent(): void {
  writeUiState(CURRENT_KEY, currentId.value || null)
}

export const sessionList = computed<readonly SessionInfo[]>(() => sessions.value)
export const activeSessionId = computed(() => currentId.value)
export const chatHistory = computed<readonly ChatHistoryItem[]>(() => history.value)
export const conversationsBusy = computed(() => loading.value)
export const conversationsNotice = computed(() => notice.value)

/** 拉取会话列表；若当前选中已不在列表（被删/越权）则清掉。 */
export async function loadSessions(): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    sessions.value = await listSessions(authToken.value)
    if (currentId.value && !sessions.value.some((s) => s.session_id === currentId.value)) {
      currentId.value = ''
      history.value = []
      persistCurrent()
    }
    // 从未选过但已有会话 → 默认选最近一条
    if (!currentId.value && sessions.value.length) {
      currentId.value = sessions.value[0]?.session_id ?? ''
      persistCurrent()
      await loadHistory()
    }
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

/** 新建会话并选中（纯空会话，title 用时间戳文案）。 */
export async function newSession(): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    const created = await createSession(
      authToken.value, `新会话 ${new Date().toLocaleString()}`, 'default',
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
export async function selectSession(id: string): Promise<void> {
  if (id === currentId.value && history.value.length) return
  currentId.value = id
  persistCurrent()
  await loadHistory()
}

/** 删除会话；删的是当前会话则清空选中与历史并重选最近一条。 */
export async function removeSession(id: string): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    await deleteSession(authToken.value, id)
    sessions.value = sessions.value.filter((s) => s.session_id !== id)
    if (id === currentId.value) {
      currentId.value = ''
      history.value = []
      persistCurrent()
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
export async function loadHistory(): Promise<void> {
  if (!currentId.value) {
    history.value = []
    return
  }
  notice.value = ''
  try {
    history.value = await getHistory(authToken.value, currentId.value)
  } catch (err) {
    notice.value = err instanceof Error ? err.message : String(err)
    history.value = []
  }
}

/** 登出/换账号时清空会话态（当前 id 也清，避免把上一人的选中态带给下一人）。 */
export function clearConversations(): void {
  sessions.value = []
  history.value = []
  notice.value = ''
  currentId.value = ''
  persistCurrent()
}
