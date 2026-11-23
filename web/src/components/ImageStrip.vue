<!-- ============================================================================
 * ImageStrip.vue — 回答回显的图片缩略图条（plan-image-citation-e2e-2026-11-23）
 * 只渲染后端 rich.images 里已过服务端白名单的 URL，渲染前再过一次 isSafeImageUrl
 * （伪协议二次闸）。零 v-html：图片走 Vue :src 绑定，不解析答案正文里的 markdown。
 * 本件无 <style> 块；形状类落 base.css（见 ThemeToggle.vue 头注同一理由）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { isSafeImageUrl, type RichImage } from '../api/sse.ts'

const props = defineProps<{ images: readonly RichImage[] }>()

/** 二次校验：服务端白名单之外的形状（伪协议/相对路径）在渲染层再挡一次。 */
const safeImages = computed(() => props.images.filter((img) => isSafeImageUrl(img.url)))

/** 点击缩略图放大预览（用户视角：传的图能看清）。 */
const preview = ref<RichImage | null>(null)
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
        @click="preview = img"
      >
        <img
          :src="img.url"
          :alt="img.caption || '回答引用的图片'"
          loading="lazy"
          referrerpolicy="no-referrer"
        >
      </button>
    </div>
    <div
      v-if="preview"
      class="rich-images__lightbox"
      role="dialog"
      aria-label="图片预览"
      @click="preview = null"
    >
      <div class="rich-images__lightbox-body">
        <img
          :src="preview.url"
          :alt="preview.caption || '图片预览'"
          referrerpolicy="no-referrer"
        >
        <p class="hint">
          {{ preview.caption || preview.source_doc || '回答引用的图片' }} · 点击关闭
        </p>
      </div>
    </div>
  </div>
</template>
