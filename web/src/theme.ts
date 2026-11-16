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

/* ---- 非凭据 UI 状态的 localStorage 唯一装配位 ----
 * 工单件 §2.3 的存储纪律是「凭据只存内存/sessionStorage、不许散落」，由 check-events.mjs
 * 的存储白名单（auth.ts / theme.ts）把写入收敛到这两件。上传历史（kbHistory.ts）与当前
 * 会话选中态（conversations.ts）都是**非凭据 UI 偏好**，与主题同类，故把通用的字符串读写
 * 收敛到这里，消费件只调本函数、不自己碰 localStorage.*——这样存储写者不越白名单，
 * 门禁语义（谁能写存储）不被削弱，凭据（ap.auth.token 在 auth.ts 的 sessionStorage）不受影响。
 * ⚠ 只准存非凭据值：调用方传进来的必须能 JSON 序列化，且不得含令牌/口令。 */
export function readUiState(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeUiState(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // 配额满/隐私模式：UI 偏好存不下不影响主流程
  }
}
