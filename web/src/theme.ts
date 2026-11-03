/* ============================================================================
 * theme.ts — 主题档位的单一落点
 * 机制（视觉件 §1.5）：`:root` = light；系统深色经 `@media (prefers-color-scheme: dark)`
 * 作用在 `:root:not([data-theme])` 上；**只有手动切换才写 `data-theme`**。
 * ⇒ 「跟随系统」这一档的实现方式是**移除属性**，不是写一个 'auto' 值：
 *   写了 data-theme="auto" 会让 :not([data-theme]) 整条媒体查询失配，
 *   于是"跟随系统"变成一个什么都不跟的档位 —— 症状是深色系统下仍是浅色。
 * 边界（视觉件 §1.6）：主题偏好不是凭据，所以它可以落 localStorage；
 *   工单件 §2.3 那条「密钥只存内存」的纪律不被这里绕过。
 * ==========================================================================*/
import { ref } from 'vue'

export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'ap.ui.theme'

function isThemeMode(v: string | null): v is 'light' | 'dark' {
  return v === 'light' || v === 'dark'
}

/** 存储读不到（隐私模式 / 禁用存储）按 system 处理，不抛：首屏配色不该依赖一个可选偏好。 */
function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return isThemeMode(v) ? v : 'system'
  } catch {
    return 'system'
  }
}

/** 当前档位。响应式，所以切换控件与页面文案读同一个值，不各存一份。 */
export const themeMode = ref<ThemeMode>('system')

function applyToDocument(mode: ThemeMode): void {
  const root = document.documentElement
  if (mode === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', mode)
}

/** 启动时同步调用（在 createApp 之前），保证首帧就带正确档位。 */
export function initTheme(): void {
  themeMode.value = readStored()
  applyToDocument(themeMode.value)
}

export function setTheme(mode: ThemeMode): void {
  themeMode.value = mode
  applyToDocument(mode)
  try {
    if (mode === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // 存不进去时**不假装记住了**：本会话内切换仍生效，刷新后回到跟随系统。
    // 这里不弹错误也不降级档位 —— 用户要的是这一屏的配色，持久化失败不是配色失败。
  }
}
