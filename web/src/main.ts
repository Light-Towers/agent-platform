/* ============================================================================
 * main.ts — 样式与主题的**唯一**入口（视觉件 §1.1「全局装配层」的那一层）
 * 两条顺序都是正确性的一部分，别挪：
 *   ① tokens → base → events 的导入顺序。events.css 里有与 base.css 同特异度的
 *      选择器（POC 实踩：灯阵的断点覆盖写在 base 里永不生效，见 base.css 断点段那条
 *      ⚠ 注记）。顺序换一下，赢的那份就换人 —— 而 CSS 不会报错，只会长得不一样。
 *   ② initTheme() 必须在 createApp() **之前**同步调用。它写的是 <html> 上的属性，
 *      而深色/浅色是靠属性存在与否匹配的；挂载后再调，首帧就按默认档位画了一次，
 *      症状是深色系统下刷新会闪一下浅色。代价登记在 index.html 头注①：
 *      壳内不放内联脚本，所以这一闪是本设计的已知、已选后果，不是缺陷。
 * ==========================================================================*/
import './styles/tokens.css'
import './styles/base.css'
import './styles/events.css'

import { createApp } from 'vue'
import App from './App.vue'
import { initTheme } from './theme'

initTheme()

createApp(App).mount('#app')
