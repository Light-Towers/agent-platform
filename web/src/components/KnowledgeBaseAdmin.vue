<!-- ============================================================================
 * KnowledgeBaseAdmin.vue — 知识库管理页（P3，plan-kb-delete-and-management-2026-11-18）
 *
 * 职责：列出租户知识库 + 展开看登记文档 + 删单文档（软删除→REVOKED）+ 删整库
 * （前置：库下无有效文档）。删除是软删除，数据可恢复；租户隔离由签名断言保证。
 * 组件无 <style> 块，形状全部复用 base.css 既有类（ry-card/ry-btn/banner/hint 等）。
 * ==========================================================================-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { authToken } from '../stores/session'
import {
  listKnowledgeBases,
  listKbDocuments,
  deleteKbDocument,
  deleteKbKnowledgeBase,
  type KbKnowledgeBase,
} from '../api/kb.ts'

/** 登记文档一条（KS /documents 返回，只用到 knowledge_id/status/filename/updated_at）。 */
interface KbDoc {
  knowledge_id: string
  status: string
  filename: string
  updated_at?: string
}

const bases = ref<KbKnowledgeBase[]>([])
const expanded = ref<string>('')          // 当前展开的库 knowledge_id
const docs = ref<KbDoc[]>([])
const loading = ref(false)
const notice = ref('')                    // 成功/失败提示（一屏一条，操作后更新）
const busyKid = ref('')                   // 正在删除的 knowledge_id（防重复点）

async function refresh(): Promise<void> {
  loading.value = true
  notice.value = ''
  try {
    bases.value = await listKnowledgeBases(authToken.value ?? '')
  } catch (err) {
    notice.value = `知识库列表加载失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    loading.value = false
  }
}

async function toggleDoc(kid: string): Promise<void> {
  if (expanded.value === kid) {
    expanded.value = ''
    docs.value = []
    return
  }
  expanded.value = kid
  docs.value = []
  notice.value = ''
  try {
    const res = await listKbDocuments(authToken.value ?? '') as { documents?: KbDoc[] }
    const all = Array.isArray(res?.documents) ? res.documents : []
    docs.value = all.filter((d) => d.knowledge_id === kid)
  } catch (err) {
    notice.value = `文档列表加载失败：${err instanceof Error ? err.message : String(err)}`
  }
}

function isActiveDoc(d: KbDoc): boolean {
  const s = (d.status || '').toUpperCase()
  return !!s && s !== 'REVOKED'
}

async function onDeleteDocument(kid: string): Promise<void> {
  if (busyKid.value) return
  if (!window.confirm(`确定下线文档「${kid}」？该文档将从对话检索中移除（软删除，数据保留）。`)) return
  busyKid.value = kid
  notice.value = ''
  try {
    await deleteKbDocument(kid, authToken.value ?? '')
    notice.value = `文档「${kid}」已下线（REVOKED），对话检索不再召回。`
    await refresh()
    if (expanded.value === kid) await toggleDoc(kid) // 重新展开刷新文档状态
  } catch (err) {
    notice.value = `文档下线失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busyKid.value = ''
  }
}

async function onDeleteBase(kid: string, docCount: number): Promise<void> {
  if (busyKid.value) return
  if (docCount > 0) {
    notice.value = `知识库「${kid}」下还有 ${docCount} 个有效文档，请先将文档全部下线后再删库。`
    return
  }
  if (!window.confirm(`确定删除知识库「${kid}」？该操作会标记库为 deleted（数据保留）。`)) return
  busyKid.value = kid
  notice.value = ''
  try {
    await deleteKbKnowledgeBase(kid, authToken.value ?? '')
    notice.value = `知识库「${kid}」已删除。`
    expanded.value = ''
    docs.value = []
    await refresh()
  } catch (err) {
    notice.value = `知识库删除失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busyKid.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <div class="col">
    <section
      class="ry-card"
      aria-labelledby="hKbAdmin"
    >
      <h2 id="hKbAdmin">
        知识库管理
        <span class="count-badge">{{ bases.length }} 个库</span>
      </h2>
      <p class="hint">
        列出当前租户的所有知识库。可展开查看登记文档、下线单个文档（软删除 REVOKED），
        或将已无有效文档的知识库删除。删除均为软删除，数据保留、可恢复。
      </p>
      <div class="composer__row">
        <button
          type="button"
          class="ry-btn"
          :aria-disabled="loading"
          @click="refresh"
        >
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
      <p
        v-if="notice"
        class="banner"
        role="status"
      >
        <strong>{{ notice }}</strong>
      </p>
    </section>

    <section
      v-for="kb in bases"
      :key="kb.knowledge_id"
      class="ry-card"
    >
      <div class="composer__row">
        <button
          type="button"
          class="ry-btn ry-btn--text"
          @click="toggleDoc(kb.knowledge_id)"
        >
          {{ expanded === kb.knowledge_id ? '▾' : '▸' }} {{ kb.name || kb.knowledge_id }}
        </button>
        <span class="count-badge">{{ kb.doc_count }} 个文档</span>
        <span class="hint">状态：{{ kb.status }}</span>
        <button
          type="button"
          class="ry-btn"
          :aria-disabled="busyKid === kb.knowledge_id || kb.doc_count > 0"
          :title="kb.doc_count > 0 ? '库下还有文档，请先下线文档' : '删除该知识库'"
          @click="onDeleteBase(kb.knowledge_id, kb.doc_count)"
        >
          {{ busyKid === kb.knowledge_id ? '删除中…' : '删除知识库' }}
        </button>
      </div>

      <div
        v-if="expanded === kb.knowledge_id"
        class="col"
      >
        <p
          v-if="docs.length === 0"
          class="hint"
        >
          该库暂无登记文档。
        </p>
        <div
          v-for="d in docs"
          :key="d.filename + d.updated_at"
          class="composer__row"
        >
          <span class="o-head-sm">{{ d.filename || d.knowledge_id }}</span>
          <span class="hint">状态：{{ d.status }}</span>
          <button
            type="button"
            class="ry-btn"
            :aria-disabled="busyKid === d.knowledge_id || !isActiveDoc(d)"
            :title="!isActiveDoc(d) ? '该文档已下线' : '下线该文档'"
            @click="onDeleteDocument(d.knowledge_id)"
          >
            {{ busyKid === d.knowledge_id ? '下线中…' : '下线文档' }}
          </button>
        </div>
      </div>
    </section>

    <p
      v-if="!loading && bases.length === 0"
      class="hint"
    >
      尚无知识库。请先在「知识库」页上传文档（填写知识库 ID）自动建库。
    </p>
  </div>
</template>
