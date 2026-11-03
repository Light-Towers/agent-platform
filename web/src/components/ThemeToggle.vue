<!-- ============================================================================
 * ThemeToggle.vue — 主题三档控件
 * 本件**没有 <style> 块**，这不是遗漏：视觉件 §1.1 定的是「样式只住在 styles/ 三件、
 * main.ts 是唯一入口」，组件里写一个局部 <style> 就等于开了第二条样式通道 ——
 * 它会让「这个颜色从哪来」重新变成需要人查的问题（门禁断言 1 只扫得到 var(--*)，
 * 扫不到 SFC 里新写的块）。要用新形状就得先往 styles/ 加类，那是同批的显式动作。
 * 三档的形状沿用 POC 宿主页（.seg + aria-pressed），不另造控件。
 * `:aria-pressed` 绑**布尔**而不是 `String(...)`：本件初版写的是字符串，理由
 * 是“Vue 对 aria-* 收到 false 会 removeAttribute”—— 那句是错的，被两道门各自拓回来：
 *   ① vue-tsc 当场报 TS2322（`aria-pressed` 的类型是 `Booleanish | "mixed"`，不收 string）；
 *   ② 读了安装的 Vue 3.5.44 的源：`isSpecialBooleanAttr` 的名单是
 *      itemscope/allowfullscreen/formnovalidate/ismap/nomodule/novalidate/playsinline/readonly，
 *      `aria-pressed` 不在内 ⇒ patchAttr 走 `el.setAttribute(key, value)` 而不是删属性；
 *      只有 `null`/`undefined` 才 removeAttribute。
 * ⇒ 布尔绑定已经会渲出显式的 `aria-pressed="false"`，三档都是“开关”而不是“一个开关 + 两个普通按钮”。
 *      上一段那句错话的代价不是界面坏了，而是**界面本来是对的、注释把它说成了另一个机制**。
 * ==========================================================================-->
<script setup lang="ts">
import { setTheme, themeMode, type ThemeMode } from '../theme'

/* 档位顺序 = 语义顺序（默认档在前），不是字符串排序。
 * 文案与值的对应是死的：'system' 那句在人眼里是「自动」，但它跟的是**系统偏好**，
 * 所以这里写「跟随系统」——POC 页上那句「自动」是被截短的说法。 */
const MODES: readonly { readonly mode: ThemeMode; readonly label: string }[] = [
  { mode: 'system', label: '跟随系统' },
  { mode: 'light', label: '浅色' },
  { mode: 'dark', label: '深色' },
]
</script>

<template>
  <div
    class="seg"
    role="group"
    aria-label="主题"
  >
    <button
      v-for="item in MODES"
      :key="item.mode"
      type="button"
      class="btn"
      :aria-pressed="themeMode === item.mode"
      @click="setTheme(item.mode)"
    >
      {{ item.label }}
    </button>
  </div>
</template>
