/* ============================================================================
 * kb.ts — 知识库上传代理客户端（G2；方案 §4 D7 + 补记 9，后端 agent_server/kb_router.py）
 *
 * 三个端点都走 agent_server 代理（浏览器不直连 KS，D7）：
 *   · POST /kb/uploads          （multipart，13 Form 字段 + 多文件；feature kb.upload）
 *   · GET  /kb/status/{task_id} （进度轮询；feature kb.upload）
 *   · GET  /kb/documents        （登记文档列表；feature kb.upload）
 * 凭据头一律复用 auth.ts 的 applyCredentialHeaders（全仓唯一装配点）。
 * 多文件用 FormData，不手动设 Content-Type（让 fetch 带 boundary）。
 * ==========================================================================*/
import { applyCredentialHeaders } from './auth.ts'

const KB_UPLOADS_PATH = '/kb/uploads'
const KB_STATUS_PATH = (taskId: string) => `/kb/status/${encodeURIComponent(taskId)}`
const KB_DOCUMENTS_PATH = '/kb/documents'

/** 上传表单的随表单填的 metadata 字段（tenant_id 由服务端断言注入，前端发空串仅作校验占位）。 */
export interface KbUploadForm {
  scopeType: string
  tenantType: string
  effectiveFrom: string
  effectiveTo: string
  version: string
  authority: string
  status: string
  constraintKind: string
  enableItemNameRecognition: boolean
  knowledgeId: string
  exhibitionId: string
  venueId: string
  datasourceType: string
}

function authHeaders(token: string): Headers {
  const h = new Headers()
  applyCredentialHeaders(h, { token })
  return h
}

/** 多文件 + metadata 上传到 /kb/uploads（代理 KS /upload）。返回代理透传的 JSON（含 task_ids）。 */
export async function uploadKbDocuments(
  files: File[],
  form: KbUploadForm,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const body = new FormData()
  for (const f of files) body.append('files', f, f.name)
  body.append('tenant_id', '')
  body.append('scope_type', form.scopeType)
  body.append('tenant_type', form.tenantType)
  body.append('effective_from', form.effectiveFrom)
  body.append('effective_to', form.effectiveTo)
  body.append('version', form.version)
  body.append('authority', form.authority)
  body.append('status', form.status)
  body.append('constraint_kind', form.constraintKind)
  body.append('enable_item_name_recognition', form.enableItemNameRecognition ? 'true' : 'false')
  body.append('knowledge_id', form.knowledgeId)
  body.append('exhibition_id', form.exhibitionId)
  body.append('venue_id', form.venueId)
  body.append('datasource_type', form.datasourceType)
  const resp = await doFetch(KB_UPLOADS_PATH, { method: 'POST', headers, body, cache: 'no-store' })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`知识库上传失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  }
  return await resp.json()
}

/* ---- 结果可核对读数（KS /status 的附加字段；后端未给时整块为空对象）----
 * 为什么定义类型而不是继续 unknown：管理员要看的是「怎么切 / 语义有没有丢」，
 * 这些数字必须能被 TS 检查到字段名，否则前端一旦写错字段名会静默显示空。 */
export interface KbSplitPreview {
  part: number
  title: string
  chars: number
  head: string
}

export interface KbSplitSummary {
  md_lines: number
  chunk_count: number
  title_count: number
  first_title: string
  chunk_chars: number
  previews: readonly KbSplitPreview[]
}

export interface KbStructureCheck {
  md_headings: number
  chunk_headings: number
  md_code_blocks: number
  chunk_code_blocks: number
  md_table_rows: number
  chunk_table_rows: number
  md_chars: number
  chunk_chars: number
  char_coverage: number
}

export interface KbTaskStatus {
  code: number
  task_id: string
  /** pending/processing/completed/failed；刚上传、后台未启动时是空串。 */
  status: string
  done_list: readonly string[]
  running_list: readonly string[]
  /** 失败原因文本（后端失败时写，成功为空）。 */
  error: string
  /** 切分统计 + 语义结构对照；尚未切分或旧后端为空对象。 */
  summary: {
    split?: KbSplitSummary
    structure_check?: KbStructureCheck
  }
}

/** 轮询上传任务进度（代理 KS /status/{task_id}）。 */
export async function getKbStatus(
  taskId: string,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<KbTaskStatus> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch(KB_STATUS_PATH(taskId), { method: 'GET', headers, cache: 'no-store' })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`知识库状态查询失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  }
  return await resp.json() as KbTaskStatus
}

/** 登记文档列表（代理 KS /documents）。 */
export async function listKbDocuments(
  token: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch(KB_DOCUMENTS_PATH, { method: 'GET', headers, cache: 'no-store' })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`知识库列表查询失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
  }
  return await resp.json()
}
