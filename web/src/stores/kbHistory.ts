/* ============================================================================
 * kbHistory.ts — 知识库上传历史的**本地兜底缓存**（不是权威源）
 *
 * 权威源已从 2026-11-17 起改成服务端：KS 把每次上传的元数据 + 切块读数落 Mongo
 * collection kb_upload_history，前端经 GET /kb/history 拉取。换设备/清缓存/KS 重启都还在。
 *
 * 本层只剩一个职责：**服务端暂时不可达时的兜底显示**——把最近一次成功拉到的历史快照
 * 存在浏览器（经白名单件 theme.ts 的 readUiState/writeUiState，不新增 localStorage 写者）。
 * 联网正常时服务端数据会覆盖这里，缓存自动失效更新。
 *
 * 边界：只存元数据与统计读数，不存文档正文；只留最近 MAX 条；读写异常静默降级。
 * ==========================================================================*/
import type { KbHistoryItem } from '../api/kb.ts'
import { readUiState, writeUiState } from '../theme.ts'

const KEY = 'ap.kb.uploads'
const MAX = 30

function isItem(v: unknown): v is KbHistoryItem {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Partial<KbHistoryItem>
  return typeof r.task_id === 'string' && typeof r.filename === 'string' && typeof r.status === 'string'
}

/** 读本地缓存（服务端拉不到时的兜底）。 */
export function loadCachedHistory(): KbHistoryItem[] {
  try {
    const raw = readUiState(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isItem) : []
  } catch {
    return []
  }
}

/** 用服务端权威列表覆盖本地缓存（联网正常时每次拉取后调用）。 */
export function saveCachedHistory(items: readonly KbHistoryItem[]): void {
  writeUiState(KEY, JSON.stringify(items.slice(0, MAX)))
}

/** 服务端还没登记（刚上传、后台管线未落库）时的即时占位，合入缓存。 */
export function cachePending(taskId: string, filename: string): KbHistoryItem[] {
  const items = loadCachedHistory().filter((r) => r.task_id !== taskId)
  items.unshift({
    task_id: taskId, tenant_id: '', filename, knowledge_id: '',
    status: 'processing', error: '', summary: {}, uploaded_at: new Date().toISOString(),
  })
  saveCachedHistory(items)
  return items
}
