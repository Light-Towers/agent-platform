<!-- ============================================================================
 * KbUpload.vue — 知识库上传页（G2；方案 §4 D7 + 补记 9 / 2026-11-16 产品形态重做）
 *
 * 2026-11-16 重做的理由（用户原话）：
 *   「用户界面管理员只关心你文档怎么切，有没有丢失语义。而用户上传更不会关心具体参数。」
 * 原形态把 12 个后端 metadata 字段直铺成表单 ⇒ 上传者面对一堆看不懂的框，
 * 管理员却看不到任何切分/语义结果（那些数只在后端日志和本地 chunks.json 里）。
 * ⇒ 现在分三层：
 *   ① **上传者层**：拖文件/点选文件 → 一个「上传」按钮。零参数。
 *   ② **管理员层**：上传后展示**可核对读数**——7 步处理步骤（按 done_list 点亮，
 *      允许跳过/乱序）、切了几片（chunk_count 角标）、标题/代码块/表格结构对照、
 *      字符覆盖率、切片预览（前 8 片）。失败给具体原因（后端 error 字段）。
 *   ③ **高级选项**（默认收起）：原 12 个字段照旧保留（功能齐全，不删能力），
 *      只有需要精细控制的人才展开。
 *
 * 数据来源纪律：
 *   · 步骤条读 `/kb/status/{task_id}` 的 done_list/running_list（节点名中文映射在后端）；
 *   · 切片与语义读数读同一响应的 summary.split / summary.structure_check
 *     （后端在 node_document_split 里现算，纯统计、不改切分算法）；
 *   · **字符覆盖率 <100% 不等于语义丢失**：chunk_overlap=0 且切分器剥标题前缀，
 *     这里把三栏计数原样并列给人判断，不替人下"丢了/没丢"的结论。
 *
 * ⚠ 本件无 <style> 块（工程约束）；新用的几个类（.kb-drop/.kb-step/.kb-stat 等）
 *   全在 base.css，组件不自造形状。浏览器不直连 KS：所有请求只打 agent_server
 *   的 /kb/* 代理（kb_router.py），凭据头经 applyCredentialHeaders 唯一装配点。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { authToken } from '../stores/session'
import {
  uploadKbDocuments,
  getKbStatus,
  listKbDocuments,
  getKbHistory,
  deleteKbDocument,
  KbRateLimitedError,
  type KbUploadForm,
  type KbTaskStatus,
  type KbHistoryItem,
} from '../api/kb.ts'
import { DIALECT_OPTIONS } from '../api/datasources.ts'
import {
  loadCachedHistory,
  saveCachedHistory,
  cachePending,
} from '../stores/kbHistory.ts'

/** 右栏 detail：由父组件（知识库页）传入当前选中的知识库。 */
const props = defineProps<{
  selectedKnowledgeId: string
  selectedName: string
}>()

/** 默认配置即"能跑"：DRAFT + PRIVATE + 勾语义识别；knowledge_id 由左栏选中的库提供。 */
const form = ref<KbUploadForm>({
  scopeType: 'PRIVATE',
  tenantType: '',
  effectiveFrom: '',
  effectiveTo: '',
  version: '',
  authority: '',
  status: 'DRAFT',
  constraintKind: '',
  enableItemNameRecognition: true,
  knowledgeId: '',
  exhibitionId: '',
  venueId: '',
  datasourceType: 'mysql',
})

const files = ref<File[]>([])
const busy = ref(false)
const dragOver = ref(false)
const errorText = ref('')
const taskIds = ref<string[]>([])
/** 当前正在查看的结果；始终等于历史列表里 activeTaskId 那条的 status。 */
const status = ref<KbTaskStatus | null>(null)
const activeTaskId = ref('')
/** 上传历史（服务端 Mongo 权威，localStorage 仅断网兜底），刷新/换设备/重启仍在。 */
const uploads = ref<KbHistoryItem[]>([])
/** 历史来源标记：服务端权威 / 本地缓存兜底。 */
const historySource = ref<'server' | 'cache'>('cache')
/** 后端按 knowledge_id 登记的文档列表（只作补充展示）。 */
const documents = ref<unknown>(null)
/** 当前选中库的上传历史 / 登记文档（选中库时只显示该库，避免多库混在一起）。 */
const scopedUploads = computed(() =>
  props.selectedKnowledgeId
    ? uploads.value.filter((u) => u.knowledge_id === props.selectedKnowledgeId)
    : uploads.value,
)
const scopedDocuments = computed(() => {
  if (!props.selectedKnowledgeId || !Array.isArray(documents.value)) return documents.value
  return (documents.value as Array<{ knowledge_id?: string }>).filter(
    (d) => d.knowledge_id === props.selectedKnowledgeId,
  )
})
/** DOC_BACKEND=pgvector 时的成功读数：本地直写文档向量库，无 KS 后台任务可轮询。 */
const localIngestNote = ref('')

/** 左栏选中库变化时：同步上传表单的 knowledge_id，并刷新该库历史/文档。 */
watch(
  () => props.selectedKnowledgeId,
  (kid) => {
    form.value.knowledgeId = kid || ''
    if (kid) void loadHistory()
  },
  { immediate: true },
)

/* ---- 文档下线（软删除→REVOKED，删后不再被 RAG 召回）---- */
/** 正在删除的 knowledge_id（防重复点），与上传的 busy 分开。 */
const deleteBusy = ref('')
/** 删除操作的成功/失败提示（与上传的 errorText 分开，避免互相覆盖）。 */
const deleteNotice = ref('')

/** 下线单个文档：软删除，删后对话检索不再召回该文档。 */
async function onDeleteDocument(kid: string): Promise<void> {
  if (deleteBusy.value) return
  if (!window.confirm(`确定下线文档「${kid}」？该文档将从对话检索中移除（软删除，数据保留，可重新发布恢复）。`)) return
  deleteBusy.value = kid
  deleteNotice.value = ''
  try {
    await deleteKbDocument(kid, authToken.value ?? '')
    deleteNotice.value = `文档「${kid}」已下线：不再被 RAG 召回（数据保留，可恢复）。`
    await Promise.all([refreshDocuments(), loadHistory()])
  } catch (err) {
    deleteNotice.value = `文档下线失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    deleteBusy.value = ''
  }
}

/** 7 个逻辑步骤，按 done_list 里出现的**中文名**点亮（节点可跳过，不按数组下标画死）。 */
const STEP_DEFS = [
  { label: '上传', names: ['开始上传文件'] },
  { label: '检查文件', names: ['检查文件'] },
  { label: '解析', names: ['PDF转Markdown', 'Markdown图片处理'] },
  { label: '切分', names: ['文档切分'] },
  { label: '语义识别', names: ['主体名称识别'] },
  { label: '生成向量', names: ['向量生成'] },
  { label: '入库', names: ['导入向量库', '导入知识图谱', '处理完成'] },
] as const

const doneSet = computed(() => new Set(status.value?.done_list ?? []))
const runningSet = computed(() => new Set(status.value?.running_list ?? []))

function stepState(names: readonly string[]): 'done' | 'running' | 'pending' {
  if (names.some((n) => doneSet.value.has(n))) return 'done'
  if (names.some((n) => runningSet.value.has(n))) return 'running'
  return 'pending'
}

const split = computed(() => status.value?.summary?.split)
const check = computed(() => status.value?.summary?.structure_check)
const failed = computed(() => status.value?.status === 'failed')
const completed = computed(() => status.value?.status === 'completed')

function onPickFiles(e: Event): void {
  const input = e.target as HTMLInputElement
  files.value = input.files ? Array.from(input.files) : []
}

function onDrop(e: DragEvent): void {
  dragOver.value = false
  const dropped = e.dataTransfer?.files
  files.value = dropped ? Array.from(dropped) : []
}

function removeFile(index: number): void {
  files.value = files.value.filter((_f, i) => i !== index)
}

async function submit(): Promise<void> {
  errorText.value = ''
  status.value = null
  localIngestNote.value = ''
  if (files.value.length === 0) {
    errorText.value = '请先选择或拖入至少一个文档文件'
    return
  }
  // 知识库 ID 是登记/发布/检索的唯一锚点，由左栏选中的库自动带入；缺了就"传了也查不到"。
  if (form.value.knowledgeId.trim() === '') {
    errorText.value = '请先在左侧选择或新建一个知识库，再上传文档'
    return
  }
  busy.value = true
  try {
    const names = files.value.map((f) => f.name).join('、')
    const res = await uploadKbDocuments(files.value, form.value, authToken.value ?? '')
    taskIds.value = (res as { task_ids?: string[] }).task_ids ?? []
    if (taskIds.value.length === 0) {
      // DOC_BACKEND=pgvector：agent_server 本地直写文档向量库（同步完成），没有 KS 后台
      // 任务可轮询（/kb/status 对这批文档无意义），也不落 KS 的上传历史 —— 给一句如实的
      // 成功读数并跳过轮询，而不是让屏上停在「没有任务 ID」的空白里。
      localIngestNote.value = '文档已写入本地文档向量库（pgvector 后端，无需后台处理），'
        + '已在当前知识库中登记；可直接在对话页向该知识库提问。'
    } else {
      const firstId = taskIds.value[0]
      if (firstId !== undefined) {
        // 即时占位到缓存（后台管线要跑几分钟才落 Mongo）；权威历史在轮询完成后从服务端拉。
        uploads.value = cachePending(firstId, names)
        historySource.value = 'cache'
        activeTaskId.value = firstId
        status.value = { code: 0, task_id: firstId, status: 'processing', done_list: [], running_list: [], error: '', summary: {} }
        await poll(firstId)
      }
      await loadHistory()
    }
    await refreshDocuments()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

/**
 * 上传返回后轮询到终态（成功/失败）。
 * KS 侧限流 20 次/60s，2s 轮询 40s 就撞 429 ⇒ 间隔放宽到 4s（15 次/60s 留余量），
 * 且撞到 429 按 Retry-After 退避而非当成错误，否则大文档还没解析完就被误报失败。
 * 最多 90 次 × 4s ≈ 6 分钟，覆盖大 PDF 解析时长。
 */
async function poll(taskId: string): Promise<void> {
  for (let i = 0; i < 90; i += 1) {
    let next: KbTaskStatus
    try {
      next = await getKbStatus(taskId, authToken.value ?? '')
    } catch (err) {
      if (err instanceof KbRateLimitedError) {
        errorText.value = `任务仍在处理中（服务端限流，等待 ${Math.round(err.retryAfterMs / 1000)}s 后继续查询）…`
        await new Promise((resolve) => setTimeout(resolve, err.retryAfterMs))
        i -= 1
        continue
      }
      throw err
    }
    errorText.value = ''
    status.value = next
    if (next.status === 'completed' || next.status === 'failed') return
    await new Promise((resolve) => setTimeout(resolve, 4000))
  }
  errorText.value = '处理仍在进行中，可稍后刷新本页查看结果'
}

/** 历史条目 → 当前查看的切块读数（服务端 item 的 summary 即要展示的读数）。 */
function itemToStatus(item: KbHistoryItem): KbTaskStatus {
  return {
    code: 0, task_id: item.task_id, status: item.status,
    done_list: [], running_list: [], error: item.error, summary: item.summary,
  }
}

/** 点击历史项：切换当前查看的切块结果（读数来自服务端持久化的 summary）。 */
function selectTask(item: KbHistoryItem): void {
  activeTaskId.value = item.task_id
  status.value = itemToStatus(item)
  taskIds.value = [item.task_id]
  errorText.value = ''
}

/** 从服务端拉权威上传历史（Mongo，换设备/清缓存/重启仍在）；失败降级到本地缓存兜底。 */
async function loadHistory(): Promise<void> {
  try {
    const items = await getKbHistory(authToken.value ?? '')
    uploads.value = items
    saveCachedHistory(items)
    historySource.value = 'server'
  } catch {
    if (!uploads.value.length) uploads.value = loadCachedHistory()
    historySource.value = 'cache'
  }
}

/** 挂载恢复：先服务端拉权威历史；仍未终态的任务续轮询；补充拉登记文档列表。 */
async function restore(): Promise<void> {
  await loadHistory()
  const unfinished = uploads.value.find((r) => r.status !== 'completed' && r.status !== 'failed')
  if (unfinished) {
    activeTaskId.value = unfinished.task_id
    status.value = itemToStatus(unfinished)
    taskIds.value = [unfinished.task_id]
    try {
      await poll(unfinished.task_id)
      await loadHistory()
    } catch {
      // 续轮询失败：保留服务端快照，不强报错误
    }
  } else {
    const latest = uploads.value[0]
    if (latest) selectTask(latest)
  }
  await refreshDocuments()
}

onMounted(restore)

async function refreshDocuments(): Promise<void> {
  try {
    documents.value = await listKbDocuments(authToken.value ?? '')
  } catch (err) {
    // 登记列表是补充项，拉取失败不覆盖上传主流程的错误提示
    if (!errorText.value) errorText.value = err instanceof Error ? err.message : String(err)
  }
}
</script>

<template>
  <div class="col">
    <!-- ① 上传者层：拖文件 → 一个按钮，零参数 -->
    <section
      class="ry-card"
      aria-labelledby="hKb"
    >
      <h2 id="hKb">
        上传文档<span v-if="selectedName"> · {{ selectedName }}</span>
      </h2>
      <p class="hint">
        拖入文件即可上传到当前选中的知识库（PDF / Markdown / Word / PPT / Excel，单个不超过 100MB）。
        处理进度与切片结果会在下方给出；下线文档后它将不再被对话检索召回。
      </p>

      <label
        class="kb-drop"
        :class="{ 'is-over': dragOver }"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <span class="o-head-sm">{{ dragOver ? '松手即可加入' : '把文件拖到这里，或点击选择' }}</span>
        <input
          type="file"
          multiple
          aria-label="选择文档文件"
          @change="onPickFiles"
        >
      </label>

      <p
        v-if="files.length"
        class="hint"
      >
        已选 {{ files.length }} 个文件
        <button
          v-for="(f, i) in files"
          :key="`${f.name}-${i}`"
          type="button"
          class="ry-btn ry-btn--text"
          @click="removeFile(i)"
        >
          {{ f.name }} ×
        </button>
      </p>

      <div class="kb-required">
        <span class="o-head-sm">上传到知识库</span>
        <p
          v-if="selectedKnowledgeId"
          class="hint"
        >
          当前库：<strong>{{ selectedName }}</strong>
          <code class="t-name">{{ selectedKnowledgeId }}</code>
        </p>
        <p
          v-else
          class="banner"
        >
          <strong>请先在左侧选择或新建一个知识库，再上传文档。</strong>
        </p>
      </div>

      <div class="composer__row">
        <button
          type="button"
          class="ry-btn ry-btn--primary"
          :aria-disabled="busy || files.length === 0 || selectedKnowledgeId === ''"
          @click="submit"
        >
          {{ busy ? '上传中…' : '上传到当前知识库' }}
        </button>
      </div>

      <p
        v-if="localIngestNote"
        class="banner"
        role="status"
      >
        <strong>{{ localIngestNote }}</strong>
      </p>

      <p
        v-if="errorText"
        class="banner"
      >
        <strong>{{ errorText }}</strong>
      </p>
      <p
        v-if="deleteNotice"
        class="banner"
        role="status"
      >
        <strong>{{ deleteNotice }}</strong>
      </p>
      <p
        v-if="failed && status?.error"
        class="banner"
      >
        <strong>处理失败：{{ status.error }}</strong>
      </p>

      <!-- 高级选项：功能齐全但默认收起，不占用上传者注意力 -->
      <details class="fold">
        <summary>
          <span class="o-head-sm">高级选项（文档归属与处理开关，一般不用改）</span>
        </summary>
        <p class="hint">
          配置随每次上传提交；留空即按默认值处理。请求只发往
          <code class="t-name">/kb/uploads</code> 代理，浏览器不直连知识库服务。
        </p>
        <div class="kb-advanced">
          <label class="o-head-sm">
            scope_type
            <input
              v-model="form.scopeType"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            tenant_type
            <input
              v-model="form.tenantType"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            effective_from
            <input
              v-model="form.effectiveFrom"
              class="ry-input"
              type="text"
              placeholder="yyyy-MM-dd"
            >
          </label>
          <label class="o-head-sm">
            effective_to
            <input
              v-model="form.effectiveTo"
              class="ry-input"
              type="text"
              placeholder="yyyy-MM-dd"
            >
          </label>
          <label class="o-head-sm">
            version
            <input
              v-model="form.version"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            authority
            <input
              v-model="form.authority"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            status
            <input
              v-model="form.status"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            constraint_kind
            <input
              v-model="form.constraintKind"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            exhibition_id
            <input
              v-model="form.exhibitionId"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            venue_id
            <input
              v-model="form.venueId"
              class="ry-input"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            数据源类型
            <select
              v-model="form.datasourceType"
              class="ry-input"
              aria-label="数据源类型"
            >
              <option
                v-for="d in DIALECT_OPTIONS"
                :key="d.value"
                :value="d.value"
              >
                {{ d.label }}
              </option>
            </select>
          </label>
          <label class="o-head-sm kb-check">
            <input
              v-model="form.enableItemNameRecognition"
              type="checkbox"
            >
            启用主体名称识别
          </label>
        </div>
      </details>
    </section>

    <!-- ② 管理员层：历史任务切换 + 结果可核对（步骤 + 切片 + 语义结构） -->
    <section
      v-if="scopedUploads.length"
      class="ry-card"
      aria-labelledby="hHistory"
    >
      <h2 id="hHistory">
        上传历史
        <span class="count-badge">{{ scopedUploads.length }} 条</span>
      </h2>
      <p class="hint">
        {{ historySource === 'server'
          ? '历史保存在服务端，点击任一记录查看其切片结果；下线文档后不再被对话检索召回。'
          : '当前显示本机缓存（服务端暂不可达）；网络恢复后会自动切回服务端权威历史。' }}
      </p>
      <div class="kb-history">
        <div
          v-for="rec in scopedUploads"
          :key="rec.task_id"
          class="kb-history__item"
          :class="{ 'is-active': rec.task_id === activeTaskId }"
        >
          <button
            type="button"
            class="ry-btn ry-btn--text"
            @click="selectTask(rec)"
          >
            <strong>{{ rec.filename }}</strong>
            <span class="hint">{{ rec.uploaded_at ? new Date(rec.uploaded_at).toLocaleString() : '' }}</span>
            <span class="count-badge">{{ rec.status === 'completed' ? '完成' : rec.status === 'failed' ? '失败' : '进行中' }}</span>
          </button>
          <button
            v-if="rec.knowledge_id"
            type="button"
            class="ry-btn"
            :aria-disabled="deleteBusy === rec.knowledge_id"
            title="下线该知识库文档（软删除，删后不再被 RAG 召回）"
            @click="onDeleteDocument(rec.knowledge_id)"
          >
            {{ deleteBusy === rec.knowledge_id ? '下线中…' : '删除文档' }}
          </button>
        </div>
      </div>
    </section>

    <section
      v-if="status"
      class="ry-card"
      aria-labelledby="hResult"
    >
      <h2 id="hResult">
        处理结果
        <span class="count-badge">{{ completed ? '完成' : failed ? '失败' : status.status || '进行中' }}</span>
      </h2>

      <ol class="kb-steps">
        <li
          v-for="step in STEP_DEFS"
          :key="step.label"
          class="kb-step"
          :class="`is-${stepState(step.names)}`"
        >
          {{ step.label }}
        </li>
      </ol>

      <p
        v-if="taskIds.length"
        class="hint"
      >
        任务 ID：{{ taskIds.join('、') }}
      </p>
      <p
        v-if="form.knowledgeId.trim()"
        class="hint"
      >
        知识库 ID：<code class="t-name">{{ form.knowledgeId.trim() }}</code>
      </p>

      <template v-if="split">
        <h3 class="o-head-sm">
          文档怎么切
          <span class="count-badge">{{ split.chunk_count }} 片</span>
        </h3>
        <p class="hint">
          原稿 {{ split.md_lines }} 行 · 识别到 {{ split.title_count }} 个标题 ·
          首片「{{ split.first_title }}」· 切片正文共 {{ split.chunk_chars }} 字
        </p>
        <details class="fold">
          <summary>
            <span class="o-head-sm">查看切片预览（前 {{ split.previews.length }} 片）</span>
          </summary>
          <ol class="kb-previews">
            <li
              v-for="p in split.previews"
              :key="`${p.part}-${p.title}`"
              class="hint"
            >
              <strong>#{{ p.part }} {{ p.title }}</strong>（{{ p.chars }} 字）
              <code class="t-name">{{ p.head }}</code>
            </li>
          </ol>
        </details>
      </template>

      <template v-if="check">
        <h3 class="o-head-sm">
          语义结构对照
        </h3>
        <p class="hint">
          标题 {{ check.md_headings }} → {{ check.chunk_headings }} ·
          代码块 {{ check.md_code_blocks }} → {{ check.chunk_code_blocks }} ·
          表格行 {{ check.md_table_rows }} → {{ check.chunk_table_rows }}
        </p>
        <p class="hint">
          字符覆盖率 {{ (check.char_coverage * 100).toFixed(1) }}%
          （切分不分片重叠、且会剥掉重复标题，低于 100% 属正常，请对照上面的结构计数判断）
        </p>
      </template>

      <p
        v-if="!split && !failed"
        class="hint"
      >
        切片读数尚未产生（处理完成后这里会显示切了几片、语义结构是否完整）。
      </p>
    </section>

    <!-- ③ 后端登记的文档列表（knowledge_id 非空才会登记，作补充展示） -->
    <section class="ry-card">
      <details class="fold">
        <summary>
          <span class="o-head-sm">当前库登记文档（服务端原始数据）</span>
        </summary>
        <p class="hint">
          当前选中库的登记文档原始数据，供核对；下线文档后状态会变 REVOKED。
        </p>
        <button
          type="button"
          class="ry-btn"
          @click="refreshDocuments"
        >
          刷新列表
        </button>
        <pre
          v-if="scopedDocuments"
          class="hint"
        >{{ JSON.stringify(scopedDocuments, null, 2) }}</pre>
      </details>
    </section>
  </div>
</template>
