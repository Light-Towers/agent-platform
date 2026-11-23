/* ============================================================================
 * tabSync.ts — D-6 跨标签令牌协商（保持 sessionStorage 档位与唯一写入点不变）
 *
 * 新标签打开深链时广播 request；仍开着且已登录的老标签回 share。
 * 令牌永不落 localStorage、不写 cookie，档位与 check-events C2 / verify-sse I1c/I12 不变。
 * 所有标签都关掉后首次直达仍须登录 —— 这是产品限制，写进 web/README.md。
 * Node 下（verify-sse）window 不存在 ⇒ 全程 no-op，不给门禁引入异步副作用。
 * ==========================================================================*/
import { readStoredToken } from './auth.ts'

const CHANNEL = 'ap.auth.token.sync'

type Msg = { kind: 'request' } | { kind: 'share'; token: string }

let channel: BroadcastChannel | null = null
let deliver: ((token: string) => void) | null = null

function getChannel(): BroadcastChannel | null {
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') return null
  if (channel === null) {
    channel = new BroadcastChannel(CHANNEL)
    channel.onmessage = (event: MessageEvent<Msg>) => {
      const msg = event.data
      if (msg?.kind === 'request') {
        const token = readStoredToken()
        if (token !== '') channel?.postMessage({ kind: 'share', token })
      } else if (msg?.kind === 'share' && typeof msg.token === 'string') {
        deliver?.(msg.token)
      }
    }
  }
  return channel
}

/** 会话层在 store setup 里注册收到 share 后的处理（仍是同一份 store 状态的写入）。 */
export function onSharedToken(fn: (token: string) => void): void {
  deliver = fn
}

/** 登录成功后把令牌告诉其它标签。 */
export function announceToken(token: string): void {
  getChannel()?.postMessage({ kind: 'share', token })
}

/** 新标签无本地令牌时请求老标签共享。 */
export function requestToken(): void {
  getChannel()?.postMessage({ kind: 'request' })
}
