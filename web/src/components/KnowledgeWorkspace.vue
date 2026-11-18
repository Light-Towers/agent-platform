<!-- ============================================================================
 * KnowledgeWorkspace.vue — 知识库页容器（master-detail）
 * 左栏 KnowledgeBaseSidebar（库列表 + 新建/改名/删除），右栏 KbUpload（当前库文档 + 上传）。
 * 文档树（库→文档→切片）由本容器统一拉取，分发给两栏：左栏取 doc_count，右栏取文档列表。
 * 数据源是 Milvus 实际切片，不是上传历史。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { authToken } from '../stores/session'
import { listDocumentTree, type KbTreeBase, type KbTreeDoc } from '../api/kb.ts'
import KnowledgeBaseSidebar from './KnowledgeBaseSidebar.vue'
import KbUpload from './KbUpload.vue'

const selectedId = ref('')
const selectedName = ref('')
const treeBases = ref<readonly KbTreeBase[]>([])
const treeError = ref('')

/** 每个库的真实文档数（来自 Milvus source_doc 去重），左栏显示用。 */
const docCounts = computed(() => {
  const m = new Map<string, number>()
  for (const b of treeBases.value) m.set(b.knowledge_id, b.doc_count)
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
  }
}

function onSelect(kid: string, name: string): void {
  selectedId.value = kid
  selectedName.value = name
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
        :doc-counts="docCounts"
        @select="onSelect"
        @changed="refreshTree"
      />
    </aside>
    <main class="kb-workspace__main">
      <KbUpload
        v-if="selectedId"
        :key="selectedId"
        :selected-knowledge-id="selectedId"
        :selected-name="selectedName"
        :documents="currentDocs"
        @changed="refreshTree"
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
