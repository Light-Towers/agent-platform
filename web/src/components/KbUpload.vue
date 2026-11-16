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
import { computed, onMounted, ref } from 'vue'

import { authToken } from '../stores/session'
import {
  uploadKbDocuments,
  getKbStatus,
  listKbDocuments,
  KbRateLimitedError,
  type KbUploadForm,
  type KbTaskStatus,
} from '../api/kb.ts'
import { DIALECT_OPTIONS } from '../api/datasources.ts'
import {
  loadUploads,
  addUpload,
  updateUploadStatus,
  type KbUploadRecord,
} from '../stores/kbHistory.ts'

/** 默认配置即"能跑"：DRAFT + PRIVATE + 勾语义识别；knowledge_id 提示管理员可填以便登记。 */
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
/** 上传历史（localStorage 恢复），刷新后仍在。 */
const uploads = ref<KbUploadRecord[]>([])
/** 后端按 knowledge_id 登记的文档列表（只作补充展示）。 */
const documents = ref<unknown>(null)

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
  if (files.value.length === 0) {
    errorText.value = '请先选择或拖入至少一个文档文件'
    return
  }
  busy.value = true
  try {
    const names = files.value.map((f) => f.name).join('、')
    const res = await uploadKbDocuments(files.value, form.value, authToken.value ?? '')
    taskIds.value = (res as { task_ids?: string[] }).task_ids ?? []
    const firstId = taskIds.value[0]
    if (firstId !== undefined) {
      // 先落一条初始记录，再轮询；这样即使中途刷新，也能在历史里看到并续查。
      addUpload(firstId, names, { code: 0, task_id: firstId, status: '', done_list: [], running_list: [], error: '', summary: {} })
      uploads.value = loadUploads()
      activeTaskId.value = firstId
      await poll(firstId)
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
    updateUploadStatus(taskId, next)
    uploads.value = loadUploads()
    if (next.status === 'completed' || next.status === 'failed') return
    await new Promise((resolve) => setTimeout(resolve, 4000))
  }
  errorText.value = '处理仍在进行中，可稍后刷新本页查看结果'
}

/** 点击历史项：切换当前查看的切块结果（不依赖 KS 进程是否还活着）。 */
function selectTask(record: KbUploadRecord): void {
  activeTaskId.value = record.taskId
  status.value = record.status
  taskIds.value = [record.taskId]
  errorText.value = ''
}

/** 刷新后恢复历史；对仍未终态的任务续轮询（KS 进程存活时查得到）。 */
async function restore(): Promise<void> {
  uploads.value = loadUploads()
  const unfinished = uploads.value.find((r) => r.status.status !== 'completed' && r.status.status !== 'failed')
  if (unfinished) {
    activeTaskId.value = unfinished.taskId
    status.value = unfinished.status
    taskIds.value = [unfinished.taskId]
    try {
      await poll(unfinished.taskId)
    } catch {
      // KS 重启后查不回：保留本地快照，不强报错误
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
        上传文档
      </h2>
      <p class="hint">
        拖入文件即可上传（PDF / Markdown / Word / PPT / Excel，单个不超过 100MB）。
        处理进度与切片结果会在下方直接给出。
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

      <div class="composer__row">
        <button
          type="button"
          class="ry-btn ry-btn--primary"
          :aria-disabled="busy || files.length === 0"
          @click="submit"
        >
          {{ busy ? '上传中…' : '上传' }}
        </button>
      </div>

      <p
        v-if="errorText"
        class="banner"
      >
        <strong>{{ errorText }}</strong>
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
            knowledge_id
            <input
              v-model="form.knowledgeId"
              class="ry-input"
              type="text"
              placeholder="留空则不登记到文档列表"
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
      v-if="uploads.length"
      class="ry-card"
      aria-labelledby="hHistory"
    >
      <h2 id="hHistory">
        上传历史
        <span class="count-badge">{{ uploads.length }} 条</span>
      </h2>
      <p class="hint">
        每次上传的结果都保存在本机浏览器，刷新或重进页面仍可查看；点击任一条切换下方切片结果。
      </p>
      <div class="kb-history">
        <button
          v-for="rec in uploads"
          :key="rec.taskId"
          type="button"
          class="kb-history__item"
          :class="{ 'is-active': rec.taskId === activeTaskId }"
          @click="selectTask(rec)"
        >
          <strong>{{ rec.filename }}</strong>
          <span class="hint">{{ new Date(rec.uploadedAt).toLocaleString() }}</span>
          <span class="count-badge">{{ rec.status.status === 'completed' ? '完成' : rec.status.status === 'failed' ? '失败' : '进行中' }}</span>
        </button>
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
          <span class="o-head-sm">已登记文档（服务端，按 knowledge_id）</span>
        </summary>
        <p class="hint">
          这里只列出上传时填了 knowledge_id 的文档；未填的上传记录在上面「上传历史」里。
        </p>
        <button
          type="button"
          class="ry-btn"
          @click="refreshDocuments"
        >
          刷新列表
        </button>
        <pre
          v-if="documents"
          class="hint"
        >{{ JSON.stringify(documents, null, 2) }}</pre>
      </details>
    </section>
  </div>
</template>
