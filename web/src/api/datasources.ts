/* ============================================================================
 * datasources.ts — 问数数据源配置客户端（G3 刀 3；后端 agent_server/datasources_router.py）
 *
 * 端点走 agent_server 代理（浏览器不直连 nl2sql）：
 *   · GET    /datasources            （feature datasource.manage）
 *   · POST   /datasources            （新建；id + credential_ref 必填）
 *   · PATCH  /datasources/{id}       （改 label/dialect/scope_label/credential_ref/status）
 *   · POST   /datasources/{id}/default（设默认）
 * 凭据头一律复用 auth.ts 的 applyCredentialHeaders（全仓唯一装配点）。
 * ⚠ credential_ref 只是 Secret 投影键名，前端绝不为口令开输入框（文档 N1）。
 * ==========================================================================*/
import { applyCredentialHeaders } from './auth.ts'
import { authToken } from '../stores/session.ts'

export interface Datasource {
  id: string
  label: string
  dialect: string
  scope_label: string
  credential_ref: string
  is_default: boolean
  status: string
  updated_by: string
  updated_at: string
}

/** 受支持的数据源类型（MySQL / Hive；后端仍兼容既有 postgres 默认源）。 */
export const DIALECT_OPTIONS: { value: string; label: string }[] = [
  { value: 'mysql', label: 'MySQL' },
  { value: 'hive', label: 'Hive' },
]

const LIST_PATH = '/datasources'

function authHeaders(): Headers {
  const h = new Headers({ 'Content-Type': 'application/json' })
  applyCredentialHeaders(h, { token: authToken.value })
  return h
}

async function readJson(path: string, fetchImpl?: typeof fetch): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch(path, { method: 'GET', headers: authHeaders(), cache: 'no-store' })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`数据源查询失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  }
  return await resp.json()
}

async function sendJson(
  method: string,
  path: string,
  body: unknown,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const resp = await doFetch(path, {
    method,
    headers: authHeaders(),
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`数据源写操作失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  }
  return await resp.json().catch(() => ({}))
}

export async function listDatasources(fetchImpl?: typeof fetch): Promise<Datasource[]> {
  return (await readJson(LIST_PATH, fetchImpl)) as Datasource[]
}

export async function createDatasource(
  input: Partial<Datasource>,
  fetchImpl?: typeof fetch,
): Promise<Datasource> {
  return (await sendJson('POST', LIST_PATH, input, fetchImpl)) as Datasource
}

export async function updateDatasource(
  id: string,
  patch: Partial<Datasource>,
  fetchImpl?: typeof fetch,
): Promise<Datasource> {
  return (await sendJson('PATCH', `${LIST_PATH}/${encodeURIComponent(id)}`, patch, fetchImpl)) as Datasource
}

export async function setDefaultDatasource(id: string, fetchImpl?: typeof fetch): Promise<void> {
  await sendJson('POST', `${LIST_PATH}/${encodeURIComponent(id)}/default`, {}, fetchImpl)
}
