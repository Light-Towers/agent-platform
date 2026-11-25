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
import { useSessionStore } from '../stores/session.ts'
import { stripHeadingMarks } from '../utils/kbText.ts'

/**
 * /kb/* 的 401 统一出口（2026-11-16）。
 * 原来三个端点各自把服务端报文甩到屏上（`IDENTITY_TOKEN_INVALID` + `Signature has expired`），
 * 用户既不知道会话已失效也不知道下一步做什么；而 401 掉登录态的逻辑只在 SSE 那条路径里。
 * ⇒ 这里按状态码分流：401 掉态 + 一句可行动提示；其它状态码保留原报文给管理员排障。
 * ⚠ 依赖方向：`kb.ts` 是 API 层、import 会话层只取这一个纯函数；会话层不反过来 import kb.ts，
 *   没有循环依赖（与 `App.vue` 直接读 session 同一条单向数据流）。
 */
/** 429 是限流不是任务失败：任务仍在后台跑，交给轮询层退避重试，不当错误甩给用户。 */
export class KbRateLimitedError extends Error {
  readonly retryAfterMs: number
  constructor(retryAfterMs: number) {
    super('请求过于频繁')
    this.name = 'KbRateLimitedError'
    this.retryAfterMs = retryAfterMs
  }
}

async function failKb(action: string, resp: Response): Promise<never> {
  const text = await resp.text().catch(() => '')
  if (resp.status === 401) {
    useSessionStore().handleSessionExpired()
    throw new Error(`${action}失败：登录令牌已过期，请重新登录后再试`)
  }
  if (resp.status === 429) {
    const ra = Number(resp.headers.get('Retry-After'))
    throw new KbRateLimitedError(Number.isFinite(ra) && ra > 0 ? ra * 1000 : 10_000)
  }
  throw new Error(`${action}失败：HTTP ${resp.status} ${text.slice(0, 200)}`)
}

const KB_UPLOADS_PATH = '/kb/uploads'
const KB_STATUS_PATH = (taskId: string) => `/kb/status/${encodeURIComponent(taskId)}`
const KB_DOCUMENTS_PATH = '/kb/documents'
const KB_HISTORY_PATH = '/kb/history'

/** 切分配置（库级，存 kb_collections.chunk_config；前端读出来做只读展示/编辑）。 */
export interface KbChunkConfig {
  readonly split_strategy: 'title' | 'char' | 'line'
  readonly max_content_length: number
  readonly chunk_overlap_ratio: number
}

/** 切分配置默认值（与后端 chunk_config_utils.DEFAULT_CHUNK_CONFIG 对齐）。 */
export const DEFAULT_KB_CHUNK_CONFIG: KbChunkConfig = {
  split_strategy: 'title',
  max_content_length: 2000,
  chunk_overlap_ratio: 0.10,
}

/** 上传表单（刀 3 精简）：只保留知识库锚点。
 *  其余 metadata 由后端 Form 默认值登记；切分配置由 KS resolver 读库配置兜底，无需前端带。 */
export interface KbUploadForm {
  knowledgeId: string
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
  body.append('tenant_id', '')  // 服务端断言注入，前端发空串仅作校验占位
  body.append('knowledge_id', form.knowledgeId)
  // 切分参数不随上传提交：KS resolver 读 kb_collections.chunk_config 兜底（F-7），
  // 前端在库设置页改配置即可，上传页只读展示——避免"靠前端记得带"。
  const resp = await doFetch(KB_UPLOADS_PATH, { method: 'POST', headers, body, cache: 'no-store' })
  if (!resp.ok) await failKb('知识库上传', resp)
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
    /** 本次实际生效的切分配置（旧后端可能没有）。 */
    effective_config?: {
      split_strategy: string
      strategy_label: string
      max_content_length: number
      chunk_overlap: number
    }
    /** 切分过程告警（如超长表格已按字符切）；旧后端可能没有。 */
    warnings?: readonly string[]
    split?: KbSplitSummary
    structure_check?: KbStructureCheck
  }
}

/** 服务端持久化的上传历史一条（KS /history；换设备/清缓存/KS 重启仍在）。 */
export interface KbHistoryItem {
  task_id: string
  tenant_id: string
  filename: string
  knowledge_id: string
  status: string
  error: string
  summary: {
    split?: KbSplitSummary
    structure_check?: KbStructureCheck
  }
  uploaded_at?: string
  updated_at?: string
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
  if (!resp.ok) await failKb('知识库状态查询', resp)
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
  if (!resp.ok) await failKb('知识库列表查询', resp)
  return await resp.json()
}

/** 服务端上传历史（代理 KS /history；含切块读数，服务端权威，不依赖本机存储）。 */
export async function getKbHistory(
  token: string,
  fetchImpl?: typeof fetch,
): Promise<KbHistoryItem[]> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch(KB_HISTORY_PATH, { method: 'GET', headers, cache: 'no-store' })
  if (!resp.ok) await failKb('上传历史查询', resp)
  const data = await resp.json() as { items?: KbHistoryItem[] }
  return Array.isArray(data.items) ? data.items : []
}

const KB_KNOWLEDGE_BASES_PATH = '/kb/knowledge-bases'

/** 知识库清单一条（P1 起代理 KS /collections 注册表）。 */
export interface KbKnowledgeBase {
  readonly knowledge_id: string
  readonly name?: string
  readonly owner?: string
  readonly doc_count: number
  /** 库状态：active | deleted（P1 kb_collections）；兼容旧聚合值的生命周期状态。 */
  readonly status: string
  readonly latest_updated_at: string
  /** 库级切分配置（刀 2 GET /collections 带出）；未配置时后端给 null。 */
  readonly chunk_config?: KbChunkConfig | null
}

/**
 * 知识库列表：上传页的知识库 ID 下拉、对话区「知识范围」选择器、管理页的共同数据源。
 */
export async function listKnowledgeBases(
  token: string,
  fetchImpl?: typeof fetch,
): Promise<KbKnowledgeBase[]> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch(KB_KNOWLEDGE_BASES_PATH, { method: 'GET', headers, cache: 'no-store' })
  if (!resp.ok) await failKb('知识库列表查询', resp)
  const data = await resp.json() as { knowledge_bases?: KbKnowledgeBase[] }
  return Array.isArray(data.knowledge_bases) ? data.knowledge_bases : []
}

/** 下线文档（软删除→REVOKED）：DELETE /kb/documents/{knowledge_id}?source_doc=...。
 *  传 source_doc 只下线该文档；不传则下线整库（旧行为兼容）。 */
export async function deleteKbDocument(
  knowledgeId: string,
  token: string,
  sourceDoc?: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const q = sourceDoc ? `?source_doc=${encodeURIComponent(sourceDoc)}` : ''
  const resp = await doFetch(`/kb/documents/${encodeURIComponent(knowledgeId)}${q}`,
    { method: 'DELETE', headers, cache: 'no-store' })
  if (!resp.ok) await failKb('文档下线', resp)
  return await resp.json()
}

/** 重新上线文档（REVOKED→PUBLISHED，恢复 RAG 召回）：POST /kb/documents/{id}/restore。 */
export async function restoreKbDocument(
  knowledgeId: string, sourceDoc: string, token: string, fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const q = `?source_doc=${encodeURIComponent(sourceDoc)}`
  const resp = await doFetch(`/kb/documents/${encodeURIComponent(knowledgeId)}/restore${q}`,
    { method: 'POST', headers: authHeaders(token), cache: 'no-store' })
  if (!resp.ok) await failKb('文档上线', resp)
  return await resp.json()
}

/** 真删除文档（物理删切片+登记，不可逆）：DELETE /kb/documents/{id}/purge。只应对已下线文档调用。 */
export async function purgeKbDocument(
  knowledgeId: string, sourceDoc: string, token: string, fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const q = `?source_doc=${encodeURIComponent(sourceDoc)}`
  const resp = await doFetch(`/kb/documents/${encodeURIComponent(knowledgeId)}/purge${q}`,
    { method: 'DELETE', headers: authHeaders(token), cache: 'no-store' })
  if (!resp.ok) await failKb('文档删除', resp)
  return await resp.json()
}

/** 知识库文档树（库→文档→切片）：数据源是 Milvus 实际切片，不是上传历史。 */
export interface KbTreeChunk {
  readonly part: number | null
  readonly title: string
  readonly parent_title: string
  /** 展示用标题：API 边界已剥掉行首 '#{1,6} '（KS 原文 title 字面带 '#'）。 */
  readonly titleDisplay: string
  readonly parentTitleDisplay: string
  readonly content: string
  readonly status: string
}
export interface KbTreeDoc {
  readonly source_doc: string
  readonly chunk_count: number
  readonly chunks: readonly KbTreeChunk[]
}
export interface KbTreeBase {
  readonly knowledge_id: string
  readonly doc_count: number
  readonly documents: readonly KbTreeDoc[]
}
export async function listDocumentTree(token: string, fetchImpl?: typeof fetch): Promise<KbTreeBase[]> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch('/kb/documents/tree', { method: 'GET', headers, cache: 'no-store' })
  if (!resp.ok) await failKb('文档树查询', resp)
  const data = await resp.json() as { knowledge_bases?: KbTreeBase[] }
  if (!Array.isArray(data.knowledge_bases)) return []
  // 单一归一化点（P3）：原始 title/content 保真留给检索，display 字段专供 UI，
  // 这样下游每个组件不必各自剥 '#'（历史上漏一处补一处）。
  return data.knowledge_bases.map((base) => ({
    ...base,
    documents: base.documents.map((doc) => ({
      ...doc,
      chunks: doc.chunks.map((chunk) => ({
        ...chunk,
        titleDisplay: stripHeadingMarks(chunk.title),
        parentTitleDisplay: stripHeadingMarks(chunk.parent_title),
      })),
    })),
  }))
}

/** 删除整个知识库（前置：库下无有效文档）：DELETE /kb/knowledge-bases/{knowledge_id}。 */
export async function deleteKbKnowledgeBase(
  knowledgeId: string,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  const resp = await doFetch(`/kb/knowledge-bases/${encodeURIComponent(knowledgeId)}`,
    { method: 'DELETE', headers, cache: 'no-store' })
  if (!resp.ok) await failKb('知识库删除', resp)
  return await resp.json()
}

/** 新建知识库：POST /kb/knowledge-bases。系统生成全局唯一 knowledge_id。 */
export async function createKbKnowledgeBase(
  name: string,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<{ knowledge_id: string; name: string }> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  headers.set('Content-Type', 'application/json')
  const resp = await doFetch('/kb/knowledge-bases', {
    method: 'POST', headers,
    body: JSON.stringify({ name }),
    cache: 'no-store',
  })
  if (!resp.ok) await failKb('知识库创建', resp)
  return await resp.json() as { knowledge_id: string; name: string }
}

/** 重命名知识库：PATCH /kb/knowledge-bases/{knowledge_id}。 */
export async function renameKbKnowledgeBase(
  knowledgeId: string,
  name: string,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  headers.set('Content-Type', 'application/json')
  const resp = await doFetch(`/kb/knowledge-bases/${encodeURIComponent(knowledgeId)}`, {
    method: 'PATCH', headers,
    body: JSON.stringify({ name }),
    cache: 'no-store',
  })
  if (!resp.ok) await failKb('知识库改名', resp)
  return await resp.json()
}

/** 更新库级切分配置：PATCH /kb/knowledge-bases/{id}（body 仅 chunk_config，后端校验范围）。 */
export async function updateKbChunkConfig(
  knowledgeId: string,
  config: KbChunkConfig,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<unknown> {
  const doFetch = fetchImpl ?? globalThis.fetch
  const headers = authHeaders(token)
  headers.set('Content-Type', 'application/json')
  const resp = await doFetch(`/kb/knowledge-bases/${encodeURIComponent(knowledgeId)}`, {
    method: 'PATCH', headers,
    body: JSON.stringify({ chunk_config: config }),
    cache: 'no-store',
  })
  if (!resp.ok) await failKb('切分配置保存', resp)
  return await resp.json()
}
