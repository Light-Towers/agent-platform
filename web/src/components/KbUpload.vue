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
import { computed, ref, watch } from 'vue'

import { authToken } from '../stores/session'
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
import { DIALECT_OPTIONS } from '../api/datasources.ts'

const props = defineProps<{
  selectedKnowledgeId: string
  selectedName: string
  /** 当前选中库的文档列表（来自文档树；数据源是 Milvus 实际切片）。 */
  documents: readonly KbTreeDoc[]
}>()
const emit = defineEmits<{
  changed: []   // 上传/下线后通知父组件刷新文档树
}>()

/** 默认配置即"能跑"：DRAFT + PRIVATE；knowledge_id 由左栏选中的库提供。 */
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
/** 最近一次上传的处理结果（步骤 + 切片读数），仅上传后短暂展示，不作主视图。 */
const status = ref<KbTaskStatus | null>(null)
/** DOC_BACKEND=pgvector 时的同步成功读数（没有 KS 后台任务可轮询）。 */
const localIngestNote = ref('')
/** 当前展开查看切片的文档名（source_doc）。 */
const expandedDoc = ref('')
/** 正在下线的文档名（防重复点）。 */
const deleteBusy = ref('')
const deleteNotice = ref('')

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
    deleteNotice.value = ''
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
  if (!window.confirm(`确定下线文档「${sourceDoc}」？该文档将从对话检索中移除（软删除，数据保留，可重新发布恢复）。`)) return
  deleteBusy.value = sourceDoc
  deleteNotice.value = ''
  try {
    await deleteKbDocument(props.selectedKnowledgeId, authToken.value ?? '', sourceDoc)
    deleteNotice.value = `文档「${sourceDoc}」已下线：不再被 RAG 召回（数据保留，可恢复）。`
    if (expandedDoc.value === sourceDoc) expandedDoc.value = ''
    emit('changed')
  } catch (err) {
    deleteNotice.value = `文档下线失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    deleteBusy.value = ''
  }
}

/** 重新上线：REVOKED → PUBLISHED，恢复被 RAG 召回。 */
async function onRestoreDocument(sourceDoc: string): Promise<void> {
  if (deleteBusy.value) return
  deleteBusy.value = sourceDoc
  deleteNotice.value = ''
  try {
    await restoreKbDocument(props.selectedKnowledgeId, sourceDoc, authToken.value ?? '')
    deleteNotice.value = `文档「${sourceDoc}」已重新上线：可再次被对话检索召回。`
    emit('changed')
  } catch (err) {
    deleteNotice.value = `文档上线失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    deleteBusy.value = ''
  }
}

/** 真删除（不可逆）：物理删切片+登记，文档从列表消失。只对已下线文档可见。 */
async function onPurgeDocument(sourceDoc: string): Promise<void> {
  if (deleteBusy.value) return
  if (!window.confirm(`确定永久删除文档「${sourceDoc}」？此操作不可逆，文档将从知识库彻底移除。`)) return
  deleteBusy.value = sourceDoc
  deleteNotice.value = ''
  try {
    await purgeKbDocument(props.selectedKnowledgeId, sourceDoc, authToken.value ?? '')
    deleteNotice.value = `文档「${sourceDoc}」已永久删除。`
    if (expandedDoc.value === sourceDoc) expandedDoc.value = ''
    emit('changed')
  } catch (err) {
    deleteNotice.value = `文档删除失败：${err instanceof Error ? err.message : String(err)}`
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
    emit('changed')   // 刷新文档树（上传完成 → 新文档/新切片出现在列表）
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
const check = computed(() => status.value?.summary?.structure_check)
const failed = computed(() => status.value?.status === 'failed')
</script>

<template>
  <div class="col">
    <!-- ① 本库文档列表（三级结构第二层）：来自 Milvus 实际切片，不是上传历史 -->
    <section
      class="ry-card"
      aria-labelledby="hDocs"
    >
      <h2 id="hDocs">
        {{ selectedName }} 的文档
        <span class="count-badge">{{ documents.length }} 份 · {{ totalChunks }} 片</span>
      </h2>
      <p class="hint">
        这是当前知识库下实际存在的文档。点开一份可查看它的切片；下线文档后它将不再被对话检索（RAG）召回。
      </p>

      <p
        v-if="deleteNotice"
        class="banner"
        role="status"
      >
        <strong>{{ deleteNotice }}</strong>
      </p>

      <div
        v-if="documents.length"
        class="kb-history"
      >
        <div
          v-for="doc in documents"
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
                <strong>#{{ chunk.part }} {{ chunk.title || chunk.parent_title || '（无标题）' }}</strong>
                <span
                  v-if="chunk.status"
                  class="count-badge"
                >{{ chunk.status }}</span>
                <code class="t-name">{{ chunk.content.slice(0, 160) }}{{ chunk.content.length > 160 ? '…' : '' }}</code>
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
        v-if="failed && status?.error"
        class="banner"
      >
        <strong>处理失败：{{ status.error }}</strong>
      </p>

      <!-- 高级选项：默认收起，不占用上传者注意力 -->
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
