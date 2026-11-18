<!-- ============================================================================
 * KnowledgeBaseSidebar.vue — 知识库页左栏（master）：库列表 + 新建/重命名/删除 + 选库
 * 选中库通过 select 事件把 knowledge_id 抛给父组件（KbUpload 右栏）。
 * 无 <style> 块，形状复用 base.css 既有类。
 * ==========================================================================-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { authToken } from '../stores/session'
import {
  listKnowledgeBases,
  createKbKnowledgeBase,
  renameKbKnowledgeBase,
  deleteKbKnowledgeBase,
  type KbKnowledgeBase,
} from '../api/kb.ts'

const emit = defineEmits<{
  select: [knowledgeId: string, name: string]
  changed: []   // 库列表变化（新建/改名/删除）后通知父组件刷新
}>()

const bases = ref<KbKnowledgeBase[]>([])
const loading = ref(false)
const notice = ref('')
const creating = ref(false)
const newName = ref('')
const editingId = ref('')
const editName = ref('')
const busy = ref('')

async function refresh(): Promise<void> {
  loading.value = true
  try {
    bases.value = await listKnowledgeBases(authToken.value ?? '')
  } catch (err) {
    notice.value = `加载失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    loading.value = false
  }
}

function choose(kb: KbKnowledgeBase): void {
  emit('select', kb.knowledge_id, kb.name || kb.knowledge_id)
}

async function onCreate(): Promise<void> {
  const name = newName.value.trim()
  if (!name || busy.value) return
  busy.value = 'create'
  notice.value = ''
  try {
    const created = await createKbKnowledgeBase(name, authToken.value ?? '')
    notice.value = `已创建「${created.name}」`
    newName.value = ''
    creating.value = false
    await refresh()
    emit('changed')
    emit('select', created.knowledge_id, created.name)
  } catch (err) {
    notice.value = `创建失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busy.value = ''
  }
}

function startEdit(kb: KbKnowledgeBase): void {
  editingId.value = kb.knowledge_id
  editName.value = kb.name || kb.knowledge_id
}

async function onRename(kb: KbKnowledgeBase): Promise<void> {
  const name = editName.value.trim()
  if (!name || busy.value) return
  busy.value = kb.knowledge_id
  try {
    await renameKbKnowledgeBase(kb.knowledge_id, name, authToken.value ?? '')
    editingId.value = ''
    await refresh()
    emit('changed')
  } catch (err) {
    notice.value = `改名失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busy.value = ''
  }
}

async function onDelete(kb: KbKnowledgeBase): Promise<void> {
  if (busy.value) return
  if (kb.doc_count > 0) {
    notice.value = `「${kb.name}」下还有 ${kb.doc_count} 个文档，请先下线文档再删库。`
    return
  }
  if (!window.confirm(`确定删除知识库「${kb.name}」？`)) return
  busy.value = kb.knowledge_id
  notice.value = ''
  try {
    await deleteKbKnowledgeBase(kb.knowledge_id, authToken.value ?? '')
    notice.value = `已删除「${kb.name}」`
    await refresh()
    emit('changed')
  } catch (err) {
    notice.value = `删除失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busy.value = ''
  }
}

defineExpose({ refresh })
onMounted(refresh)
</script>

<template>
  <div class="kb-sidebar">
    <div class="composer__row">
      <h2 class="o-head-sm">
        知识库
        <span class="count-badge">{{ bases.length }}</span>
      </h2>
      <button
        type="button"
        class="ry-btn"
        @click="creating = !creating"
      >
        {{ creating ? '取消' : '+ 新建' }}
      </button>
    </div>

    <div
      v-if="creating"
      class="composer__row"
    >
      <input
        v-model="newName"
        class="ry-input"
        type="text"
        placeholder="输入知识库名称"
        aria-label="新知识库名称"
        @keydown.enter="onCreate"
      >
      <button
        type="button"
        class="ry-btn ry-btn--primary"
        :aria-disabled="!newName.trim() || busy === 'create'"
        @click="onCreate"
      >
        {{ busy === 'create' ? '创建中…' : '创建' }}
      </button>
    </div>

    <p
      v-if="notice"
      class="hint"
      role="status"
    >
      {{ notice }}
    </p>

    <ul class="kb-sidebar__list">
      <li
        v-for="kb in bases"
        :key="kb.knowledge_id"
        class="kb-sidebar__item"
      >
        <template v-if="editingId === kb.knowledge_id">
          <input
            v-model="editName"
            class="ry-input"
            type="text"
            aria-label="知识库新名称"
            @keydown.enter="onRename(kb)"
            @keydown.esc="editingId = ''"
          >
          <button
            type="button"
            class="ry-btn ry-btn--text"
            :aria-disabled="busy === kb.knowledge_id"
            @click="onRename(kb)"
          >
            保存
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            class="ry-btn ry-btn--text kb-sidebar__pick"
            :title="`${kb.name || kb.knowledge_id} · ${kb.knowledge_id}`"
            @click="choose(kb)"
          >
            <span class="kb-sidebar__name">{{ kb.name || kb.knowledge_id }}</span>
            <span class="hint">{{ kb.doc_count }} 文档</span>
          </button>
          <button
            type="button"
            class="ry-btn ry-btn--text"
            title="重命名"
            @click="startEdit(kb)"
          >
            ✎
          </button>
          <button
            type="button"
            class="ry-btn ry-btn--text"
            :title="kb.doc_count > 0 ? '库下有文档，先下线文档' : '删除知识库'"
            :aria-disabled="busy === kb.knowledge_id || kb.doc_count > 0"
            @click="onDelete(kb)"
          >
            ×
          </button>
        </template>
      </li>
    </ul>

    <p
      v-if="!loading && bases.length === 0"
      class="hint"
    >
      还没有知识库，点「+ 新建」创建一个。
    </p>
    <p
      v-if="loading"
      class="hint"
    >
      加载中…
    </p>
  </div>
</template>
