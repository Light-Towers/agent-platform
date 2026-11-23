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
  updateKbChunkConfig,
  DEFAULT_KB_CHUNK_CONFIG,
  type KbKnowledgeBase,
  type KbChunkConfig,
} from '../api/kb.ts'

const props = defineProps<{
  /** knowledge_id → 真实文档数（来自 Milvus 文档树）；用它替代 /collections 的恒 0 冗余字段。 */
  docCounts: Map<string, number>
  /** 当前选中的 knowledge_id，用于选中态高亮（与对话页会话列表同一套 is-active 样式）。 */
  selectedId: string
}>()

const emit = defineEmits<{
  select: [knowledgeId: string, name: string]
  changed: []   // 库列表变化（新建/改名/删除）后通知父组件刷新
  renamed: [knowledgeId: string, name: string]  // #3：改名当前库 → 父组件同步右栏标题
  deleted: [knowledgeId: string]                // #2：删库 → 父组件清选中态
  /** 库配置索引（L-B：单一数据源，避免父组件重复请求 listKnowledgeBases）。 */
  configs: [map: Map<string, KbChunkConfig>]
}>()

const bases = ref<KbKnowledgeBase[]>([])
const loading = ref(false)
/** #9：成功/失败提示二分（成功绿、失败红）。 */
const notice = ref<{ text: string; ok: boolean }>({ text: '', ok: true })
function setNotice(text: string, ok: boolean): void {
  notice.value = { text, ok }
}
const creating = ref(false)
const newName = ref('')
const editingId = ref('')
const editName = ref('')
const busy = ref('')

/** 切分设置编辑态（刀 3）：正在编辑配置的库 id + 草稿（可变副本，KbChunkConfig 只读）。 */
type ChunkConfigDraft = { split_strategy: KbChunkConfig['split_strategy']; max_content_length: number; chunk_overlap_ratio: number }
const configEditingId = ref('')
const configDraft = ref<ChunkConfigDraft>({ ...DEFAULT_KB_CHUNK_CONFIG })
const STRATEGY_OPTIONS: { value: KbChunkConfig['split_strategy']; label: string }[] = [
  { value: 'title', label: '按标题切分' },
  { value: 'char', label: '按字符数切分' },
  { value: 'line', label: '按行/表格切分' },
]

function startConfigEdit(kb: KbKnowledgeBase): void {
  configDraft.value = kb.chunk_config
    ? { ...kb.chunk_config }
    : { ...DEFAULT_KB_CHUNK_CONFIG }
  configEditingId.value = configEditingId.value === kb.knowledge_id ? '' : kb.knowledge_id
}

async function onSaveConfig(kb: KbKnowledgeBase): Promise<void> {
  const d = configDraft.value
  // 前端做基本范围提示（后端为准做权威校验）
  // L-C：下列 500/2000/0.5 与后端 chunk_config_utils 的 MAX_MIN/MAX_MAX/OVERLAP_RATIO_MAX 三处重复；
  // 后端 P-2 取证若收紧，以服务端 400 为准（此处提示可能滞后），届时同步这三个数。
  if (!Number.isInteger(d.max_content_length) || d.max_content_length < 500 || d.max_content_length > 2000) {
    setNotice('块大小须为 500–2000 之间的整数', false)
    return
  }
  if (d.chunk_overlap_ratio < 0 || d.chunk_overlap_ratio > 0.5) {
    setNotice('重叠比例须在 0–50% 之间', false)
    return
  }
  busy.value = `cfg-${kb.knowledge_id}`
  setNotice('', true)
  try {
    await updateKbChunkConfig(kb.knowledge_id, d, authToken.value ?? '')
    setNotice(`已保存「${kb.name || kb.knowledge_id}」的切分配置`, true)
    configEditingId.value = ''
    await refresh()
    emit('changed')  // 通知父组件刷新 chunkConfigById → 上传页只读展示同步
  } catch (err) {
    setNotice(`切分配置保存失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    busy.value = ''
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  try {
    bases.value = await listKnowledgeBases(authToken.value ?? '')
    // L-B：单一数据源——把配置索引 emit 给父组件，父不再另发一次 listKnowledgeBases
    const configMap = new Map<string, KbChunkConfig>()
    for (const b of bases.value) if (b.chunk_config) configMap.set(b.knowledge_id, b.chunk_config)
    emit('configs', configMap)
  } catch (err) {
    setNotice(`加载失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    loading.value = false
  }
}

function docCount(kb: KbKnowledgeBase): number {
  return props.docCounts.get(kb.knowledge_id) ?? kb.doc_count ?? 0
}

function choose(kb: KbKnowledgeBase): void {
  emit('select', kb.knowledge_id, kb.name || kb.knowledge_id)
}

async function onCreate(): Promise<void> {
  const name = newName.value.trim()
  if (!name || busy.value) return
  busy.value = 'create'
  setNotice('', true)
  try {
    const created = await createKbKnowledgeBase(name, authToken.value ?? '')
    setNotice(`已创建「${created.name}」`, true)
    newName.value = ''
    creating.value = false
    await refresh()
    emit('changed')
    emit('select', created.knowledge_id, created.name)
  } catch (err) {
    setNotice(`创建失败：${err instanceof Error ? err.message : String(err)}`, false)
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
    setNotice(`已改名为「${name}」`, true)
    await refresh()
    emit('renamed', kb.knowledge_id, name)
    emit('changed')
  } catch (err) {
    setNotice(`改名失败：${err instanceof Error ? err.message : String(err)}`, false)
  } finally {
    busy.value = ''
  }
}

async function onDelete(kb: KbKnowledgeBase): Promise<void> {
  if (busy.value) return
  if (docCount(kb) > 0) {
    setNotice(`「${kb.name}」下还有 ${docCount(kb)} 个有效文档，请先下线文档再删库。`, false)
    return
  }
  if (!window.confirm(`确定删除知识库「${kb.name}」？`)) return
  busy.value = kb.knowledge_id
  setNotice('', true)
  try {
    await deleteKbKnowledgeBase(kb.knowledge_id, authToken.value ?? '')
    setNotice(`已删除「${kb.name}」`, true)
    await refresh()
    emit('deleted', kb.knowledge_id)  // #2：父组件清选中态
    emit('changed')
  } catch (err) {
    setNotice(`删除失败：${err instanceof Error ? err.message : String(err)}`, false)
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
      v-if="notice.text"
      class="notice"
      :class="notice.ok ? 'notice--ok' : 'banner'"
      role="status"
    >
      <strong>{{ notice.text }}</strong>
    </p>

    <ul class="kb-sidebar__list">
      <li
        v-for="kb in bases"
        :key="kb.knowledge_id"
        class="kb-sidebar__item"
        :class="{ 'is-active': selectedId === kb.knowledge_id }"
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
            <span class="hint">{{ docCount(kb) }} 文档</span>
          </button>
          <button
            type="button"
            class="ry-btn ry-btn--text"
            title="切分设置"
            @click="startConfigEdit(kb)"
          >
            设置
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
            :title="docCount(kb) > 0 ? '库下有文档，先下线文档' : '删除知识库'"
            :aria-disabled="busy === kb.knowledge_id || docCount(kb) > 0"
            @click="onDelete(kb)"
          >
            ×
          </button>
        </template>

        <!-- 切分设置内联编辑器（仅改库级配置；上传页只读展示） -->
        <div
          v-if="configEditingId === kb.knowledge_id"
          class="kb-config-editor"
        >
          <label class="o-head-sm">
            切分规则
            <select
              v-model="configDraft.split_strategy"
              class="ry-input"
              aria-label="切分规则"
            >
              <option
                v-for="opt in STRATEGY_OPTIONS"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</option>
            </select>
          </label>
          <label class="o-head-sm">
            每片字数（500–2000）
            <input
              v-model.number="configDraft.max_content_length"
              class="ry-input"
              type="number"
              min="500"
              max="2000"
              aria-label="切块大小"
            >
          </label>
          <label class="o-head-sm">
            重叠比例（0–50%）
            <input
              :value="Math.round(configDraft.chunk_overlap_ratio * 100)"
              class="ry-input"
              type="number"
              min="0"
              max="50"
              aria-label="重叠比例"
              @input="configDraft.chunk_overlap_ratio = Number(($event.target as HTMLInputElement).value) / 100"
            >
          </label>
          <p class="hint">
            规则按字符切；改完重新上传同名文档即按新配置覆盖。
          </p>
          <div class="composer__row">
            <button
              type="button"
              class="ry-btn ry-btn--primary"
              :aria-disabled="busy === `cfg-${kb.knowledge_id}`"
              @click="onSaveConfig(kb)"
            >
              {{ busy === `cfg-${kb.knowledge_id}` ? '保存中…' : '保存配置' }}
            </button>
            <button
              type="button"
              class="ry-btn"
              @click="configEditingId = ''"
            >
              取消
            </button>
          </div>
        </div>
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
