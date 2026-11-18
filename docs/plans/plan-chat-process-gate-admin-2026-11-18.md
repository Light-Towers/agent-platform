# 对话页：过程信息收进 admin 专属开关

> 状态：代码完成 + 静态门禁全绿，真浏览器验证因夜间服务器不可达改期（2026-11-19 早补验 + 部署）。触发：用户指出对话返回/展示了一大堆内部过程事件，普通用户只该看到答案；证据/时间线/图例收进一个按钮（悬浮/点击展开），且**仅 admin 角色**可见。

## 根因 / 现状（实取确认）
一次真实对话（"你好"）SSE 返回 6 帧：`route`（路由决策）、`memory`（历史记忆）、`evidence`（命中依据）、`status`（token 用量/步骤）、`answer`（正文答案）、`done`（终止帧）。复杂问题还会有 `replan`/`suspended`/`error`/`admission`/`coordination`/`cache_hit`。
- 后端核心 8 类事件定义在 `packages/agent-runtime/.../planner/protocol.py`，前端加 4 类共 12 类（`web/src/api/events.ts`）。
- 前端现状：答案在中间 `chat-shell__main`（Answer.vue），过程信息在右侧 `chat-shell__inspector`（依据列表 + 事件时间线，两个 `<details>` 默认收起）+ 底部常驻 `Legend`（12 类图例）+ 中间一条 `traceNote`（请求号，调试用）。**所有用户都能看到这些过程面板**。

## 决策（用户 2026-11-18 拍板）
1. 默认界面只展示答案（普通用户全程只看答案）。
2. 证据列表 / 事件时间线 / 图例 / 请求号 收进一个「查看过程」开关，点击展开、再点收起。
3. 该开关**仅 admin 角色可见**；viewer 角色界面上完全没有过程入口。
4. 只改前端展示层：后端 SSE 仍下发全量帧（评测/可观测/门禁需要），事件定义、图例字典、Legend.vue 组件本身都不删不改名。

## 实现
- `session.ts` 已有 `authRole`（服务端回读的角色码）。App.vue 加 `canInspect = computed(() => authRole.value === 'admin')` + 局部 `showInspector = ref(false)`。
- App.vue 中间栏加「查看过程（证据/事件）」按钮（`v-if="canInspect"`）；traceNote / inspector / Legend 全部加 `v-if="canInspect && showInspector"`。
- inspector 不显示时 grid 从三列变两列（`.chat-shell--no-inspector`），避免右侧空出 300px。
- 不碰 `events.ts` / `Legend.vue` / 后端 Literal（门禁 6 读这些，保持原样即绿）。

## 安全边界（如实记录）
前端隐藏是**展示层**，不是安全边界：`/query` 的 SSE 仍把 route/evidence 等帧下发给所有角色。要真正做到"普通用户 API 层拿不到证据"，须后端按角色过滤事件帧（本次不做，另议）。

## 验证
- ✅ 静态全绿（2026-11-18 晚）：typecheck / lint / 6 视觉门禁（check-tokens，定义 123/引用 123、事件双向比较过）/ ruff / doc-sync。
- ⏳ 真浏览器验证改期 2026-11-19 早：夜间服务器 SSH 超时、`/auth/login` HTTP=000（5173 代理到后端不通），CDP 无法登录取 DOM。脚本已备好 `C:\...\Temp\opencode\cdp_role_gate.mjs`（注入 fetch patch 改 auth 响应 role，独立端口 9337，不碰用户 9222 agent、不碰数据库），明早服务器可达后跑：viewer 只看答案/无过程入口，admin 有开关、点击展开/收起。
- 部署也改期明早：本改动纯前端展示层，需重建+分发平台镜像（KS 无改动）后 rollout；临时提权 e2e_probe_7q3 验后降回。
- 注：本次 server 不可达同时挡住了上一批「知识库三级结构」的部署（commit df00e090），两批可一起明早部署。
