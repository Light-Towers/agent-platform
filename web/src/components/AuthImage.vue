<!-- ============================================================================
 * AuthImage.vue — 鉴权图片加载（plan-image-qa-fullstack，2026-11-24）
 *
 * 背景：/img 代理端点要 Bearer 令牌（桶私有），但浏览器 <img src> 不会带 Authorization
 * 头 ⇒ 直接把 /img/... 放进 src 会 401 碎图（2026-11-24 界面截图实踩）。
 * 解法：组件内部用 fetch() 带令牌取图 → blob → object URL 给 <img>。令牌不进 URL
 * （不泄漏到日志/referrer），后端鉴权不变。
 * 单一实现：切分预览（KbUpload）与回答回显（ImageStrip）共用本件。
 * 本件无 <style> 块；形状类落 base.css。
 * ==========================================================================-->
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useSessionStore } from '../stores/session.ts'
import { fetchImageBlob } from '../stores/sseReducer.ts'

const props = defineProps<{
  url: string
  alt?: string
  imgClass?: string
}>()

const { authToken } = storeToRefs(useSessionStore())
const blobUrl = ref('')
const failed = ref(false)
let currentObjectUrl = ''

function revoke(): void {
  if (currentObjectUrl !== '') {
    URL.revokeObjectURL(currentObjectUrl)
    currentObjectUrl = ''
  }
}

async function load(url: string): Promise<void> {
  revoke()
  blobUrl.value = ''
  failed.value = false
  const result = await fetchImageBlob(url, authToken.value)
  if (!result.ok) { failed.value = true; return }
  currentObjectUrl = URL.createObjectURL(result.blob)
  blobUrl.value = currentObjectUrl
}

watch(() => props.url, (u) => { void load(u) }, { immediate: true })
onBeforeUnmount(revoke)
</script>

<template>
  <img
    v-if="blobUrl !== ''"
    :src="blobUrl"
    :alt="alt || '图片'"
    :class="imgClass"
    loading="lazy"
    referrerpolicy="no-referrer"
  >
  <span
    v-else-if="failed"
    class="rich-img-failed"
    :title="url"
  >图片加载失败</span>
  <span
    v-else
    class="rich-img-loading"
  >加载中…</span>
</template>
