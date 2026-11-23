/* ============================================================================
 * main.ts — 样式与主题的**唯一**入口（视觉件 §1.1「全局装配层」的那一层）
 * 两条顺序都是正确性的一部分，别挪：
 *   ① tokens → base → events 的导入顺序。events.css 里有与 base.css 同特异度的
 *      选择器（POC 实踩：灯阵的断点覆盖写在 base 里永不生效，见 base.css 断点段那条
 *      ⚠ 注记）。顺序换一下，赢的那份就换人 —— 而 CSS 不会报错，只会长得不一样。
 *   ② initTheme() 必须在 createApp() **之前**同步调用：index.html 头部的同步脚本
 *      已在首帧前把手动偏好落到 <html>，这里做应用侧复核（同一 key、同一属性名），
 *      并初始化 themeMode 响应式值。挂载后再调会让响应式视图与文档属性短暂分叉。
 *      ⚠ 2026-11-23 D-2 已拍板翻转原「壳内不放内联脚本、接受首帧闪一次」取舍；
 *      旧取舍与翻转理由见 web/README.md 与视觉件 §1.5。
 * ==========================================================================*/
import './styles/tokens.css'
import './styles/base.css'
import './styles/events.css'

import { createApp } from 'vue'
import App from './App.vue'
import { initTheme } from './theme'

initTheme()

createApp(App).mount('#app')
