/* ============================================================================
 * vite.config.ts — 构建期配置（Node 只活在这里，运行时镜像里没有 Node）
 * 工单件 §9.2 定死的两条：
 *   ① base 必须是 '/ui/'：产物由 agent_server 挂在 /ui 下（§9.1），写错成 '/' 时
 *      静态资源全 404，而症状看起来像"打包失败"——这是最难归因的一种失败。
 *   ② dev 代理**默认**指向 127.0.0.1:8000；默认值只写回环，web/ 内不得出现内网
 *      主机名/网段（AGENTS.md《分支卫生》#4，公开镜像闸门会扫这里）。
 *
 * 2026-11-16 起代理目标可用 VITE_DEV_BACKEND 覆盖：本机起 Vite 连**已部署**的服务
 * 验证前端改动，不再为看效果走完整构建/分发/rollout。真值由执行时从环境变量给，
 * **不入库**——默认值仍是回环，公开镜像零真值。
 *   ⚠ 用 Vite 自带的 loadEnv 而不是 process.env：本仓刻意不装 @types/node
 *     （.mjs 脚本是纯 JS），直接写 process.env 会让 typecheck 报 TS2591。
 *   用法：VITE_DEV_BACKEND=http://<internal-host>:30080 pnpm dev
 * ==========================================================================*/
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

/* Vite 8 的 configure 回调参数来自 http-proxy-3 的 ProxyServer，它 extends 一个依赖
 * @types/node 的 EventEmitter；本仓刻意不装 @types/node ⇒ 类型面看不到 .on。
 * 运行期对象确实有 .on（http-proxy-3），这里只声明本配置用到的两个事件与两个字段，
 * 用一次窄化 cast 避开缺失的 node 类型，不引入 any、不改 lockfile。 */
type SseProxyReq = { setHeader(name: string, value: string): void }
type SseProxyRes = { headers: Record<string, string | string[] | undefined> }
type SseProxyHooks = {
  on(event: 'proxyReq', listener: (proxyReq: SseProxyReq) => void): void
  on(event: 'proxyRes', listener: (proxyRes: SseProxyRes) => void): void
}

/* 代理这些前缀的理由：CORS 只放行了 5173（agent_server/config.py 的 cors_allow_origins），
 * 而 /query 是 SSE。/query 已从通用数组拆出、单独配防缓冲（见下方 configure）；
 * http-proxy 默认不缓冲响应体，但上游若对 text/event-stream 启用 gzip，开发期会看到
 * 「事件一次性到达」——这里显式要求 identity 并透传防缓冲头。形状由 check-events.mjs
 * 的齿 C6 锁住，逐帧到达仍需本地联调人工确认（verify:sse 不测代理）。
 * `/auth` 是登录面四个端点的前缀（`/auth/login`|`/auth/register`|`/auth/me`|
 * `/auth/logout`）；`src/api/auth.ts` 写的是绝对路径 ⇒ 开发期不经代理就是 5173 的 404。 */
const proxied = ['/history', '/health', '/session', '/console.html', '/auth', '/kb', '/datasources']

export default defineConfig(({ mode }) => {
  // envDir 传 '.'（相对 vite 启动目录 web/），不写 process.cwd() —— 后者要 @types/node。
  const DEV_BACKEND = loadEnv(mode, '.', 'VITE_').VITE_DEV_BACKEND || 'http://127.0.0.1:8000'
  return {
    base: '/ui/',
    plugins: [vue()],
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
    server: {
      port: 5173,
      proxy: {
        ...Object.fromEntries(
          proxied.map((p) => [p, { target: DEV_BACKEND, changeOrigin: false }]),
        ),
        // SSE 专用。changeOrigin 保持 false：原配置的 Host/来源语义不动，只加防缓冲。
        '/query': {
          target: DEV_BACKEND,
          changeOrigin: false,
          configure: (proxy) => {
            const hooks = proxy as unknown as SseProxyHooks
            hooks.on('proxyReq', (proxyReq) => {
              proxyReq.setHeader('Accept-Encoding', 'identity')
            })
            hooks.on('proxyRes', (proxyRes) => {
              const contentType = proxyRes.headers['content-type']
              if (typeof contentType === 'string' && contentType.includes('text/event-stream')) {
                proxyRes.headers['cache-control'] = 'no-cache'
                proxyRes.headers['x-accel-buffering'] = 'no'
              }
            })
          },
        },
      },
    },
  }
})
