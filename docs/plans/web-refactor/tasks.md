# web/ 前端内部重构 — Tasks（工单）

> 依赖 `spec.md`（做什么）与 `design.md`（怎么改 / 对账结论）。**状态：待拍板，未开工。**
> R1–R5 = 用户清单的 PR 1–5（改名原因见 `design.md` 头部）。每个 R 对应一个短命 PR。
> **开工前置**：`design.md` §2.3 中影响该 R 的决策已拍板；未拍板的 R 不得开始。

---

## 0. 开工前置（一次完成，不属任何 R）

- [x] T0-1 拍板 D-1：hash 模式，保留 `/ui/*` 404 判据。
- [x] T0-2 拍板 D-2：接受翻转 `index.html` 无内联脚本决策；R1 随动登记理由。
- [x] T0-3 拍板 D-3：只写部署前置条件，不改不存在的文件。
- [x] T0-4 拍板 D-4：原子迁移、无兼容 shim。
- [x] T0-5 拍板 D-5 / D-5b：测"不丢字"；无障碍仅 ImageStrip lightbox。
- [x] T0-6 已在 `docs/README.md` §3.9 索引表登记本方案三件；`check_doc_sync.py` rc=0（0 警告）。
- [x] T0-7 已记录开工前 HEAD `4c074f3716e93ecb5c2b60bb10f00ed3d9edac9d` 与七门基线读数（逐条 rc），见 `design.md` §7；读数绑件名 + sha。

---

## R1 — 消除首帧闪白与加固 CSS 层叠（原 PR 1 · 低风险但含一项决策翻转）

**依赖**：T0-2（D-2）。**门禁**：`pnpm typecheck && pnpm lint && pnpm check:tokens && pnpm check:ui-consistency`。

- [x] R1-1 在 `web/index.html` `<head>` 顶部插入同步 IIFE：
  - 读取 `ap.ui.theme`（**不是** `ap.theme`）；
  - `dark` → 写 `data-theme="dark"`；`light` → 写 `data-theme="light"`；`system`/无值 → 不写；
  - try/catch 包住存储读取，失败按 system；不得写 `data-theme="auto"`。
  - 同步把翻转理由写入 `web/README.md` 与视觉件对应条目（D-2 的登记义务）。
- [x] R1-2 更新 `web/src/main.ts` 头注：从"已知闪帧"改为"首帧已同步定档，应用侧复核"；保留 `initTheme()` 在 `createApp()` 之前的顺序。
- [x] R1-3 在 `web/src/styles/tokens.css` 顶部声明 `@layer tokens, base, events;`，三件样式分别包裹到对应层；**不重排内部缩进**（保护 `check-tokens` 断言 5 锚点）。
- [x] R1-4 保留 `base.css` 中 `.is-active` 的顺序纪律与门禁：`@layer` 只解决跨层覆盖，不宣称解除 base 内部同权重依赖。
- [x] R1-5 跑门禁；若断言 5 锚点漂移，**改锚点不改判据强度**，并加一枚合成违规样本自证能咬（注一条色值字面量必须判红）。
- [x] R1-6 复取 V4 视觉读数（双主题 × 三断点），确认无新增横向滚动/叠字；读数绑本次 HEAD。

**验收**：深色系统首帧为深色；深色系统 + 手动浅色首帧为浅色；四门全 rc=0；锚点迁移带反证。
**回滚**：按 R1 单批 revert；恢复 `index.html` 头注与三件样式原状。

**R1 完成记录（2026-11-23，HEAD `dd8b2dd41b33d99fffed79113a2582691025eed0`）**：`typecheck` / `lint` / `check:tokens`（定义 123 / 引用 123）/ `check:ui-consistency`（`.is-active` 单一实现、合成反证已咬）四门 rc=0；额外 `pnpm build` 通过（CSS 30.66 kB / JS 151.48 kB）。首档同步脚本一次性行为探针 4/4 通过（dark/亮系统→dark；light/深系统→light；无偏好与 system→不写属性）。**未达**：V4 双主题 × 三断点实拍 harness 在本机不存在（`.tmp-scratch/ap-visual/` 未随仓库带来），故视觉判据未复取，不写成"已过"。

---

## R2 — 锁定 SSE 开发代理与生产防缓冲前置（原 PR 2 · 低风险）

**依赖**：T0-3（D-3）。**门禁**：`pnpm verify:sse && pnpm check:events && pnpm typecheck`。

- [x] R2-1 `web/vite.config.ts`：把 `/query` 从 `proxied` 数组拆出单独配置；**继续用 `loadEnv`**（不写 `process.env`）、**保持 `changeOrigin: false`**。
- [x] R2-2 `configure` 钩子：`proxyReq` 设 `Accept-Encoding: identity`；`proxyRes` 仅对 `content-type` 含 `text/event-stream` 写 `cache-control: no-cache` 与 `x-accel-buffering: no`；其余 5 个前缀不动。
- [x] R2-3 在 `web/scripts/check-events.mjs` 增加代理形状齿：真面读 `vite.config.ts`；固定合成违规（缺防缓冲头 / 压缩未关）必须判红；遵循 AGENTS 第 8 条（真面参与判决 + 自证能咬）。**不新建门禁文件**。
- [x] R2-4 `web/README.md` 增"生产前置条件"段：当前部署链无 HTTP 反代（NodePort 直通、无 Ingress、`deploy/k8s` 不入库）；若日后引入反代，`/query` 须 `proxy_buffering off` 与 gzip off，列为开工前置而非事后排查。**不凭空创建 Nginx 配置文件**。
- [x] R2-5 本地联调 `pnpm dev` + `VITE_DEV_BACKEND`，人工确认时间线逐条出现；把"逐帧到达"记为人工验收项，不写进 `verify:sse` 的能力声明。
- [x] R2-6 跑三门；确认 `verify:sse` 未被误用于证明代理行为。

**验收**：代理配置形状门带反证；三门 rc=0；生产侧以前置条件文档落地。
**回滚**：恢复 `vite.config.ts` 的 `proxied` 数组形态；移除 `check-events.mjs` 新齿与文档段。

**R2 完成记录（2026-11-23，HEAD 见提交 `refactor/web-frontend-r1`）**：`typecheck` / `lint` / `verify:sse`（153 条断言，失败 0）/ `check:events`（齿 C6 `/query` 独立配置 + identity + 防缓冲头 ✅）四门 rc=0。类型面适配：Vite 8 用 `http-proxy-3`，其 `ProxyServer.on` 的类型依赖本仓刻意不装的 `@types/node`（`vite/dist/node/index.d.ts:698,788`；运行期调用点 `vite/dist/node/chunks/node.js:19899-19901`），故用一次性窄化 cast 声明两个事件与两个字段，不引入 `any`、不改 lockfile。
**本地联调（一次性探针，不入库）**：v1 探针在响应头到达时即断言，只读到首帧 ⇒ 2 格假红；v2 用「直连后端 vs 经代理」对照定位为探针 bug（两者都分批）；v3 等 `end` 后 6/6 通过：`Accept-Encoding: identity`、`content-type: text/event-stream`、`cache-control: no-cache`、`x-accel-buffering: no`、收到 3 帧、块到达 0/267/476ms（间隔 267/209ms）。生产侧当前无反代，以前置条件文档落地，未做生产验证。

---

## R3 — 状态管理迁至 Pinia（原 PR 3 · 中风险）

**依赖**：T0-4（D-4）。**门禁**：`pnpm typecheck && pnpm lint && pnpm verify:sse && pnpm verify:markdown`。

- [ ] R3-1 `pnpm add pinia --save-exact`；`pnpm-lock.yaml` 由命令生成并入库；`web/src/main.ts` 在挂载前注册 `createPinia()`。
- [ ] R3-2 新建 `web/src/stores/sseReducer.ts`：迁入 `EVENT_HANDLERS`、`applyFrame`、`initialState`、纯类型，以及 `pushBanner`（8 条上限、去重、溢出计数）。契约保持纯函数、不碰网络/DOM/全局状态。
- [ ] R3-3 `web/src/api/sse.ts` 改为 import reducer；**不留 re-export 兼容 shim**（D-4）；网络层职责不变。
- [ ] R3-4 `web/src/stores/session.ts` 改写为 Pinia store：保留登录态机、`hasFeature` 单一问法、8 条 banner、登录态切换清 banner 不清时间线、`ap.auth.token` 唯一装配位不变、features 不落存储。
- [ ] R3-5 `web/src/stores/conversations.ts` 改写为 Pinia store，直接 `useSessionStore()` 取当前会话 id 与 `resetRound`；删除 `web/src/App.vue` 中 `ask(undefined, sid)` 的中转胶水。
- [ ] R3-6 `web/src/stores/kbHistory.ts` 保持纯函数缓存层（现状无响应式状态），不强行包 store；在消费点接 store。
- [ ] R3-7 `web/scripts/verify-sse.mjs`：import 路径改到 reducer；驱动会话层前 `setActivePinia(createPinia())`；§H 的 banner/登录态用例复跑通过。
- [ ] R3-8 `web/scripts/check-events.mjs`：`TS_SSE` 坐标与 `EVENT_HANDLERS` 正则来源改到 reducer；双向比较与存储白名单强度不变；加合成违规（删一个 key）自证能红。
- [ ] R3-9 跑四门；确认 `verify:markdown` 未受影响。

**验收**：三个 store 无旧单例兼容层；"谁写谁读谁清空"可在 `design.md` §4.2 表中逐行对上；两个门禁同批迁移且反证有效。
**回滚**：R3 整批 revert（含 lockfile）；不可只回退 store 而留半迁移的门禁坐标。

---

## R4 — 引入 Vue Router（原 PR 4 · 中风险，含 D-1 决策）

**依赖**：T0-1（D-1）、R3（守卫读 Pinia 状态）。**门禁**：`pnpm typecheck && pnpm lint && pnpm check:ui-consistency`。

- [ ] R4-1 `pnpm add vue-router --save-exact`；lockfile 入库。
- [ ] R4-2 新建 `web/src/router/index.ts`：`createWebHashHistory('/ui/')`（D-1 推荐）。路由：`/ → /chat`、`/chat/:sessionId?`、`/role`(feature)、`/kb`(kb.upload)、`/datasource`(datasource.manage)、`/health`。
- [ ] R4-3 `router.beforeEach` 复用 `hasFeature`（唯一问法），不新写第二份判定；能力码未回读时不得永久重定向；`/health` 对所有已登录用户开放。
- [ ] R4-4 从 `web/src/App.vue` 拆出 `ChatView.vue`（三栏 + 提交区 + 过程抽屉），App.vue 退为框架 + `<RouterView>`；删除 `ap.ui.view` 读写与 `activeView/effectiveView`。
- [ ] R4-5 URL 与会话联动：`:sessionId` 变化驱动 conversations store 选中；未知 id 回落默认选择且不白屏；菜单选中态继续用 `.is-active`（单一实现）。
- [ ] R4-6 保留 `/ui/*` 未知路径 404 判据；**不改后端托管语义**，除非 D-1 另选 history 并单独写 ADR。
- [ ] R4-7 跑三门；手动验证：前进/后退、深链刷新、无权限回落、未知会话 id 回落。

**验收**：5 视图 URL 可达；刷新直达；前进/后退还原；404 判据仍成立；`check:ui-consistency` 仍咬。
**回滚**：R4 整批 revert（含 lockfile 与 App.vue 拆分）；恢复 `ap.ui.view` 前先确认 R3 的 store 仍自洽。

---

## R5 — 组件边界治理与文档同步（原 PR 5 · 低风险）

**依赖**：T0-5（D-5 / D-5b）、R1–R4 已合。**门禁**：全量（见下）。

- [ ] R5-1 `web/scripts/verify-markdown.mjs` 扩测：代码块围栏边界、行内码、未闭合标记按文本保留、XSS 串当文本；新增"表格/多级缩进列表按纯文本逐行显示且不丢字"的边界断言（D-5a）。**不实现新语法**。
- [ ] R5-2 `web/src/components/ImageStrip.vue` lightbox：`aria-modal="true"` + `aria-label`、Escape 关闭、打开时焦点锁定、关闭后焦点归还缩略图按钮；非模态 `<details>` 抽屉不套 focus trap（D-5b）。
- [ ] R5-3 行为验证沿用既有 CDP harness（gitignored 一次性工具），结构断言并入既有门禁；不引入 DOM 测试库（避免改 lockfile 与内网构建链）。
- [ ] R5-4 根 `README.md:508` 改为 Vue 3 + Vite + TypeScript 单页应用表述，与 `web/README.md` 一致。
- [ ] R5-5 清理 `web/src/App.vue:10` 的"没有会话历史列表"过时注释。
- [ ] R5-6 全量门禁：
  `pnpm typecheck && pnpm lint && pnpm check:tokens && pnpm check:events && pnpm check:ui-consistency && pnpm verify:sse && pnpm verify:markdown`
- [ ] R5-7 按 `docs/operations/evidence-format.md` 五字段写完成记录；区分"代码已交 / 门禁已跑 / 验收已过"。

**验收**：七门全 rc=0；Markdown 不支持语法不丢字；XSS 仍为文本；弹层可键盘退出；文档与实物一致。
**回滚**：R5 单批 revert。

---

## 需求 → 工单覆盖检查

| Spec 能力 | 对应工单 |
|---|---|
| §5.1 无闪白首屏与稳定层叠 | R1-1…R1-6 |
| §5.2 流式不缓冲 | R2-1…R2-6 |
| §5.3 单一状态源与会话连贯 | R3-1…R3-9 |
| §5.4 可深链视图导航 | R4-1…R4-7 |
| §5.5 组件边界与文档一致 | R5-1…R5-7 |
| §4 DFX / 不变量 | 每 R 门禁 + `design.md` §1.4 |
| §6 数据约束 | R1-1 / R3-4 / R3-5 / R3-6 / R4-5 |

## 交付纪律

1. 每个 R 一个短命分支：< 24h、PR < 400 行、合回后即删死枝；合 `main` 须用户显式批示。
2. 远端名先 `git remote -v` 现取（本仓无 `origin`）；公开镜像分支另算，不混入计数。
3. 门禁红时改产品代码到契约要求；**禁止删用例 / 收窄断言 / 放宽前置条件凑绿**。
4. 新增或迁移的判据必须同批带自证能咬；否则按"门禁瞎"处理。
5. 完成陈述带 HEAD sha + 件名 + 逐条 rc；不把历史读数搬进当前账面。

---

## R4 / R5 扩展项（2026-11-23 新稿，**待 D-6 / D-7 / D-8 拍板，不进当前开工项**）

> 对账见 `design.md` §8；需求见 `spec.md` §7。**D-6 / D-7 / D-8 已于 2026-11-23 按推荐拍板**（见 `design.md` §8.3）；以下项按各自所属 R 的排期推进。

**R4 扩展（依赖 D-6）**

- [ ] X-1 评估并实现跨标签令牌协商：维持 sessionStorage 档位，用 BroadcastChannel 在仍打开的老标签与新标签间传递令牌；无老标签时回落登录面。**不改 `ap.auth.token` 的档位与写入点**，不触碰 `check-events.mjs` C2 与 `verify-sse.mjs` I1c/I12。
- [ ] X-2 把"所有标签关闭后首次直达仍需登录"作为产品限制写入 `web/README.md` 与帮助文案，不靠放宽门禁掩盖。

**R5a 引用联动（依赖 D-7 / D-8）**

- [ ] X-3 `InlineTokens.vue` 解析 `[1]` 为按钮（hover 预览、click 锚定）；`Answer.vue` 持 `activeEvidenceIndex` / `isEvidenceExpanded` 局部态。
- [ ] X-4 `EvidenceList.vue` 自动展开并平滑滚动 + 1.8s 高亮脉冲；`Timeline.vue` 支持从证据卡片反向高亮 stepId；高亮色只引 `tokens.css` 语义令牌。
- [ ] X-5 `streamQuery` 增 `AbortController` signal 支持"停止生成"；错误改为单轮内联重试，全局 banner 语义变更时同批迁移 `verify:sse` 断言并加反证（改形状≠放宽）。

**R5b 阅读密度与配置闭环（依赖 D-7）**

- [ ] X-6 对话视图去外层描边、正文宽 760–840px、中等断点折叠侧栏；过 `check:tokens` 与 V4 实拍。
- [ ] X-7 `KbUpload.vue` 索引完成时提供"在对话中使用此知识库"跳转，并把选中知识库带入对话页。

**R5c a11y 与文档（原 R5 内容，依赖 D-7 决定编号）**

- [ ] X-8 保留原 R5-1…R5-7 全部项（Markdown 边界、ImageStrip lightbox 无障碍、根 README 与 App.vue 过时注释清理、全量门禁）。
