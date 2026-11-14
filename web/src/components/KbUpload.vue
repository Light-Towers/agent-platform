<!-- ============================================================================
 * KbUpload.vue — 知识库上传配置页（G2；方案 §4 D7 + 补记 9）
 *
 * 在 web/ 里上传文档 + 填上传配置（模板层已砍除，metadata 每次随表单填），可见任务进度。
 * 浏览器不直连 KS：所有请求只打 agent_server 的 /kb/* 代理（kb_router.py），
 * 凭据头经 applyCredentialHeaders（api/auth.ts 唯一装配点）。
 *
 * 表单 12 个随填 metadata 字段对齐 kb_router 转发的 KS /upload 13 Form 字段
 * （tenant_id 不填，由服务端断言注入；前端发空串仅作 R5 校验占位）。
 * ⚠ 本件无 <style> 块（工程约束）；用到的类全在 base.css。
 * ==========================================================================-->
<script setup lang="ts">
import { ref } from 'vue'

import { authToken } from '../stores/session'
import { uploadKbDocuments, getKbStatus, listKbDocuments, type KbUploadForm } from '../api/kb.ts'
import { DIALECT_OPTIONS } from '../api/datasources.ts'

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
const errorText = ref('')
const lastTaskIds = ref<string[]>([])
const statusText = ref('')
const documents = ref<unknown>(null)

function onPickFiles(e: Event): void {
  const input = e.target as HTMLInputElement
  files.value = input.files ? Array.from(input.files) : []
}

async function submit(): Promise<void> {
  errorText.value = ''
  statusText.value = ''
  if (files.value.length === 0) {
    errorText.value = '请先选择至少一个文档文件'
    return
  }
  busy.value = true
  try {
    const res = await uploadKbDocuments(files.value, form.value, authToken.value ?? '')
    const json = res as { task_ids?: string[] }
    lastTaskIds.value = json.task_ids ?? []
    if (lastTaskIds.value.length > 0) {
      const firstId = lastTaskIds.value[0]
      if (firstId !== undefined) {
        await pollStatus(firstId)
      }
    }
    await refreshDocuments()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

async function pollStatus(taskId: string): Promise<void> {
  try {
    const res = await getKbStatus(taskId, authToken.value ?? '')
    statusText.value = JSON.stringify(res)
  } catch (err) {
    statusText.value = err instanceof Error ? err.message : String(err)
  }
}

async function refreshDocuments(): Promise<void> {
  try {
    documents.value = await listKbDocuments(authToken.value ?? '')
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  }
}
</script>

<template>
  <div class="col">
    <div class="col">
      <section
        class="panel"
        aria-labelledby="hKb"
      >
        <h2 id="hKb">
          知识库上传配置
        </h2>
        <p class="hint">
          上传文档并填写本次导入的配置（模板层已取消，配置随每次上传表单提交）。请求只发往
          <code class="t-name">/kb/uploads</code> 代理，浏览器不直连知识库服务。
          数据源类型（MySQL / Hive）随 metadata 一并提交给知识库服务，用于标注文档归属的数据源类型。
        </p>

        <form
          class="stack"
          @submit.prevent="submit"
        >
          <label class="o-head-sm">
            文档文件（可多选）
            <input
              type="file"
              multiple
              @change="onPickFiles"
            >
          </label>
          <p
            v-if="files.length"
            class="hint"
          >
            已选 {{ files.length }} 个文件
          </p>

          <label class="o-head-sm">
            scope_type
            <input
              v-model="form.scopeType"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            tenant_type
            <input
              v-model="form.tenantType"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            effective_from
            <input
              v-model="form.effectiveFrom"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            effective_to
            <input
              v-model="form.effectiveTo"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            version
            <input
              v-model="form.version"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            authority
            <input
              v-model="form.authority"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            status
            <input
              v-model="form.status"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            constraint_kind
            <input
              v-model="form.constraintKind"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            knowledge_id
            <input
              v-model="form.knowledgeId"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            exhibition_id
            <input
              v-model="form.exhibitionId"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            venue_id
            <input
              v-model="form.venueId"
              class="field"
              type="text"
            >
          </label>
          <label class="o-head-sm">
            数据源类型
            <select
              v-model="form.datasourceType"
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
          </label>
          <label class="o-head-sm">
            enable_item_name_recognition
            <input
              v-model="form.enableItemNameRecognition"
              type="checkbox"
            >
          </label>

          <button
            type="submit"
            class="btn btn-primary"
            :aria-disabled="busy"
          >
            {{ busy ? '上传中…' : '上传' }}
          </button>
        </form>

        <p
          v-if="errorText"
          class="banner"
        >
          <strong>{{ errorText }}</strong>
        </p>
        <p
          v-if="lastTaskIds.length"
          class="hint"
        >
          任务 ID：{{ lastTaskIds.join('、') }}
        </p>
        <pre
          v-if="statusText"
          class="hint"
        >{{ statusText }}</pre>
      </section>

      <section
        class="panel"
        aria-labelledby="hDocs"
      >
        <h2 id="hDocs">
          已登记文档
        </h2>
        <button
          type="button"
          class="btn"
          @click="refreshDocuments"
        >
          刷新列表
        </button>
        <pre
          v-if="documents"
          class="hint"
        >{{ JSON.stringify(documents, null, 2) }}</pre>
        <p
          v-else
          class="hint"
        >
          尚未加载（点「刷新列表」拉取 GET /kb/documents）。
        </p>
      </section>
    </div>
  </div>
</template>
