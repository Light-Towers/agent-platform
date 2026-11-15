# 前端技术栈选型（roadmap #18 前半「方案评审（含技术选型）」）

- 状态：**已拍板（2026-10-29，用户原话"行，那就最终定Vue"）——终态栈 = Vue3**；拍板范围**仅栈一项**。原状态"推荐已出…待拍板"自本行解除；三轮判据收敛过程与决策日志见 §8，**不得因已拍板而删**（它是防再摇摆的唯一依据）。ADR-0010 的未决状态已由该 ADR §6（同日追加）落地为已决 C。⚠ 本文 §7 第 2 点存有一处**未被人发现的同名异义**（此处的"A 方案"与 `packages/agent-core/agent_core/guardrails/errors.py:15-16` 定案的"D-2=A"含义**恰好相反**），已在 §7 就地标注，引用该点时不得裸写"A"
- 日期：2026-10-27
- 来源：roadmap `plan-production-delivery-roadmap-2026-10-09.md` #18 改法前半 + `docs/TODO.md` §1 前端待办第 1 条 + `docs/adr/0010-ui-stack-selection.md` §5 待用户回答
- 关联：ADR-0010（A/B/C 三选项与重启条件）· `docs/plans/plan-frontend-error-contract-audit-2026-10-19.md`（错误契约是前端工程前置）· `docs/research/competitive-landscape.md`（定位边界）

## 0. 结论（先看这里）

> **判据演化（2026-10-27，三轮，完整日志见 §8）**：① 初版按「内部工具」推 → Vue3；② 用户明确**开源项目**（GitHub `Light-Towers/agent-platform`）→ 同类目开源实践加权，改判 React；③ 用户再明确**不做流程拖拽、目标是企业 agent 平台** → 画布支柱死亡 + 决策回到「企业工具型管理台选维护成本最低栈」→ **翻回 Vue3（终态推荐）**。每次改判都是判据集变了，不是偏好摇摆。

**推荐三句话：**

1. **落地路径选 C**（ADR-0010 的 C 选项）：#18 验收用**现有 `console.html` 补证据链**（它已实现 提问→SSE 过程时间线→结果→错误提示），**不为 #18 引入工具链**；Phase 3 产品化再立独立 `web/` 工程。理由：#18 判据明文「不新增后端专用接口」+ 现有页面已覆盖主链路，先引工具链属于把 10 人/日里的一半花在脚手架上，对判据零贡献。
   > **⚠ 2026-10-29 取证实测订正本条**：原文此处写的"缺的只是 `/session/revert` 交互与「截图+日志」留证"**错了两处**：① roadmap #18 判据四步（提问→执行→展示过程与结果→错误提示）**不含回退**，`/session/revert` 是 `docs/TODO.md:95` 给**新前端**列的复用接口，不是取证必做项；② 给只读控制台加写入口违反**基线 6**，已被 `applications/agent_server/tests/test_console_router.py:22` 钉为禁项（2026-10-29 实跑 2 failed 后全量回退）。⇒ 正解：#18 **零代码改动即可取证关断**；revert 交互归 `web/`，且其开工受 `checkpoint_id` 不可得的缺口前置（见实施件 §11.5）。
2. **前端框架选 Vue 3 + Vite + TypeScript + Element Plus + Pinia（图表 vue-echarts/ECharts）**，不选 React/Next.js、不选 Svelte。理由：① 无画布的企业管理台形态（70% RBAC/租户/审计/成本/审批队列 CRUD + 30% 聊天流）是 Element Plus 最高产的领域，且是中文企业级管理台生态的事实标准（若依系）；② 维护者侧收益是当下确定的——公司 FastAPI+Vue3 先例、无专职前端 + AI 辅助下 SFC+EP 单一写法生成最稳；③ React 案的画布支柱（@xyflow）因「不做流程拖拽」出界，Langflow 的 UI 身份即画布、相似度降档，真正要借的模式（TanStack Query↔Vue Query、Zustand↔Pinia、执行时间线）均有 Vue 成熟平移解；④ Next.js 依旧否决（SSR/SEO 零收益 + 开源自部署多一个 Node 运行时面）。
3. **工程形态：单仓单 SPA**（根 `web/`，pnpm，路由分模块覆盖 6 应用页面）+ **OpenAPI 类型生成**（FastAPI 自带 schema → 生成 TS 客户端与错误类型）+ **生产由 FastAPI 托管 dist**（多阶段 Dockerfile，Node 只活在构建阶段——126 宿主无 Node、代码走 `git bundle`+`scp` 的事实决定的）。**框架无关，三轮判据演化均不动本条。**

一句话版：**栈定 Vue3；范围明确不做流程拖拽；节奏是「console.html 出 #18 证据 → web/ 产品化」；引入前端工程与补 CI 门禁、收敛错误契约三件事必须同批，否则不做。**

## 1. 选型输入（判据从需求与事实推导，不从偏好推导）

| 维度 | 事实（出处） | 对选型的约束 |
|---|---|---|
| 项目类型 | 统一生产级 Agent 平台 monorepo（纯 Python uv workspace，6 应用），**开源项目**（GitHub `Light-Towers/agent-platform`，Apache-2.0 公开脱敏镜像，受众 = 外部采用者/贡献者 + 内部生产双用），目标定位**企业 agent 平台**（非低代码构建器，用户 2026-10-27 明确），差异化在「运行时工程化深度」而非「前端体验」（`docs/research/competitive-landscape.md` §3.3，原文 L135「把竞争维度从"问答体验"（必败）转移到"生产级运行时工程化深度"（空白）」） | 前端是采用者/贡献者的接触面，但不是差异化竞争力 ⇒ 选**维护成本最低的成熟企业管理台栈**，不选最炫的栈、不为低代码体验投资 |
| 功能需求 | ① SSE 流式对话 + 多步过程时间线（`/query`，事件 type：route/evidence/replan/memory/status/answer/error…）② 会话 `/history` + `/session/revert` ③ 联邦 WS 多 Agent 会话（`serialize_stream_event` 统一 schema）④ nl2sql 问答式 SQL 面板 + 结果图表 ⑤ 知识库列表/生命周期/多租户 ACL 管理页 ⑥ kefu 客服会话窗（`docs/TODO.md` §1 表）+ 企业管理台面（RBAC/租户/审计/成本面板/human_task 审批队列） | 形态 = **聊天流 + 企业管理 CRUD + 数据面板 + WS 实时**的控制台 SPA；**范围决策：不做流程拖拽画布**（用户明确），无 SSR/SEO ⇒ 排除 Next.js/SvelteKit 的差异化能力点，画布类框架能力（React Flow/@xyflow）一律出界不计分 |
| 团队熟悉度 | 无专职前端，维护主力是后端/数据/AI 背景 + AI 辅助编码；公司会展数仓前端为 **FastAPI+Vue3** 既有实践；仓内现无任何 JS 工具链（`git ls-files` 对 package.json/vite/vue/tsx 零命中，ADR-0010 §1 实测） | 优先**组件库覆盖度高、手写 CSS 少、国内文档全**的栈；Vue3 有组织内先例，React 无——无画布后此项权重回升为主导项 |
| 生态与可维护性 | AGENTS.md 框架选型规则：成熟 = 稳定发布+社区活跃+文档完善+广泛采用；六应用页面多数是表格/表单/描述面板/审批流 | Vue3+Vite+Element Plus 满足成熟度四要件；中文企业级管理台生态（表格/权限树/审计/上传）覆盖最全；TS + OpenAPI 类型生成直接服务「错误契约对齐」待办 |
| 部署/环境约束 | 生产镜像 `python:3.11-slim`；126 通道是 `git bundle`+`scp`+`build.sh`（rev 门禁），宿主无 Node/uv（AGENTS.md 环境 126 节）；`CORS_ALLOW_ORIGINS` 默认已放行 `http://127.0.0.1:5173`（Vite 默认端口，`config.py:128` 注释明示） | 前端只允许出现在**镜像构建阶段**（多阶段构建）或 CI 产 dist；开发用 Vite 5173 与现有 CORS 约定无缝。**此约束只否决 Next.js（Node 运行时进产线），不区分 React+Vite 与 Vue3+Vite** |
| 过程约束 | 「先出方案评审（含技术选型），再实现」（roadmap #18）；「若引入前端工程，需同步补 CI 门禁」（TODO §1）；错误契约三形状未收敛，审计倾向 A（`plan-frontend-error-contract-audit-2026-10-19.md`） | 选型报告 = 本文件；**动工前置 = 错误契约拍板 + CI JS 段**，见 §6 P0 |

## 2. 候选栈对比

评分口径：与「开源自部署的企业 Agent 平台控制台（兼内部生产）、6 应用、聊天+企业管理 CRUD+面板、无画布、无专职前端、纯 Python 仓」的契合度。✅ 优 / 🟡 平 / ❌ 劣。

| 候选 | 功能覆盖 | 团队熟悉 | 生态/组件库 | 可维护性（AI 辅助视角） | 部署复杂度 | 判定 |
|---|---|---|---|---|---|---|
| **Vue3 + Vite + TS + Element Plus + Pinia** | ✅ 聊天流/表单/表格/面板/审批队列全覆盖；WS/SSE 无特殊障碍 | ✅ 公司 Vue3 先例；后端转前端曲线平缓 | ✅ Element Plus 企业管理台组件全（Table/Form/Descriptions/Upload/权限树…）；中文企业级生态事实标准 | ✅ SFC 单文件直观；EP 用法固定，AI 生成代码稳定 | ✅ 产 dist 静态托管，Node 只在构建期 | **推荐（终态）** |
| React 19 + Vite + AntD 5 + TanStack Query + Zustand | ✅ 同等覆盖 | 🟡 无组织先例 | ✅ AntD 全；全球开源参考面大 | 🟡 约束处方（AntD-only）后生成稳定，但无先例期模式要自建 | ✅ 同左 | 可用备选（贡献者结构国际化后可重评） |
| Next.js（Dify 路线） | ✅ 多出 SSR/RSC/路由约定 | ❌ 更重 | ✅ | 🟡 | ❌ 产线多出 Node 运行时/standalone 产物；开源自部署者负担加重（Dify 多容器 compose 即反例） | 否决：SSR/SEO 需求不存在，纯增负担。**锚点提醒**：这个否决不依赖「Google 读不懂 JS」——调研已证伪该说法（Google 对 JS 页整页渲染成功率接近 100%）；SSR 今天真实的收益面是**不执行 JS 的第二类爬虫**（社交/IM 链接预览、AI 抓取器）与首屏转化，而本前端是**登录后控制台**，两类爬虫面均不存在 ⇒ 否决成立，但理由必须这样写。调研全文（70 源）见 `docs/research/react-nextjs-ssr-seo-deep-research.md` |
| SvelteKit（Open WebUI 路线） | 🟡 聊天流极佳，管理台组件需手拼 | ❌ 无先例 | 🟡 生态小，管理台组件库不成熟 | 🟡 可参考范例少 | 🟡 | 否决：与 AGENTS.md「广泛采用」要件有距离，且无收益点 |
| 维持手写静态页（A 永久化） | ❌ 三个重启条件（流式+回溯+多步可视化）在 TODO §1 已全部出现（ADR-0010 §4 判据已触发） | ✅ | ❌ | ❌ 六应用各写一份 SSE/重连/状态代码，重复且无测试 | ✅ | 否决：只适合 #18 出证据的过渡角色 |
| Streamlit/Gradio（Python 局内捷径） | 🟡 单页面板可以，多应用统一体验/WS/鉴权弱 | ✅ | 🟡 | ❌ 产品化后重写概率高 | 🟡 | 否决：demo 味与企业平台门面不符，属补丁式低 ROI |

**结论：Vue3 栈胜出靠「维护者侧确定收益」（组织先例 + 中文企业管理台生态 + AI 辅助生成稳定性）；React 的「贡献者池/全球参考面」在 0 star、企业定位阶段是假设收益，不敌确定收益。部署复杂度一列对两栈同为 ✅（只否决 Next.js）。**

## 3. 同类项目实践参照

| 项目 | 定位相似度 | 前端栈 | 可借 | 不借 |
|---|---|---|---|---|
| **n8n**（200k★，工作流/Agent 编排） | ★★★ 形态近：执行过程时间线 + 管理台（**其画布我们不做**，故只对标非画布部分） | Vue3 + Vite + Pinia + Element Plus（`packages/frontend/editor-ui`，pnpm monorepo） | ① 栈组合本身；② `@n8n/api-types` 共享 TS 契约 ≈ 我们的 OpenAPI 类型生成；③ 后端托管 dist、运行时注入实例配置；④ 执行时间线可视化（对应我们的 SSE 多步过程时间线） | Vue Flow 画布（范围出界）；CRDT 协同 |
| **RAGFlow**（infiniflow，RAG 引擎） | ★★ 知识库管理台 CRUD 同构（其 agent 画布模块不用） | React 18 + Vite + TS + Ant Design 5 + TanStack Query + Zustand | ① AntD 知识库/文档/分块 CRUD 的**页面组织模式**（平移到 Element Plus）；② Zod 校验 API 边界的思路；③ i18next 结构（国际化时） | 栈本身；AntD(legacy)+Radix(new) 混用（样式分叉反面教材）；画布模块 |
| **Langflow**（155k★，低代码 Agent/RAG 构建） | ★（降档：其 UI 身份即画布，范围出界后相似度大幅下降） | React 19 + Vite + TS + @xyflow + Zustand + TanStack Query | ①「后端托管 dist、单端口」部署形态（与本方案同款）；② TanStack Query+Zustand 分层**模式**（平移到 Vue Query+Pinia） | 栈本身；@xyflow 画布（出界）；Tailwind/Radix 样式路线 |
| **Dify**（159k★，LLM 应用平台） | ★★ 企业 LLM 平台定位参照 | Next.js 16 + React 19 + TS + Tailwind + Jotai/TanStack Query | ① 组件库独立成包的做法（UI 复用面扩大时）；② env 用 Zod 构建期校验 | SSR/Next 路线（自部署负担）；重设计系统投入（与我们定位不符） |
| **Open WebUI**（128k★，AI 对话前端） | ★★ 对话体验层 | SvelteKit + Svelte 5 + Tailwind + Vite | **部署形态**：FastAPI 后端直接托管编译后的前端产物，同源免 CORS——与本仓 `console.html`/`import.html` 同惯例 | Svelte 栈本身 |
| **chatgpt-web**（Vue3 SSE 聊天开源参考） | ★★ 聊天流实现参考 | Vue3 + Vite + Element Plus | SSE 流式对话 + 会话管理的 Vue3 实现范式 | 其产品定位（个人客户端） |

**跨项目共性（直接采纳三条，全部框架无关）**：① SPA + 构建产物由 Python 后端托管（同源，开源自部署友好）；② 前后端共享契约类型（OpenAPI 生成 TS）；③ 组件库做设计约束、少手写 CSS。

**无画布后的同类目结论修正**：画布出界使「LLM 平台开源多为 React」的证据效力下降——那些产品（Langflow/FastGPT/Dify）的 UI 身份很大程度上就是画布/低代码体验；我们真正要建的企业管理台 + 聊天流形态，Vue 侧有 n8n（非画布部分）+ chatgpt-web + 若依系生态的成熟平移解，栈选型的「同类实践」项由 React 优势翻转为平手偏 Vue。

## 4. 推荐方案详述

### 4.1 终态技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 框架 | Vue 3（Composition API + `<script setup>`） | |
| 构建 | Vite + TypeScript（strict） | dev 5173，与 `CORS_ALLOW_ORIGINS` 默认值一致 |
| UI 组件库 | Element Plus | 备选 Naive UI（TS 更纯、但管理台组件覆盖略薄）；不混用两套 |
| 服务端状态 | Vue Query（TanStack Query Vue 适配） | 取数/缓存/重试/失效统一（RAGFlow 模式的 Vue 平移） |
| 客户端状态 | Pinia | 会话/鉴权/连接状态三个 store 起步 |
| 表单/校验 | el-form + Zod（API 边界） | Zod 同时运行时校验错误契约 `{code,msg,request_id}` |
| 图表 | ECharts（vue-echarts） | nl2sql 结果面板 |
| 包管理 | pnpm（单 `web/` 目录，不引入 monorepo 工具） | |
| API 契约 | FastAPI `openapi.json` → `openapi-typescript`/hey-api 生成 TS 客户端 | 一处生成，错误类型随契约演进；服务 `shared-schemas` 的 Pydantic 是单一真相源 |
| 流式 | fetch + ReadableStream 读 SSE（沿用 `console.html` 的 `readSse` 逻辑，抽成 composable） | **不能用 EventSource**——无法带 `X-API-Key` 头，console.html 已实证 |
| 实时 | 联邦 WS，消费 `serialize_stream_event` 统一 schema | 与 SSE 事件映射同源（`agent_runtime.planner.protocol`） |
| i18n（可后置） | vue-i18n | 中文先行；开源国际化时再引 |
| 测试 | Vitest + Playwright（关键链路 E2E，兼任 #18 证据自动化） | |
| Lint | ESLint + `vue-tsc --noEmit` | 进 `make ci` 新增段（见 §4.4） |

### 4.2 落地路径（C，带触发条件）

| 阶段 | 做什么 | 不做什么 | 完成判据 |
|---|---|---|---|
| **P0（#18，≈2 人/日）** | 跑通完整链路并**留截图与日志**（判据原文）。**2026-10-29 订正：零代码改动**，原写的"补 `/session/revert` 按钮"已删除——revert 不属 #18 四步判据，且只读控制台禁写入口（基线 6） | 不引入 Node/构建链；**不改 `console.html` 一行** | roadmap #18 判据：一条完整业务链路真跑通 + 截图日志入库 |
| **P1（错误契约，≈1 人/日）** | 错误契约 D-2/D-4 拍板（审计倾向 A：4xx 统一 `{code,msg,request_id}`） | 不先写前端解析层 | 收敛方案入 `plan-p2-unified-exception-handlers` 评审记录 |
| **P2（web/ 工程，与 P1 同批开工）** | 立 `web/`：脚手架 + CI 门禁 + 首屏迁移（agent_server 流式控制台 P0 版交互 + knowledge-service 管理页） | 不做六应用全量 UI；不做设计系统 | `make ci` 含 web 段全绿；首屏 E2E 过 |
| **P3（产品化）** | 按 TODO §1 顺序铺：nl2sql 面板 → 联邦多 Agent 会话 → kefu 窗 → exhibition 产品化 | 不做微前端、不做 SSR、**不做流程拖拽画布**（范围决策） | 各应用走各自现有接口，不新增后端专用接口（延续 #18 纪律） |

**A→B 转换触发条件**（固化 ADR-0010 §4，写成工单级判据，防永久 A）：P2 开工即视为已触发——因为 TODO §1 需求清单里「流式渲染 + 会话回溯 + 多步过程可视化」三者**同时**出现（ADR §4 条件 1），且界面对象将从业内演示走向业务方/开源采用者使用（条件 2）。**即：B 的触发条件今天已经成立，C 里的 A 只是 #18 的取证手段，不是长期架构。**

### 4.3 工程与契约要点

1. **目录**：根 `web/`（与 `applications/` 平级，路由分 module：`chat` / `kb-admin` / `nl2sql` / `federation` / `kefu` / `exhibition` + `admin`（RBAC/租户/审计/成本/审批队列）；开源门面以通用能力为主，业务应用作示例模块收进次级路由）；Python 侧零改动，uv workspace 不感知 JS。
2. **托管**：多阶段 Dockerfile（`node:22-slim` build → dist COPY 进 `python:3.11-slim`），由 agent_server 现有静态托管惯例（`console_router.py` 同款 `FileResponse`/StaticFiles）出页面；**Node 不进产线镜像**，126 宿主无 Node 不构成阻塞，开源自部署者同样只面对一个 Python 容器。
3. **类型与错误契约**：P1 收敛后前端错误解析层只认 `{code,msg,request_id}`（Zod schema 单文件）；生成的 TS 类型拒绝手写重复定义——这是 TODO「前端↔后端错误契约对齐」的落点，也是 ADR-0010「选 B 还需回答谁维护」的另一半答案：**契约由 OpenAPI 生成维护，人只维护视图层**。
4. **密钥/鉴权**：沿用 console.html 纪律——`X-API-Key` 只存内存，不落 localStorage；JWT 方案（ADR-0007/0008）落地后再换登录态。

### 4.4 CI 门禁（与 P2 同批，缺一不做）

- `make lint` 不动 Python 快路径；新增 `make lint-web`（`vue-tsc --noEmit` + eslint）与 `make test-web`（vitest），**并列入 `make ci`**（TODO §1 明文要求）。
- lockfile 入库；Dependabot 增 npm ecosystem（与现有 uv 面并列）。
- `scripts/check_doc_sync.py` 的引用路径校验继续以 `git ls-files` 为准——`web/` 入库后文档才能引用其路径。

## 5. 适用场景与不适用场景

**适用：**
- 开源自部署企业 Agent 平台的管理控制台（外部采用者起服务后使用）兼内部生产/演示双用；
- **企业管理台面**：RBAC/权限树、多租户 ACL、审计日志、成本面板、human_task 审批队列——Element Plus 高产区；
- 六应用统一视觉与交互（共享 layout、错误提示组件、SSE/WS 连接层）；
- 以表单/表格/面板为主、流式对话为核心的页面形态；
- AI 辅助开发为主、人工评审为主的维护模式（SFC+EP 单一写法下生成质量稳定）。

**不适用（范围决策或出界，不是现在做）：**
- **流程拖拽画布/节点编辑器——明确不做**（用户 2026-10-27 范围决策）。若未来范围真变，届时先评 Vue Flow（n8n 已证可行性），不是非 React 不可；
- 对外营销站/SEO/SSR——控制台不需要；开源文档站走 VitePress/独立站（惯例），不进 `web/`；
- 一次性 demo——继续用静态页（A），不要为 demo 立工程。

## 6. 潜在风险与缓解

| 级 | 风险 | 缓解 |
|---|---|---|
| **P0** | 错误契约未收敛就建前端 ⇒ 把 `{detail}` 三形状（裸字符串/dict detail/自定义 503）固化进客户端，P2 收敛时变成「打破前端」 | **P1 拍板在 P2 动工之前**（顺序硬约束）；前端错误解析收在单文件（Zod schema），形状变更只改一处 |
| **P0** | 引入前端工程但不补 CI 段 ⇒ 前端代码漂移无人拦截（TODO §1 原文） | P2 工程初始化与 `make ci` web 段**同一批 PR**，无门禁不合并 |
| **P1** | Node 工具链进仓后的供应链面（npm 依赖 ≈ 数百包） | lockfile + Dependabot npm；Node 只在构建阶段；产线镜像不含 node_modules |
| **P1** | 无专职前端，页面质量靠 AI 生成 + 后端评审 ⇒ 视觉/交互一致性漂移 | Element Plus 用法约定（禁裸写样式覆盖组件）；共享组件收口（错误提示/流式时间线/连接状态灯/审批队列） |
| **P1** | A（console.html）与 B（web/）双轨期行为不一致 | P2 首屏即迁移 console 交互，迁移完成后 console.html 降级为冒烟页或删除（删除需评审） |
| **P2** | Element Plus / Vue 大版本升级成本 | 选保守版本通道（不追 beta）；组件用法标准化使升级是机械替换 |
| **P2** | SSE 断线重连、背压等交互细节的长尾成本 | 抽象连接层（一个 composable 管 SSE/WS），长尾成本与框架无关，早抽早受益 |
| **P2** | 范围蔓延：有人提出「加个拖拽编排」 | 范围决策已入库（§5 明确不做）；真要提需求走 Spec 流程重新评审栈与交互，不接受即兴塞入 |

## 7. 与 ADR-0010 的映射 + 待拍板点

| ADR-0010 待答 | 本文答案 |
|---|---|
| A / B / C 选哪个 | **C**（A 出 #18 证据；B 为目标态，触发条件已成立，P2 立即开工） |
| 选 B 的前端框架与谁维护 | **Vue 3 + Vite + TS + Element Plus + Pinia**（2026-10-27 三轮判据收敛的终态推荐，决策日志见 §8）；维护 = 后端/数据团队 + AI 辅助，契约层由 OpenAPI 生成托管，视图层人工评审 |
| 重启条件（§4） | 条件 1（流式+回溯+多步可视化）与条件 2（业务方/开源采用者使用）**当前需求已同时满足** ⇒ B 不是「将来」，是本阶段规划内 |

**待用户拍板（本文不代拍）——2026-10-29 逐项更新：**
1. ✅ **已答**：确认 **Vue3 终态栈**（用户 2026-10-29 原话拍板）+ 确认「不做流程拖拽」为**范围决策**（用户 2026-10-27 已明确并已写入 §5，本次未推翻）；
2. ⚠ **此条已失效，且含同名异义陷阱**——本行原写"确认 P1 错误契约走审计倾向的 A 方案（4xx 统一为 `{code,msg,request_id}`）"；而后端实际定案是 `errors.py:15-16` 的 D-2=A：**只**注册 `Exception → 500` 兜底，**不改** 4xx 的 `{detail}` 信封。⇒ 两个"A"结论相反：本文的 A = 收敛 4xx，后端的 D-2=A = 不收敛 4xx。以代码与 ADR 口径为准：前端按三通道实现（见实施件 §3），本条不再作为待拍板项。**引用时不得裸写"A 方案"，必须写清是哪一份文档的 A**；
3. ⚠ **未答**：`web/` 目录名与是否随 PR-0 一并更新 `AGENTS.md`/`ARCHITECTURE.md` 目录表（`check_doc_sync.py` 门禁相关）。实施件 §9.3 已默认按"同步更新"做工单拆分，**但目录名本身未获用户确认**。

## 8. 决策日志（2026-10-27 三轮判据收敛）

> 记录每次改判的「前提变化 → 权重变化 → 结论」，供拍板复核与防止再摇摆。

### 轮 1：初版（内部工具前提）→ Vue3

- 前提：内部企业控制台（来源：`competitive-landscape.md` 防漂移表述 + 126 内网部署上下文）。
- 结论：Vue3+Element Plus——维护成本最低 + 公司先例 + n8n 形态参照；Next.js 因 SSR 无需求且多出 Node 运行时面而否决。

### 轮 2：开源前提复核 → React（当日改判一）

- 前提变化：用户明确**本项目是开源项目**（GitHub `Light-Towers/agent-platform`，Apache-2.0，受众 = 外部采用者/贡献者）。
- 权重变化：「同类项目实践」「贡献者/参考实现面」两维度加权；「同类」扩展为同类目（Python/FastAPI + RAG/Agent + 开源自部署）⇒ Langflow/RAGFlow/Dify 均 React。
- 结论：改判 React 19+Vite+AntD 5+TanStack Query+Zustand。
- **论证纠错（当时已记）**：「Node 只活在构建期/单容器部署」只否决 Next.js，不歧视 React+Vite；不得当 Vue 专属优势用。

### 轮 3：范围澄清复核（无画布 + 企业定位）→ 翻回 Vue3（终态推荐，当日改判二）

- 前提变化：用户明确**不做流程拖拽功能、目标是企业 agent 平台**（非低代码构建器）。
- 权重变化：
  - React 案三支柱中「未来画布走 @xyflow」**死亡**（范围出界）；
  - 「同类目实践」效力下降——Langflow 的 UI 身份即画布、相似度降档到 ★；RAGFlow 的 CRUD 模式（TanStack Query/Zustand）是**可平移模式**（Vue Query/Pinia 同构存在），不是必须照抄的 React 代码；
  - 控制台形态确定为 70% 企业管理台（RBAC/租户/审计/成本/human_task 审批队列）+ 30% 聊天流 ⇒ 决策回到「企业工具型管理台选维护者成本最低的成熟栈」；
  - 「贡献者池（React 全球更大）」在 0 star、企业定位、中文受众阶段是**假设收益**；「组织先例 + 中文企业级管理台生态 + AI 辅助生成稳定性」是**当下确定收益**。
- 结论：翻回 Vue 3 + Vite + TS + Element Plus + Pinia。确定收益 > 假设收益。
- 不变项（三轮均未动）：Next.js 否决（开源下更硬）；路径 C；单 SPA + FastAPI 托管 dist + Node 只在构建期；错误契约 P1 前置、CI 门禁同批。

### 锁栈边界（防再摇摆）

本次拍板后**锁 Vue3**，仅在下列情形重开评估，否则不做横跳（两栈都是成熟解，代价在切换本身）：
1. 范围真出现画布/节点编辑器需求（届时先评 Vue Flow——n8n 已证可行性，不是非 React 不可）；
2. 面向国际贡献者的英文文档路线启动，且贡献者结构实际发生变化（以 PR 来源为证，不以愿景为证）；
3. 团队引入 React 背景专职前端。
