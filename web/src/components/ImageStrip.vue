<!-- ============================================================================
 * ImageStrip.vue — 回答回显的图片缩略图条（plan-image-citation-e2e-2026-11-23）
 * 只渲染后端 rich.images 里已过服务端白名单的 URL，渲染前再过一次 isSafeImageUrl
 * （伪协议二次闸）。零 v-html：图片走 Vue :src 绑定，不解析答案正文里的 markdown。
 * R5c：lightbox 补 aria-modal / Escape 关闭 / 焦点锁 / 关闭后焦点归还触发按钮。
 * 本件无 <style> 块；形状类落 base.css（见 ThemeToggle.vue 头注同一理由）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { isSafeImageUrl, type RichImage } from '../stores/sseReducer.ts'
import AuthImage from './AuthImage.vue'

const props = defineProps<{ images: readonly RichImage[] }>()

/** 二次校验：服务端白名单之外的形状（伪协议/相对路径）在渲染层再挡一次。 */
const safeImages = computed(() => props.images.filter((img) => isSafeImageUrl(img.url)))

const preview = ref<RichImage | null>(null)
const dialogRef = ref<HTMLElement | null>(null)
let lastTrigger: HTMLElement | null = null

function open(img: RichImage, event: MouseEvent): void {
  lastTrigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  preview.value = img
}
function close(): void {
  preview.value = null
  lastTrigger?.focus()
  lastTrigger = null
}

watch(preview, async (img) => {
  if (img === null) return
  await nextTick()
  dialogRef.value?.focus()
})

/** Escape 关闭 + Tab 焦点锁（弹层内只有关闭按钮，循环即在它与容器之间）。 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') { close(); return }
  if (event.key !== 'Tab') return
  const host = dialogRef.value
  if (host === null) return
  const focusables = host.querySelectorAll<HTMLElement>('button, [href], [tabindex]:not([tabindex="-1"])')
  if (focusables.length === 0) { event.preventDefault(); host.focus(); return }
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
</script>

<template>
  <div
    v-if="safeImages.length > 0"
    class="rich-images"
  >
    <div class="rich-images__label">
      回答引用的图片（{{ safeImages.length }}）
    </div>
    <div class="rich-images__strip">
      <button
        v-for="(img, i) in safeImages"
        :key="`${img.url}-${i}`"
        type="button"
        class="rich-images__thumb"
        :title="img.caption || img.source_doc || '查看图片'"
        @click="open(img, $event)"
      >
        <AuthImage
          :url="img.url"
          :alt="img.caption || '回答引用的图片'"
          img-class="rich-images__thumb-img"
        />
      </button>
    </div>
    <div
      v-if="preview"
      ref="dialogRef"
      class="rich-images__lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="图片预览"
      tabindex="-1"
      @click="close"
      @keydown="onKeydown"
    >
      <div
        class="rich-images__lightbox-body"
        @click.stop
      >
        <AuthImage
          :url="preview.url"
          :alt="preview.caption || '图片预览'"
          img-class="rich-images__lightbox-img"
        >
          <p class="hint">
            {{ preview.caption || preview.source_doc || '回答引用的图片' }}
          </p>
          <button
            type="button"
            class="ry-btn"
            @click="close"
          >
            关闭
          </button>
        </authimage>
      </div>
    </div>
  </div>
</template>
