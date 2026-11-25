<!-- ============================================================================
 * KbUpload.vue — 知识库右栏 detail（选中库的文档 + 上传）
 *
 * 三级结构（Dify/RAGFlow/Coze 同款）：左栏知识库 → 右栏**该库下的文档** → 点文档看**切片**。
 * 文档/切片数据来自 props.documents（父组件从 GET /kb/documents/tree 拉取，
 * 数据源是 Milvus 实际切片），不是「上传历史流水」。上传历史不再作为主视图。
 *
 * 数据来源纪律：
 *   · 文档列表 = Milvus 按 knowledge_id + source_doc 聚合；doc_count = 文档数（非切片数）；
 *   · 点文档展开该文档的切片（part / heading / content / status）；
 *   · 删文档按 source_doc 粒度软删除（REVOKED），删后不再被 RAG 召回；
 *   · 上传后 emit('changed') 让父组件刷新文档树（而非自己维护历史）。
 *
 * ⚠ 本件无 <style> 块；复用的类（.kb-history/.kb-previews/.kb-drop/.kb-steps 等）
 *   全在 base.css。浏览器不直连 KS：所有请求只打 agent_server 的 /kb/* 代理。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { storeToRefs } from 'pinia'
import { useSessionStore } from '../stores/session'
const sessionStore = useSessionStore()
const { authToken } = storeToRefs(sessionStore)

import { parseContentTokens } from '../stores/sseReducer.ts'
import { confirmDestructive } from '../utils/confirm.ts'
import AuthImage from './AuthImage.vue'
import MarkdownText from './MarkdownText.vue'
import {
  uploadKbDocuments,
  getKbStatus,
  deleteKbDocument,
  restoreKbDocument,
  purgeKbDocument,
  KbRateLimitedError,
  type KbUploadForm,
  type KbTaskStatus,
  type KbTreeDoc,
} from '../api/kb.ts'
import { DEFAULT_KB_CHUNK_CONFIG, type KbChunkConfig } from '../api/kb.ts'

const props = defineProps<{
  selectedKnowledgeId: string
  selectedName: string
  /** 当前选中库的文档列表（来自文档树；数据源是 Milvus 实际切片）。 */
  documents: readonly KbTreeDoc[]
  /** 当前库的切分配置（库设置页编辑；上传页只读展示）。 */
  chunkConfig?: KbChunkConfig | null
}>()
const emit = defineEmits<{
  changed: []   // 上传/下线后通知父组件刷新文档树
}>()

/** 乐观状态覆盖：Milvus 写入有可见性延迟，操作成功后立刻改本地状态让按钮即时切换，
 *  后端刷新回来后以真实数据为准（覆盖随文档从树里消失/重插自动失效）。 */
const statusOverride = ref<Record<string, string>>({})
function optimisticStatus(sourceDoc: string, status: string): void {
  statusOverride.value = { ...statusOverride.value, [sourceDoc]: status }
}
/** 展示用文档：用乐观状态覆盖 chunks[].status，驱动 isRevoked 的按钮显隐。 */
const displayDocs = computed(() => props.documents.map((doc) => {
  const ov = statusOverride.value[doc.source_doc]
  if (!ov) return doc
  return { ...doc, chunks: doc.chunks.map((c) => ({ ...c, status: ov })) }
}))

/** 上传表单（刀 3 精简）：只带 knowledge_id；切分配置由后端读库配置兜底。 */
const form = ref<KbUploadForm>({ knowledgeId: '' })

/** 展示用切分配置：后端未配置时用默认值标注（与后端 DEFAULT_CHUNK_CONFIG 对齐）。 */
const shownChunkConfig = computed<KbChunkConfig>(() =>
  props.chunkConfig ?? DEFAULT_KB_CHUNK_CONFIG
)
const STRATEGY_LABEL: Record<KbChunkConfig['split_strategy'], string> = {
  title: '按标题切分',
  char: '按字符数切分',
  line: '按行/表格切分',
}

/** 同名覆盖提示（F-5）：文件名去后缀 = source_doc，命中现有文档即提示将被覆盖。 */
const overwriteNames = computed<string[]>(() => {
  const existing = new Set(displayDocs.value.map((d) => d.source_doc))
  return files.value
    .map((f) => f.name.replace(/\.[^.]+$/, ''))  // 去后缀，与后端 file_title 同口径
    .filter((name) => existing.has(name))
})

const files = ref<File[]>([])
const busy = ref(false)
const dragOver = ref(false)
const errorText = ref('')
const taskIds = ref<string[]>([])
/** 最近一次上传的处理结果（步骤 + 切片读数），仅上传后短暂展示，不作主视图。 */
const status = ref<KbTaskStatus | null>(null)
/** DOC_BACKEND=pgvector 时的同步成功读数（没有 KS 后台任务可轮询）。 */
const localIngestNote = ref('')
/** 当前展开查看切片的文档名（source_doc）。 */
const expandedDoc = ref('')
/** 正在下线的文档名（防重复点）。 */
const deleteBusy = ref('')
/** 操作反馈：ok=true 成功（绿）/false 失败（红）——用户视角：成功别用失败色。 */
const deleteNotice = ref<{ text: string; ok: boolean }>({ text: '', ok: true })

function notice(text: string, ok: boolean): void {
  deleteNotice.value = { text, ok }
}

/** Milvus 写入可见性有延迟：操作后立即刷新会读到旧 status ⇒ 延迟再刷一次。 */
const pendingTimers: number[] = []
function refreshAfterWrite(): void {
  emit('changed')                    // 先即时刷新（乐观）
  // #12：记录定时器 id，组件销毁（切库）时清理，避免旧组件触发全局刷新
  pendingTimers.push(window.setTimeout(() => emit('changed'), 3000))
}
onUnmounted(() => { for (const t of pendingTimers) window.clearTimeout(t) })

const totalChunks = computed(() =>
  props.documents.reduce((sum, d) => sum + d.chunk_count, 0),
)

/** 左栏选中库变化时：同步上传表单的 knowledge_id，重置展开项与提示。 */
watch(
  () => props.selectedKnowledgeId,
  (kid) => {
    form.value.knowledgeId = kid || ''
    expandedDoc.value = ''
    errorText.value = ''
    notice('', true)
    statusOverride.value = {}  // 切换库时清掉乐观状态
  },
  { immediate: true },
)

/** 文档是否已全部下线（所有切片 status=REVOKED）——据此决定显示「上线/删除」还是「下线」。
 *  产品规则（用户拍板）：删除按钮只在已下线文档上出现，有效文档不能一步删除。 */
function isRevoked(doc: KbTreeDoc): boolean {
  return doc.chunks.length > 0 && doc.chunks.every((c) => c.status === 'REVOKED')
}

/* ---- 文档下线（按 source_doc 粒度软删除 → REVOKED，删后不再被 RAG 召回）---- */
async function onDeleteDocument(sourceDoc: string): Promise<void> {
  if (deleteBusy.value) return
  if (!confirmDestructive({
    action: '下线文档', target: sourceDoc,
    consequence: '该文档将从对话检索（RAG）中移除，数据保留。',
    reversible: true,
  })) return
  deleteBusy.value = sourceDoc
  notice('', true)
  try {
    await deleteKbDocument(props.selectedKnowledgeId, authToken.value ?? '', sourceDoc)
    notice(`文档「${sourceDoc}」已下线：不再被 RAG 召回（数据保留，可恢复）。`, true)
    if (expandedDoc.value === sourceDoc) expandedDoc.value = ''
    // 乐观更新：立刻把该文档标记为已下线，删除按钮马上出现，不等后端刷新
    optimisticStatus(sourceDoc, 'REVOKED')
    refreshAfterWrite()
  } catch (err) {
    notice(`文档下线失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    deleteBusy.value = ''
  }
}

/** 重新上线：REVOKED → PUBLISHED，恢复被 RAG 召回。 */
async function onRestoreDocument(sourceDoc: string): Promise<void> {
  if (deleteBusy.value) return
  deleteBusy.value = sourceDoc
  notice('', true)
  try {
    await restoreKbDocument(props.selectedKnowledgeId, sourceDoc, authToken.value ?? '')
    notice(`文档「${sourceDoc}」已重新上线：可再次被对话检索召回。`, true)
    // 乐观更新：立刻标记为 PUBLISHED，「上线/删除」按钮即时消失
    optimisticStatus(sourceDoc, 'PUBLISHED')
    refreshAfterWrite()
  } catch (err) {
    notice(`文档上线失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    deleteBusy.value = ''
  }
}

/** 真删除（不可逆）：物理删切片+登记，文档从列表消失。只对已下线文档可见。 */
async function onPurgeDocument(sourceDoc: string): Promise<void> {
  if (deleteBusy.value) return
  if (!confirmDestructive({
    action: '永久删除文档', target: sourceDoc,
    consequence: '该文档的切片与登记将被物理删除，从知识库彻底移除。',
    reversible: false,
  })) return
  deleteBusy.value = sourceDoc
  notice('', true)
  try {
    await purgeKbDocument(props.selectedKnowledgeId, sourceDoc, authToken.value ?? '')
    notice(`文档「${sourceDoc}」已永久删除。`, true)
    if (expandedDoc.value === sourceDoc) expandedDoc.value = ''
    emit('changed')  // 删除后文档从树消失，无需乐观状态
    pendingTimers.push(window.setTimeout(() => emit('changed'), 3000))
  } catch (err) {
    notice(`文档删除失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    deleteBusy.value = ''
  }
}

/** 点文档展开/收起切片。 */
function toggleDoc(sourceDoc: string): void {
  expandedDoc.value = expandedDoc.value === sourceDoc ? '' : sourceDoc
}

/* ---- 上传 ---- */
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
  if (form.value.knowledgeId.trim() === '') {
    errorText.value = '请先在左侧选择或新建一个知识库，再上传文档'
    return
  }
  busy.value = true
  try {
    const res = await uploadKbDocuments(files.value, form.value, authToken.value ?? '')
    taskIds.value = (res as { task_ids?: string[] }).task_ids ?? []
    if (taskIds.value.length === 0) {
      localIngestNote.value = '文档已写入本地文档向量库（pgvector 后端，无需后台处理），'
        + '已在当前知识库中登记；可直接在对话页向该知识库提问。'
    } else {
      const firstId = taskIds.value[0]
      if (firstId !== undefined) {
        status.value = { code: 0, task_id: firstId, status: 'processing', done_list: [], running_list: [], error: '', summary: {} }
        await poll(firstId)
      }
    }
    // #7：清掉乐观覆盖——同名文档重新上传后应按后端真实状态显示，不被旧 override 误标下线
    statusOverride.value = {}
    refreshAfterWrite()  // #5：上传也走即时+3s二次刷新（Milvus 写入可见性延迟）
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

/** 轮询到终态（成功/失败）。KS 限流 20 次/60s，间隔 4s + 429 退避。 */
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

/** 7 个逻辑步骤，按 done_list 里出现的中文名点亮（节点可跳过/乱序）。 */
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
/** 切片正文内嵌渲染：图片出现在正文哪个位置就显示在哪（不抽出来堆在底部）。 */
function chunkTokens(content: string) {
  return parseContentTokens(content)
}
/** 标题缺省时从正文首个 Markdown 标题推导，避免「（无标题）」而正文明明有标题。 */
function chunkTitle(chunk: { title?: string; parent_title?: string; content?: string }): string {
  const explicit = chunk.title || chunk.parent_title
  if (explicit?.trim()) return explicit
  const first = (chunk.content ?? '').match(/^#{1,6}\s+(.+)$/m)
  return first?.[1]?.trim() || '（无标题）'
}
const check = computed(() => status.value?.summary?.structure_check)
const effectiveConfig = computed(() => status.value?.summary?.effective_config)
const splitWarnings = computed(() => status.value?.summary?.warnings ?? [])
const failed = computed(() => status.value?.status === 'failed')
</script>

<template>
  <div class="col">
    <!-- ① 本库文档列表（三级结构第二层）：来自 Milvus 实际切片，不是上传历史 -->
    <section
      class="ry-card"
      aria-labelledby="hDocs"
    >
      <div class="composer__row">
        <h2 id="hDocs">
          {{ selectedName }} 的文档
          <span class="count-badge">{{ documents.length }} 份 · {{ totalChunks }} 片</span>
        </h2>
        <button
          type="button"
          class="ry-btn ry-btn--text"
          :aria-disabled="busy"
          @click="emit('changed')"
        >
          刷新
        </button>
      </div>
      <p class="hint">
        这是当前知识库下实际存在的文档。点开一份可查看它的切片；下线文档后它将不再被对话检索（RAG）召回。
      </p>

      <p
        v-if="deleteNotice.text"
        class="notice"
        :class="deleteNotice.ok ? 'notice--ok' : 'banner'"
        role="status"
      >
        <strong>{{ deleteNotice.text }}</strong>
      </p>

      <div
        v-if="documents.length"
        class="kb-history"
      >
        <div
          v-for="doc in displayDocs"
          :key="doc.source_doc"
          class="kb-history__item"
          :class="{
            'is-active': expandedDoc === doc.source_doc,
            'kb-history__item--revoked': isRevoked(doc),
          }"
        >
          <button
            type="button"
            class="ry-btn ry-btn--text kb-sidebar__pick"
            :aria-expanded="expandedDoc === doc.source_doc"
            @click="toggleDoc(doc.source_doc)"
          >
            <strong>{{ doc.source_doc }}</strong>
            <span class="hint">{{ doc.chunk_count }} 片 · {{ expandedDoc === doc.source_doc ? '收起切片' : '点击查看切片' }}</span>
          </button>
          <span
            v-if="isRevoked(doc)"
            class="ry-tag ry-tag--warning"
          >已下线</span>
          <!-- 有效文档：只有「下线」；已下线文档：显示「上线」+「删除」（删除只对已下线开放） -->
          <template v-if="isRevoked(doc)">
            <button
              type="button"
              class="ry-btn"
              :aria-disabled="deleteBusy === doc.source_doc"
              title="重新上线（恢复被 RAG 召回）"
              @click="onRestoreDocument(doc.source_doc)"
            >
              {{ deleteBusy === doc.source_doc ? '上线中…' : '上线' }}
            </button>
            <button
              type="button"
              class="ry-btn ry-btn--danger"
              :aria-disabled="deleteBusy === doc.source_doc"
              title="永久删除（不可逆）"
              @click="onPurgeDocument(doc.source_doc)"
            >
              {{ deleteBusy === doc.source_doc ? '删除中…' : '删除' }}
            </button>
          </template>
          <button
            v-else
            type="button"
            class="ry-btn"
            :aria-disabled="deleteBusy === doc.source_doc"
            title="下线该文档（软删除，可恢复）"
            @click="onDeleteDocument(doc.source_doc)"
          >
            {{ deleteBusy === doc.source_doc ? '下线中…' : '下线' }}
          </button>

          <!-- 三级结构第三层：点文档展开该文档的切片明细 -->
          <details
            v-if="expandedDoc === doc.source_doc"
            class="fold"
            open
          >
            <summary>
              <span class="o-head-sm">切片明细（{{ doc.chunk_count }} 片）</span>
            </summary>
            <ol class="kb-previews">
              <li
                v-for="chunk in doc.chunks"
                :key="`${chunk.part}-${chunk.title}`"
                class="hint"
              >
                <strong>#{{ chunk.part }} {{ chunkTitle(chunk) }}</strong>
                <span
                  v-if="chunk.status"
                  class="count-badge"
                >{{ chunk.status }}</span>
                <div class="kb-chunk-content">
                  <template
                    v-for="(token, ti) in chunkTokens(chunk.content)"
                    :key="ti"
                  >
                    <MarkdownText
                      v-if="token.kind === 'text'"
                      :text="token.text"
                      extended
                      class="kb-chunk-md"
                    />
                    <AuthImage
                      v-else
                      :url="token.url"
                      :alt="token.alt || '切片图片'"
                      img-class="kb-inline-img"
                    />
                  </template>
                </div>
              </li>
            </ol>
          </details>
        </div>
      </div>
      <p
        v-else
        class="hint"
      >
        当前知识库还没有文档。用下方上传区添加第一份文档。
      </p>
    </section>

    <!-- ② 上传者层：拖文件 → 一个按钮，零参数 -->
    <section
      class="ry-card"
      aria-labelledby="hKb"
    >
      <h2 id="hKb">
        上传文档<span v-if="selectedName"> · {{ selectedName }}</span>
      </h2>
      <p class="hint">
        拖入文件即可上传到当前选中的知识库（PDF / Markdown / Word / PPT / Excel，单个不超过 100MB）。
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

      <p
        v-if="overwriteNames.length"
        class="notice notice--ok"
        role="status"
      >
        <strong>将覆盖同名文档：{{ overwriteNames.join('、') }}</strong>（同名即视为同一文档，旧切片会被新内容替换）
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
        class="notice notice--ok"
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
        v-if="failed && status?.error"
        class="banner"
      >
        <strong>处理失败：{{ status.error }}</strong>
      </p>

      <!-- 切分设置：只读展示当前库配置（编辑在左侧栏库设置里） -->
      <div class="kb-required">
        <span class="o-head-sm">当前库切分规则</span>
        <p class="hint">
          {{ STRATEGY_LABEL[shownChunkConfig.split_strategy] }} · 每片 {{ shownChunkConfig.max_content_length }} 字 ·
          重叠 {{ Math.round(shownChunkConfig.chunk_overlap_ratio * 100) }}%
        </p>
        <p class="hint">
          要修改切法/大小/重叠，请在左侧选中库后点「设置」。改完重新上传同名文档即可按新规则覆盖旧切片。
        </p>
      </div>
    </section>

    <!-- ③ 最近一次上传处理读数（仅上传后展示，可核对切分/语义结构是否完整） -->
    <section
      v-if="status"
      class="ry-card"
      aria-labelledby="hResult"
    >
      <h2 id="hResult">
        最近一次上传处理
        <span class="count-badge">{{ status.status === 'completed' ? '完成' : status.status === 'failed' ? '失败' : status.status || '进行中' }}</span>
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
        v-if="effectiveConfig"
        class="hint"
      >
        本次按 <strong>{{ effectiveConfig.strategy_label }}</strong> · 每片 {{ effectiveConfig.max_content_length }} 字 ·
        重叠 {{ effectiveConfig.chunk_overlap }} 字执行
      </p>
      <p
        v-for="(w, i) in splitWarnings"
        :key="i"
        class="hint"
      >
        ⚠ {{ w }}
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
      </template>
      <template v-if="check">
        <p class="hint">
          标题 {{ check.md_headings }} → {{ check.chunk_headings }} ·
          代码块 {{ check.md_code_blocks }} → {{ check.chunk_code_blocks }} ·
          表格行 {{ check.md_table_rows }} → {{ check.chunk_table_rows }}
        </p>
        <p class="hint">
          字符覆盖率 {{ (check.char_coverage * 100).toFixed(1) }}%
          （切分不分片重叠、且会剥掉重复标题，低于 100% 属正常）
        </p>
      </template>
    </section>
  </div>
</template>
