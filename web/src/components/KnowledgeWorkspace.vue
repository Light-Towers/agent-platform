<!-- ============================================================================
 * KnowledgeWorkspace.vue — 知识库页容器（master-detail）
 * 左栏 KnowledgeBaseSidebar（库列表 + 新建/改名/删除），右栏 KbUpload（当前库文档上传/管理）。
 * 选中库后右栏才可用；未选库时引导选库或新建。
 * ==========================================================================-->
<script setup lang="ts">
import { ref } from 'vue'
import KnowledgeBaseSidebar from './KnowledgeBaseSidebar.vue'
import KbUpload from './KbUpload.vue'

const selectedId = ref('')
const selectedName = ref('')

function onSelect(kid: string, name: string): void {
  selectedId.value = kid
  selectedName.value = name
}

function onChanged(): void {
  // 库列表变了（新建/改名/删除）：若当前选中的库被删，清空选择
  // 由 Sidebar 的 changed 事件触发；这里不重新拉列表（Sidebar 自己管）
}
</script>

<template>
  <div class="kb-workspace">
    <aside class="kb-workspace__sidebar ry-card">
      <KnowledgeBaseSidebar
        @select="onSelect"
        @changed="onChanged"
      />
    </aside>
    <main class="kb-workspace__main">
      <KbUpload
        v-if="selectedId"
        :key="selectedId"
        :selected-knowledge-id="selectedId"
        :selected-name="selectedName"
      />
      <section
        v-else
        class="ry-card"
      >
        <h2 class="o-head-sm">
          知识库
        </h2>
        <p class="hint">
          请先在左侧选择或新建一个知识库，然后即可上传文档、查看处理结果与下线文档。
          下线后的文档将不再被对话检索（RAG）召回。
        </p>
      </section>
    </main>
  </div>
</template>
