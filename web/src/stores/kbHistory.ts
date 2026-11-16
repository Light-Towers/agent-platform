/* ============================================================================
 * kbHistory.ts — 知识库上传历史（浏览器本地持久化）
 *
 * 为什么需要这一层：KS 的 /documents 只登记填了 knowledge_id 的上传，而默认上传
 * 留空 ⇒ 那份文档根本不在后端列表里；且 /status/{task_id} 的结果存在 KS 进程内存，
 * 进程重启即失。用户要的是「刷新后还能看到上传过什么、怎么切的」，这一层用
 * localStorage 存每次上传的 task_id + 文件名 + 完整结果快照，刷新后原样恢复。
 *
 * 边界：
 *   · 只存元数据与统计读数，不存文档正文（切片预览已由后端截断，量小）；
 *   · 只保留最近 MAX 条，防止 localStorage 无限增长；
 *   · 存储读写异常一律降级为空/无操作，不让持久化问题影响上传主流程。
 * ==========================================================================*/
import type { KbTaskStatus } from '../api/kb.ts'
import { readUiState, writeUiState } from '../theme.ts'

const KEY = 'ap.kb.uploads'
const MAX = 30

export interface KbUploadRecord {
  taskId: string
  filename: string
  uploadedAt: string
  status: KbTaskStatus
}

function isRecord(v: unknown): v is KbUploadRecord {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Partial<KbUploadRecord>
  return typeof r.taskId === 'string' && typeof r.filename === 'string' && typeof r.status === 'object'
}

export function loadUploads(): KbUploadRecord[] {
  try {
    const raw = readUiState(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isRecord) : []
  } catch {
    return []
  }
}

function saveUploads(records: readonly KbUploadRecord[]): void {
  writeUiState(KEY, JSON.stringify(records.slice(0, MAX)))
}

/** 记录一次新上传（同名任务先去重，最新的排最前）。 */
export function addUpload(taskId: string, filename: string, status: KbTaskStatus): void {
  if (!taskId) return
  const records = loadUploads().filter((r) => r.taskId !== taskId)
  records.unshift({ taskId, filename, uploadedAt: new Date().toISOString(), status })
  saveUploads(records)
}

/** 轮询中每次拿到新读数就覆盖该任务快照（完成/失败后也保留最终态）。 */
export function updateUploadStatus(taskId: string, status: KbTaskStatus): void {
  const records = loadUploads()
  const idx = records.findIndex((r) => r.taskId === taskId)
  if (idx < 0) return
  const current = records[idx]
  if (!current) return
  records[idx] = { ...current, status }
  saveUploads(records)
}
