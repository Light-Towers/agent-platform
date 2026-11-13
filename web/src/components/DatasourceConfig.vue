<!-- ============================================================================
 * DatasourceConfig.vue — 问数数据源配置页（G3 刀 3；方案 §5/§6）
 *
 * 本页仅做**配置面**：列出数据源、改名称/方言/口径标签、设默认源、绑元数据引用名。
 * 两条刻意不做（对应文档 N1/N4）：
 *  ① 口令/DSN **绝不**出现在任何输入框或回显——credential_ref 只是 Secret 投影的
 *     键名（如 DW_DB_DSN），库里只落引用名；界面文案照写「保存不校验、启动才验」。
 *  ② 不做多源池热加载——改了 is_default 只是登记态变更，真正生效以部署清单为准。
 * 调用走 agent_server 代理 /datasources（feature datasource.manage），浏览器不直连 nl2sql。
 * 本件无 <style> 块；类全在 base.css（与 KbUpload.vue 同套）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createDatasource,
  DIALECT_OPTIONS,
  listDatasources,
  setDefaultDatasource,
  updateDatasource,
  type Datasource,
} from '../api/datasources.ts'

const loading = ref(false)
const errorText = ref('')
const datasources = ref<Datasource[]>([])

// 编辑态
const editing = ref<Datasource | null>(null)
const editLabel = ref('')
const editDialect = ref('')
const editScope = ref('')
const editCredRef = ref('')

// 新建态
const showCreate = ref(false)
const newId = ref('')
const newLabel = ref('')
const newDialect = ref('mysql')
const newScope = ref('')
const newCredRef = ref('')

// 受支持的数据源类型（目前先支持 MySQL）；编辑既有 postgres 默认源时把当前方言也纳入选项，
// 避免下拉框因选项不含当前值而显示空白（不引入新类型，仅保展示连贯）。
const editOptions = computed(() => {
  const values = DIALECT_OPTIONS.map((o) => o.value)
  if (editing.value && !values.includes(editing.value.dialect)) {
    return [...DIALECT_OPTIONS, { value: editing.value.dialect, label: editing.value.dialect }]
  }
  return DIALECT_OPTIONS
})

async function refresh(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    datasources.value = await listDatasources()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function startEdit(ds: Datasource): void {
  editing.value = ds
  editLabel.value = ds.label
  editDialect.value = ds.dialect
  editScope.value = ds.scope_label
  editCredRef.value = ds.credential_ref
  showCreate.value = false
}

function cancelEdit(): void {
  editing.value = null
}

async function saveEdit(): Promise<void> {
  if (editing.value === null) return
  errorText.value = ''
  try {
    await updateDatasource(editing.value.id, {
      label: editLabel.value,
      dialect: editDialect.value,
      scope_label: editScope.value,
      credential_ref: editCredRef.value,
    })
    editing.value = null
    await refresh()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  }
}

async function markDefault(ds: Datasource): Promise<void> {
  errorText.value = ''
  try {
    await setDefaultDatasource(ds.id)
    await refresh()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  }
}

function openCreate(): void {
  showCreate.value = true
  editing.value = null
  newId.value = ''
  newLabel.value = ''
  newDialect.value = 'mysql'
  newScope.value = ''
  newCredRef.value = ''
}

function cancelCreate(): void {
  showCreate.value = false
}

async function submitCreate(): Promise<void> {
  errorText.value = ''
  if (newId.value.trim() === '' || newCredRef.value.trim() === '') {
    errorText.value = 'id 与 credential_ref 均为必填'
    return
  }
  try {
    await createDatasource({
      id: newId.value.trim(),
      label: newLabel.value,
      dialect: newDialect.value,
      scope_label: newScope.value,
      credential_ref: newCredRef.value,
    })
    showCreate.value = false
    await refresh()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(() => { void refresh() })
</script>

<template>
  <main class="grid">
    <div class="col">
      <section
        class="panel"
        aria-labelledby="hDs"
      >
        <h2 id="hDs">
          问数数据源配置
        </h2>
        <p class="hint">
          本页只配置数据源的展示与归属元数据。credential_ref 是 Secret 投影键名
          （如 DW_DB_DSN），<strong>不存口令</strong>；保存不校验、启动 reconcile 才验。
          数据源类型目前支持 <strong>MySQL / Hive</strong>。
        </p>

        <p
          v-if="errorText"
          class="banner"
        >
          <strong>{{ errorText }}</strong>
        </p>

        <div
          v-if="loading"
          class="hint"
        >
          加载中…
        </div>

        <table
          v-else
          class="stack"
        >
          <thead>
            <tr>
              <th>id</th>
              <th>名称</th>
              <th>类型</th>
              <th>口径标签</th>
              <th>credential_ref</th>
              <th>默认</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ds in datasources"
              :key="ds.id"
            >
              <td><code class="t-name">{{ ds.id }}</code></td>
              <td>{{ ds.label }}</td>
              <td>{{ ds.dialect }}</td>
              <td>{{ ds.scope_label }}</td>
              <td><code class="t-name">{{ ds.credential_ref }}</code></td>
              <td>{{ ds.is_default ? '是' : '否' }}</td>
              <td>{{ ds.status }}</td>
              <td>
                <button
                  type="button"
                  class="btn"
                  @click="startEdit(ds)"
                >
                  编辑
                </button>
                <button
                  v-if="!ds.is_default"
                  type="button"
                  class="btn btn-primary"
                  @click="markDefault(ds)"
                >
                  设默认
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <button
          type="button"
          class="btn btn-primary"
          @click="openCreate"
        >
          新建数据源
        </button>
      </section>

      <!-- 编辑面板 -->
      <section
        v-if="editing"
        class="panel"
        aria-labelledby="hEdit"
      >
        <h2 id="hEdit">
          编辑：{{ editing.id }}
        </h2>
        <form
          class="composer"
          @submit.prevent="saveEdit"
        >
          <label class="o-head-sm">名称</label>
          <input
            v-model="editLabel"
            class="field"
            type="text"
            aria-label="名称"
          >
          <label class="o-head-sm">数据源类型</label>
          <select
            v-model="editDialect"
            class="field"
            aria-label="数据源类型"
          >
            <option
              v-for="d in editOptions"
              :key="d.value"
              :value="d.value"
            >
              {{ d.label }}
            </option>
          </select>
          <label class="o-head-sm">口径标签</label>
          <input
            v-model="editScope"
            class="field"
            type="text"
            aria-label="口径标签"
          >
          <label class="o-head-sm">credential_ref（Secret 投影键名，非口令）</label>
          <input
            v-model="editCredRef"
            class="field"
            type="text"
            aria-label="credential_ref"
          >
          <div class="composer__row">
            <button
              type="submit"
              class="btn btn-primary"
            >
              保存
            </button>
            <button
              type="button"
              class="btn"
              @click="cancelEdit"
            >
              取消
            </button>
          </div>
        </form>
      </section>

      <!-- 新建面板 -->
      <section
        v-if="showCreate"
        class="panel"
        aria-labelledby="hNew"
      >
        <h2 id="hNew">
          新建数据源
        </h2>
        <form
          class="composer"
          @submit.prevent="submitCreate"
        >
          <label class="o-head-sm">id（必填）</label>
          <input
            v-model="newId"
            class="field"
            type="text"
            aria-label="id"
          >
          <label class="o-head-sm">名称</label>
          <input
            v-model="newLabel"
            class="field"
            type="text"
            aria-label="名称"
          >
          <label class="o-head-sm">数据源类型</label>
          <select
            v-model="newDialect"
            class="field"
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
          <label class="o-head-sm">口径标签</label>
          <input
            v-model="newScope"
            class="field"
            type="text"
            aria-label="口径标签"
          >
          <label class="o-head-sm">credential_ref（必填，Secret 投影键名，非口令）</label>
          <input
            v-model="newCredRef"
            class="field"
            type="text"
            aria-label="credential_ref"
          >
          <div class="composer__row">
            <button
              type="submit"
              class="btn btn-primary"
            >
              创建
            </button>
            <button
              type="button"
              class="btn"
              @click="cancelCreate"
            >
              取消
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>
