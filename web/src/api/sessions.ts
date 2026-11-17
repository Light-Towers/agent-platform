/* ============================================================================
 * sessions.ts — 多会话目录客户端（agent_server/api/sessions_router.py + session_router.py）
 *
 * session_id 由服务端签发（uuid4 hex），前端只持有；本件四个端点：
 *   · GET    /sessions              列当前归属人的会话
 *   · POST   /sessions              签一个新会话（title/workspace_id）
 *   · PATCH  /sessions/{id}         手动改标题（写 title_source=manual，自动生成器不再覆盖）
 *   · DELETE /sessions/{id}         删一个会话（归属校验，非本人 404）
 *   · GET    /history?session_id=…  取某会话的历史对话原文（回填已存在的 thread）
 * 凭据头复用 auth.ts 的 applyCredentialHeaders（全仓唯一装配点），401 走统一掉态出口。
 * 路径写绝对路径（页面挂 /ui/，相对会被拼成 /ui/sessions，后端无此路由）。
 * ==========================================================================*/
import { applyCredentialHeaders } from './auth.ts'
import { handleSessionExpired } from '../stores/session.ts'

export interface SessionInfo {
  session_id: string
  title: string
  title_source?: 'default' | 'auto' | 'manual'
  workspace_id: string
  created_at?: string | null
  last_active_at?: string | null
}

export interface ChatHistoryItem {
  index: number
  role: string
  content: string
  id?: string | null
  created_at?: string | null
}

function headers(token: string): Headers {
  const h = new Headers()
  applyCredentialHeaders(h, { token })
  return h
}

async function readResp(resp: Response, action: string): Promise<Record<string, unknown>> {
  if (resp.status === 401) {
    handleSessionExpired()
    throw new Error(`${action}失败：登录令牌已过期，请重新登录后再试`)
  }
  const text = await resp.text().catch(() => '')
  if (!resp.ok) throw new Error(`${action}失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    return {}
  }
}

export async function listSessions(token: string, fetchImpl?: typeof fetch): Promise<SessionInfo[]> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch('/sessions', { method: 'GET', headers: headers(token), cache: 'no-store' })
  const data = await readResp(resp, '会话列表查询')
  return Array.isArray(data.sessions) ? data.sessions as SessionInfo[] : []
}

export async function createSession(
  token: string, title: string, workspaceId: string, fetchImpl?: typeof fetch,
): Promise<SessionInfo> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch('/sessions', {
    method: 'POST',
    headers: (() => { const h = headers(token); h.set('Content-Type', 'application/json'); return h })(),
    body: JSON.stringify({ title, workspace_id: workspaceId }),
    cache: 'no-store',
  })
  const data = await readResp(resp, '新建会话')
  if (typeof data.session_id !== 'string') throw new Error('新建会话失败：服务端未返回 session_id')
  return data as unknown as SessionInfo
}

export async function updateSessionTitle(
  token: string, sessionId: string, title: string, fetchImpl?: typeof fetch,
): Promise<SessionInfo> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    headers: (() => { const h = headers(token); h.set('Content-Type', 'application/json'); return h })(),
    body: JSON.stringify({ title }),
    cache: 'no-store',
  })
  const data = await readResp(resp, '修改会话标题')
  return data as unknown as SessionInfo
}

export async function deleteSession(token: string, sessionId: string, fetchImpl?: typeof fetch): Promise<void> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE', headers: headers(token), cache: 'no-store',
  })
  await readResp(resp, '删除会话')
}

export async function getHistory(
  token: string, sessionId: string, fetchImpl?: typeof fetch,
): Promise<ChatHistoryItem[]> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch(`/history?session_id=${encodeURIComponent(sessionId)}`, {
    method: 'GET', headers: headers(token), cache: 'no-store',
  })
  const data = await readResp(resp, '历史消息查询')
  return Array.isArray(data.items) ? data.items as ChatHistoryItem[] : []
}
