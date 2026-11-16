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

/* 代理这些前缀的理由：CORS 只放行了 5173（agent_server/config.py 的 cors_allow_origins），
 * 而 /query 是 SSE。此处只登记**未验证的风险**：http-proxy 默认不缓冲响应体，但若后端对
 * text/event-stream 启用了 gzip，开发期会看到「事件一次性到达」而现网是逐帧到达。
 * PR-1 接 SSE 时必须实测这条（判据 = 屏上时间线逐条出现），届时再决定要不要加处置；
 * 不在这里预先写上没验证过的解法。
 * `/auth` 是 PR-2b 登录面四个端点的前缀（`/auth/login`|`/auth/register`|`/auth/me`|
 * `/auth/logout`）；`src/api/auth.ts` 写的是绝对路径 ⇒ 开发期不经代理就是 5173 的 404。 */
const proxied = ['/query', '/history', '/health', '/session', '/console.html', '/auth', '/kb', '/datasources']

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
      proxy: Object.fromEntries(
        proxied.map((p) => [p, { target: DEV_BACKEND, changeOrigin: false }]),
      ),
    },
  }
})
