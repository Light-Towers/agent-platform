<!-- ============================================================================
 * KnowledgeWorkspace.vue — 知识库页容器（master-detail）
 * 左栏 KnowledgeBaseSidebar（库列表 + 新建/改名/删除），右栏 KbUpload（当前库文档 + 上传）。
 * 文档树（库→文档→切片）由本容器统一拉取，分发给两栏：左栏取 doc_count，右栏取文档列表。
 * 数据源是 Milvus 实际切片，不是上传历史。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { authToken } from '../stores/session'
import { listDocumentTree, type KbTreeBase, type KbTreeDoc, type KbChunkConfig } from '../api/kb.ts'
import KnowledgeBaseSidebar from './KnowledgeBaseSidebar.vue'
import KbUpload from './KbUpload.vue'

const emit = defineEmits<{
  /** 库被删除——父组件（App）可据此清理对话页知识范围下拉里已失效的选中值（#8）。 */
  'kb-deleted': [knowledgeId: string]
}>()

const selectedId = ref('')
const selectedName = ref('')
const treeBases = ref<readonly KbTreeBase[]>([])
const treeError = ref('')
/** 库级切分配置索引（库设置页保存后随刷新更新），传给右栏只读展示。 */
const chunkConfigById = ref<Map<string, KbChunkConfig>>(new Map())
const sidebarRef = ref<InstanceType<typeof KnowledgeBaseSidebar> | null>(null)

/** 有效文档数（status != REVOKED 的 distinct source_doc）——与后端删库守卫同源。
 *  #1：全下线后 doc_count=0 ⇒ 删库按钮可用（之前数全部含 REVOKED，永远删不掉库）。 */
function activeDocCount(base: KbTreeBase): number {
  const docs = new Set<string>()
  for (const doc of base.documents) {
    if (doc.chunks.some((c) => c.status !== 'REVOKED')) docs.add(doc.source_doc)
  }
  return docs.size
}
const docCounts = computed(() => {
  const m = new Map<string, number>()
  for (const b of treeBases.value) m.set(b.knowledge_id, activeDocCount(b))
  return m
})
/** 当前选中库的文档列表（点开看切片）。 */
const currentDocs = computed<readonly KbTreeDoc[]>(() =>
  treeBases.value.find((b) => b.knowledge_id === selectedId.value)?.documents ?? [],
)

async function refreshTree(): Promise<void> {
  try {
    treeBases.value = await listDocumentTree(authToken.value ?? '')
    treeError.value = ''
  } catch (err) {
    treeError.value = `文档树加载失败：${err instanceof Error ? err.message : String(err)}`
    treeBases.value = []  // #11：失败时清掉旧数据，不把过期读数当当前
  }
  // L-B：切分配置索引由 Sidebar.refresh() 经 @configs emit 上来（单一数据源，不重复请求）
}

/** Sidebar 经 @configs 抛上来的库配置索引（L-B：一次请求，配置与库列表同源） */
function onConfigs(map: Map<string, KbChunkConfig>): void {
  chunkConfigById.value = map
}

/** 统一刷新（P1 修类）：任何变更同时刷新 tree + Sidebar 的库列表快照。 */
async function refreshAll(): Promise<void> {
  await Promise.all([refreshTree(), sidebarRef.value?.refresh()])
}

function onSelect(kid: string, name: string): void {
  selectedId.value = kid
  selectedName.value = name
}

/** #3：改名当前库 → 同步右栏标题。 */
function onRenamed(kid: string, name: string): void {
  if (kid === selectedId.value) selectedName.value = name
  void refreshAll()
}

/** #2：删库 → 若删的是当前选中库，清空选中态，右栏回空态。 */
function onDeleted(kid: string): void {
  if (kid === selectedId.value) {
    selectedId.value = ''
    selectedName.value = ''
  }
  emit('kb-deleted', kid)
  void refreshAll()
}

onMounted(refreshTree)
</script>

<template>
  <div class="kb-workspace">
    <aside class="kb-workspace__sidebar ry-card">
      <p
        v-if="treeError"
        class="banner"
        role="status"
      >
        <strong>{{ treeError }}</strong>
      </p>
      <KnowledgeBaseSidebar
        ref="sidebarRef"
        :doc-counts="docCounts"
        :selected-id="selectedId"
        @select="onSelect"
        @changed="refreshAll"
        @renamed="onRenamed"
        @deleted="onDeleted"
        @configs="onConfigs"
      />
    </aside>
    <main class="kb-workspace__main">
      <KbUpload
        v-if="selectedId"
        :key="selectedId"
        :selected-knowledge-id="selectedId"
        :selected-name="selectedName"
        :documents="currentDocs"
        :chunk-config="chunkConfigById.get(selectedId) ?? null"
        @changed="refreshAll"
      />
      <section
        v-else
        class="ry-card kb-workspace__empty"
      >
        <h2 class="o-head-sm">
          知识库
        </h2>
        <p class="hint">
          请先在左侧选择或新建一个知识库，然后即可查看该库下的文档、上传新文档、点开文档查看切片。
          下线后的文档将不再被对话检索（RAG）召回。
        </p>
      </section>
    </main>
  </div>
</template>
