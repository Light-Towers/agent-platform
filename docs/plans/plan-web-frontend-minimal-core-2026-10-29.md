# web/ 前端工程：最小核心功能实施方案

- 状态：**用户已拍板 = Vue3**（2026-10-29 原话"行，那就最终定Vue"）；**同日追加采纳§11.3 三项**（原话"按推荐的方案继续"）—— ① **改守原顺序、不偏离选型文档**（ADR-0010 里一度记的"取消 A 步骤"已撤销），② 目录名 `web/`，③ `eventsource-parser`。执行入口相应新增 **PR-00**（零工具链取证批，见 §7）。**但 ① 的执行内容同日开工即被实测推翻**：#18 判据四步**不含"回退"**，且给 `console.html` 加 revert 会被该页在册测试拦下（基线 6，实跑 2 failed）⇒ **PR-00 缩为零代码纯取证**，因果链与教训见 §11.5。栈的真相源不在本文——是 `docs/plans/plan-frontend-stack-selection-2026-10-27.md`（**该文档的 4.1 小节**，本文无此编号）+ `docs/adr/0010-ui-stack-selection.md`（A/B/C）；本文只引用，**换栈必须三处同批改**（本轮曾把"改本文一行"当代价，已修正）
- 日期：2026-10-29
- 来源：`docs/TODO.md` §1（agent_server 前端待办原文）+ `docs/plans/plan-frontend-stack-selection-2026-10-27.md`（三轮判据与锁栈边界）+ `docs/adr/0010-ui-stack-selection.md`（2026-10-29 由「未决」落为「已决 C」，其 §6 是本文取数与订正的依据之一）
- 前置：本文 §5 所列**三件事必须与 PR-0 同批**，缺一则该批不合（另见 §11.3——那三项偏离已于 2026-10-29 采纳，保留指针只为一条纪律：**偏离不得默认放过**）
- 执行入口：新会话从本文 §7 工单表 + §9 文件清单开始，不依赖任何对话历史
- 开工前置核查（2026-10-30，rev `3868023c`）：本文 **41 条行号坐标复验全命中**（rc=0），但查出 **6 处文面要订正** —— ① 事件类数 **13 写错，实取 12**；② `/health` 字段集本文只列 13 个，契约实取 **30**（权威源是两层模型，不是 `console.html`）；③ CI 的两处 `paths:` **不含 `web/**`** ⇒ §5 那条「必含 CI 的 JS 段」会被路径过滤器架空；④ `.dockerignore` 缺 `**/node_modules` 与 `web/dist` 两条；⑤ §11.5/§11.6 的坐标写的是**裸文件名**（仓内有两个同名 `schemas.py`）；⑥ `README.md:643` 一条过期行号（引 `health.py:25-40`，那里已不是 `HealthResponse`）。订正已就地落在 §1/§3/§5/§7/§9/§10.5/§11.5/§11.6 与 README，逐条读数见 `docs/operations/evidence/2026-10-30-frontend-preflight/readings.md`。**同日（2026-10-30）两个待拍板已答**（§12）：A = 新增 `make ci-web` 目标 + workflow 加一步（并不进 `make ci`），B = `docs/TODO.md` 三条随 **PR-0 落地那一批**改（本轮不动账面）⇒ §0 那句「实现者不再做选择」重新成立，PR-0 无待拍板项

## 0. 结论（决策完备，实现者不再做选择）

**栈**：Vue 3 + Vite + TypeScript + Pinia，工程位置 = 仓库根 `web/`，包管理 pnpm。
**Element Plus 第一批不装**。最小核心只有"对话流 + 时间线 + 状态灯"，无表格/表单/权限树，引入 EP 是净负担；待 §6 第二批（RBAC/租户/审计/成本/审批队列）再引入，届时它才值回成本。**这条不违反选型结论**——栈口径未变，变的只是组件库的引入时机。

**最小核心 = 覆盖后端实际发出的事件全集**（不是"追平 `console.html`"）。范围依据是 `docs/TODO.md` §1 原文："新建 SSE 流式对话控制台，复用 `/query`（SSE）+ `/history` + `/session/revert` 现有接口"。

基线口径本轮被实测**改过一次**，理由是拿 `console.html`（346 行）当能力基线会系统性低估需求：它的 `switch (payload.type || name)`（:223）只有 9 个 case，而后端还会发 `done`、`admission`、`coordination` 三类，这三者现在全部落到 default 打印"未处理的事件类型"。其中 `done` 不是可选装饰——`query_router.py:372` 的 `{type:"done", thread_id, answer: final_answer}` 是**最终答案与流终止的权威信号**（唯一例外见 §3 第 4 条：`error` 帧后紧跟的 `done` 不得当成功答案），不处理它就只能靠 ReadableStream 自然结束来推断"答完了"， loading 态与重复提交防护都失去确定依据。`console.html` 降级为**行为参照物**（事件文案、灯语义、错误口径照它对齐），不再是范围定义。

### 0.2 一处节奏覆盖，必须知情

选型文档 §0 定的落地路径是 C：「#18 验收用现有 `console.html` 补证据链，**不为 #18 引入工具链**；Phase 3 产品化再立独立 `web/` 工程」。

用户 2026-10-29 指令"从头构建生成前端项目，先把最小核心功能实现完成"**把 Phase 3 的产品化工程提前了**。本文按指令执行，并记录：

- `console.html` **不删**。它同时是 ADR-0010 选项 C 的证据基线，和新前端的行为参照物（事件文案、错误口径、灯语义都照它对齐）。
- 代价知情：跳过 C 意味着脚手架成本前置。选型文档原话是"先引工具链属于把 10 人/日里的一半花在脚手架上，对判据零贡献"。

### 0.3 上一轮那条判据的处置

选型文档 §1 的"公司会展数仓前端为 **FastAPI+Vue3** 既有实践"经全仓溯源**无任何来源标注**（取证 rev `896f966e`：`git grep -I -n -F --untracked -e "FastAPI+Vue3"` = **3 行 / 2 文件**，即选型文档 L16、L27 与本文 L29 自身（自指命中）；两处原句都只写“公司先例”而没有出处。⚠ **`--untracked` 不是可选项**：选型文档 `docs/plans/plan-frontend-stack-selection-2026-10-27.md` 本身尚未入库，同一命令不带该开关读数 **0 命中**——“全仓零 X”在这类命令上默认只扫已跟踪文件，不写清作用域就会把“没扫”读成“没有”。同文档对"用户明确""ADR-0010 §1 实测""`config.py:128` 注释明示"都打了标注，唯独此条裸奔），且唯一实物（本机另一份工作副本 `bigdata-business/ruoyi-ui`，**不在本仓、不入库**）是 **Spring Boot + Vue 2.6 + Element UI + Vuex + webpack、无 TS、SSE 零匹配**。

**本文把它降级为「未证实，不计入权重」**。影响面：选型文档 §1 那句"无画布后此项权重回升为主导项"不成立（团队熟悉度变两栈平手），主导项应改读为"Element Plus 中文企业管理台生态 + 无专职前端下 SFC 单一写法的生成稳定性"。**Vue3 的方向不变**——因选型文档轮 2 已自纠："Node 只活在构建期"只否决 Next.js，不歧视 React+Vite，部署列两栈本就同为 ✅。（该句的"Next.js"需读作"需要 Node server 的 Next 形态"，原因见 §10.3 第 1 条——Khoj 用 Next 但静态导出，运行时同样无 Node。）

## 1. 后端契约（全部本轮实测，非推断）

| 项 | 事实 | 出处 |
|---|---|---|
| 对话 | `POST /query`，body `{query, session_id?, tenant_id?}`，返回 `StreamingResponse`（SSE） | `applications/agent_server/api/query_router.py:28` |
| 历史 | `GET /history?session_id=&limit=`；存储不可用返回 **503** + `detail="HISTORY_READ_FAILED"` / `"CHECKPOINTER_UNAVAILABLE"` | `applications/agent_server/tests/test_history_real_checkpointer.py:145,158` |
| 回溯 | `POST /session/revert`，body `{session_id, checkpoint_id}`；未命中 **404** + `detail="CHECKPOINT_NOT_FOUND"` | 同上 `:186-191` |
| 自述 | `GET /health`，免鉴权探针路径 | `console.html` `loadLights()` |
| 鉴权 | 头 `X-API-Key`；`API_KEY` 为空 = 开发模式不校验 | `applications/agent_server/api/auth.py:23`、`config.py:19` |
| 页面壳 | `GET /console.html` 免鉴权，`Cache-Control: no-store` | `applications/agent_server/api/console_router.py:26-39` |
| 租户归属 | **服务端断言租户**，客户端传的 `session_id` / `tenant_id` 不参与归属；与断言不一致时后端 WARNING | `config.py:19` 注释、`test_history_real_checkpointer.py:229-237` |

**事件全集按执行路径分叉**（实测，非推断）。`serialize_stream_event` 的 docstring 声称两轨"客户端无感"，但两轨事件集并不同构，前端不能假设任何事件必现：

| 出口 | 事件 | 出处 |
|---|---|---|
| graph 路径 `_node_event` | `route` `evidence` `answer` **仅 3 类** | `query_router.py:465-478` |
| planner 路径 `serialize_stream_event` | `route` `evidence` `memory` `status` `replan` `answer` `error` `suspended` | `packages/agent-runtime/agent_runtime/planner/protocol.py:788-827` |
| router 直接发 | `cache_hit` `done` `admission` `coordination` `error` | `query_router.py:206,207,227,253,372,378` |

**事件类型的权威定义在 `serialize_stream_event` + `_node_event`，不在 `console.html`**——PR-1 的 TS 联合类型须对齐前者（符合 AGENTS.md「单一实现」原则），否则前端跟着一个有盲区的参照物走。

**并集是 12 类，不是 13 类**（2026-10-30 复取，rev `3868023c`）：上表两行都列了 `error`（planner 路 8 + router 直发 5，`error` 同名单形），去重 = **12**：`route evidence memory status replan answer error suspended cache_hit done admission coordination`。上一版工单文面里那个「13」是按表行数加出来的，不是从源里数出来的 —— 见 §12 第 1 条，`check-events.mjs` 的期望集因此**不得写死数字**。

**还有第三个权威点，本文上一版漏了**：`packages/agent-runtime/agent_runtime/planner/protocol.py:44` 的
`StreamEventType = Literal["route", "evidence", "memory", "answer", "error", "status", "replan", "suspended"]`
与 `serialize_stream_event` 的 8 个分支**逐字等值**（实取 True）。这条不是装饰：`serialize_stream_event` 对未定义 type **返回 `None` 静默忽略**（`:792` docstring 自陈），所以「Literal 加一项而分支没加」在运行期**零症状**——事件直接消失，前端连「未处理的事件类型」都不会报。⇒ §2.2 那条纪律在**后端自己这半**也需要一道门禁（§12 第 2 条）。

**`/health` 字段集**（2026-10-30 按契约复取 = **30 个**，本文上一版只列了 13 个且出处挂的是 `console.html` `loadLights()` —— 那是参照物，不是契约）：

| 层 | 字段 | 出处 |
|---|---|---|
| 共享基类 13 个 | `status` `version` `dependencies` `storage` `llm` `search` `sql_backend` `coordination` `admission` `revert` `otel` `otel_status` `mcp` | `packages/shared-schemas/shared_schemas/health.py:67` `class HealthResponse(BaseModel)` |
| agent_server 子类另 17 个 | `scheduler` `control_plane` `cost_governance` `forensic` `embedding_backend` `embedding_real` `planner` `guard_enabled` `nl2sql` `langfuse_enabled` `langfuse_ready` `cache_backend` `cache_ready` `cache_degraded_reason` `cache_stats` `auth_enabled` `identity_mode`(jwt/single/insecure) | `applications/agent_server/schemas.py:121` `class HealthResponse(BaseHealthResponse)` |

⇒ **PR-4 按这 30 个做**（判据原文是「每盏灯的文本可追溯到字段值」，漏 17 个就漏了 `revert`/`admission`/`cache_ready` 这些最能说明「接线 ≠ 启用」的灯）；`console.html` 只用来对文案与灯语义。子类 docstring（`:128-130`）另给一条硬约束：**新增字段只加在本 app 子类，不许加到基类**（基类被另外三个服务直接返回）⇒ 前端要新读数时提后端需求要提对地方。

## 2. 三条必须继承的工程纪律（都是已踩过的坑，不许重新发现）

### 2.1 传输：SSE 必须用 `fetch` 读，不能用 `EventSource`

因为要携带 `X-API-Key` 请求头，而 `EventSource` 不支持自定义头。（`console.html` 注释原文已记此事。）解帧本身**不自写**，交给 `eventsource-parser`（选型理由与先例见 §10.3 第 2 条）——重连与鉴权头仍由我们掌控。

### 2.2 未识别事件类型不得静默吞掉

后端加新事件而前端无分支时，屏上会出现"接口给了却看不见"的假象。必须渲染一条只含事件名、不含载荷的提示（载荷可能含资料原文，不 dump）。

### 2.3 入口 HTML 必须 `no-store`

Vite 产物给 JS/CSS 带内容 hash，但 `index.html` 本身不带；滚动升级后浏览器若沿用旧壳，就是**旧事件契约配新接口**——`console_router.py:36-38` 注释记着实跑中已误判过一次"修复没生效"。

另有一条凭据纪律：密钥只存内存，不落 `localStorage`/`sessionStorage`（`console.html` 现状即如此），刷新即失。

## 3. 错误通道：不是"待收敛"，而是已定案的三通道

**本节上一版的前提是错的**。它把 D-2 当成未决事项（"后端若收敛为信封制……"），而 `packages/agent-core/agent_core/guardrails/errors.py:15-16` 的 docstring 已写明定案：

> D-2=A：`install_error_handlers` 仅注册 `Exception → 500` 兜底脱敏，**不改**各 app 现有 4xx `HTTPException` 的 `{detail}` 对外信封（零破坏）。

即：两套形状并存是**刻意的、已记录的决策**，不是漂移。`applications/agent_server/main.py:701` 实测确认 `create_app()` 走 `build_api_app(enable_tracing=True)`，且 `install_handlers` 默认 True——所以 500 走信封、4xx 走 `detail` 这两条在本仓同时生效。`docs/TODO.md` §1 第 104 行"须先于 D-2/D-4 收敛决策落地"的等待前提已经消失（D-2 = 不收敛 4xx），**那条 P0 可以关掉**。

前端实际面对**三条**错误通道，不是两条：

| 通道 | 形状 | 出处 |
|---|---|---|
| HTTP 4xx（含 503） | FastAPI 原生 `{"detail": …}`，**但 `detail` 有两种形状**：业务类是**字符串**（`"CHECKPOINT_NOT_FOUND"`），校验类 **422 是数组** `[{type, loc, msg, input, ctx}]` | `errors.py:15-16` 明文不改；`test_history_real_checkpointer.py:186-191`；422 数组形状 = 2026-10-29 本机 `POST /session/revert` 缺字段实取（取证件 §3 第一条） |
| HTTP 未捕获 500 | `{"code": "INTERNAL_ERROR", "msg": "服务器内部错误，请稍后重试", "request_id": ...}` + `X-Trace-Id` 头 | `errors.py:126-131`、`test_guardrails_errors.py:151-156` |
| **SSE 流内 `error` 帧** | 状态码已发、流已开，`install_error_handlers` 兜不住；值为 `mask_exception_for_client()` 的**固定文案** | `errors.py:58-62` 自陈此限制；`query_router.py:376-378` |

第三通道有一条必须写死的推论：**SSE 错误帧不包含任何诊断信息**。`mask_exception_for_client` 的 `exc` 参数"只为语义显式，**不参与返回值**"（`errors.py:64-65`），所以流内错误的 `payload.error` 永远是同一句"服务器内部错误，请稍后重试"。因此：

- UI 上**不要**做一个"错误详情"区去承接它——它没有信息量，且会让使用者误以为所有故障都同一个原因。
- 正确做法：文案上直接引导去查服务端日志/`request_id`（`console.html` 未做此事，属已知短板，不在本批修）。
- 另有一致性陷阱：`query_router.py:378` 手工发的 error 帧用键 `error`，而 `serialize_stream_event` 的 error 分支是 `{"type":"error", **event.payload}`（键由 Planner 决定，`protocol.py:821-822`）。**两路 error 的载荷键不同**，前端必须兼容取键。
- **紧邻的终止陷阱（本批最高危；本文上一版在此自相矛盾）**：`query_router.py:379` 在 `error` 帧**之后紧跟** `{"type":"done","thread_id":...,"answer":""}`。若按本文开头「`done` 是最终答案的权威信号」无条件执行，此处会用**空串覆盖已有渲染并将其当成功收尾**——症状是"回答消失了，但界面显示正常完成"。外部先例把这类写法列为明令禁止的反模式（`yak-ops-ui/FRONTEND_RULES.md` 原文："Components must not parse HTTP envelope details or **turn API failures into successful empty results**"）。**定死**：流内一旦出现过 `error` 帧，后续 `done` 的 `answer` 一律不覆盖已渲染内容，会话终态置 `failed` 而非 `completed`。（鉴权失败属通道一，流未开，不受此规则约束。）
- **422 的数组 `detail` 必须分形处理，且不得把 `input` 回显上屏（2026-10-29 实跑新增）**：上一版把 4xx 一律写成"字符串 `detail`"，不全面。实跑读数：业务类给字符串（`{"detail":"CHECKPOINT_NOT_FOUND"}`，`/session/revert` 带不存在的 uuid ⇒ 404），校验类 **422 给数组**（`{"detail":[{"type":"missing","loc":["body","checkpoint_id"],"msg":"Field required","input":…}]}`）。现状 `console.html:209` 用 `typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)` 兜底——不崩，但会把整个校验错误（**含服务端 echo 回来的用户原文**）铺在屏上：用 2100 字问题触发 422 时那一行长 2248 字符、把时间线列撑到整屏高（截图 `console_step5_422.png`）。`web/` 的 `describeError` 要按 `Array.isArray(detail)` 分支，取每项 `loc` 末段作字段名 + `msg` 作原因，**丢弃 `input`**（它回显用户输入，可能含资料原文/PII，不上屏也是出域纪律）。另：422 短路在校验层，**不写会话历史**（实跑复核 `/history` 条数前后不变）。

处置（写死，不再讨论）：前端所有错误解析收敛到**单一函数** `describeError(resp: Response): Promise<string>` + **单一函数** `describeStreamError(payload: unknown): string`，三条口径分别对应一个分支点。后端未来若真收敛为信封制，改动面 = 这两个函数 + 两组单测。

**这三条通道的作用域 = 「只连 `agent_server` 的前端」，不是「全仓」**（2026-10-30 复跑审计件后补）：`docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` §1.1 另记两种形状——exhibition-agent 的 **dict detail**（`applications/exhibition-agent/exhibition_agent/server.py:144/:146/:148/:150` 四处 `raise HTTPException(..., detail={"code": …, "message": …})`，本批逐行复跑确认）与 nl2sql-service `/ready` 的自定义 dict（**本批未复跑**，仍按转述读）。`web/` 第一批不连这两个服务，所以 §3 的三分支设计**不因此改动**；但若第二批把 nl2sql 面板并进来（§6 明列它属第二批），`describeError` 要加第 4/5 分支，届时按「先方案后编码」另开，不许顺手在 `web/` 里加特例。

## 4. 验收标准

按 `AGENTS.md` 指向的 `docs/operations/evidence-format.md` 口径写完成陈述，本文额外要求：

| # | 判据 | 反证方式（非空转） |
|---|---|---|
| A1 | 无 `DATABASE_URL`/无 LLM 密钥下，`pnpm build` 产 `web/dist` 且 `agent_server` 托管后可打开对话页 | 空库跑通即非"依赖环境才绿" |
| A2 | 提问 → 时间线按事件类型分色出现 → 答案落屏；`error` 事件出现时不白屏 | 用未配 LLM 的部署制造真实 error 分支 |
| A3 | 喂一个未知事件类型（后端临时加或用例伪造），屏上必须出现"未处理的事件类型"行 | 证明 §2.2 纪律不是空话 |
| A4 | `X-API-Key` 错误 → 明确提示"密钥未填或不正确（服务端：…）"，而非 `TypeError: Failed to fetch` | 对照 `console.html` 已有行为 |
| A5 | CI 的 JS 段能因**一个**故意引入的前端漂移而失败（未用类型的变量/未处理 Promise），随后撤销 | 证明门禁不是空转 |
| A6 | `make lint` 与既有 10 个 pytest session 零回归 | 前端引入不得动后端绿度 |
| A7 | `done` 事件驱动流终止与答案定稿：收到 `done` 即解除 loading 并允许再次提交；未收到则不得假定完成 | 临时用本地 mock 只开流不发 `done`，界面必须仍判"未完成" |
| A8 | 四条错误分支各占一分支且文案可区分（4xx 字符串 `detail` / **422 数组 `detail`** / 500 信封 `msg` / 流内 `error` 帧） | 分别故意触发，对比屏上文本互异；422 那条须显示"字段名 + 原因"且**屏上不得出现用户输入原文**；流内那条必须引导向 `request_id` 而非假称"详情" |
| A9 | **（PR-00）**截图与日志逐条对应 roadmap #18 判据四步（提问→执行→展示过程与结果→错误提示），且取证**零后端改动** | `git diff` 后端目录为空；四步各有一张截图/一段日志；日志须含 SSE 事件名序列 |
| A10 | **（由 PR-00 移交 PR-3）**回退返回的 `session_id` 与 `/history` 返回的 `thread_id` 必须是同一个值，不一致不得显示成功 | 原为 PR-00 设计，因 revert 不得进只读控制台而移交 `web/` PR-3（实现要点存 §11.5） |

## 5. 前置三件事（同批，缺一则该批不合）

选型文档一句话版纪律：**引入前端工程、补 CI 门禁、收敛错误契约三件事必须同批**。落到工单上：

- PR-0 必含 `web/` 骨架 + CI 的 JS 段（lint + typecheck + build），否则前端代码漂移无人拦截（`make lint`/pytest 目前仅覆盖 Python 侧）。**落点已拍板（2026-10-30，§12-A = 形状二）**：`Makefile` 新增 `ci-web:` 目标（`pnpm install --frozen-lockfile` → lint → typecheck → `check-events.mjs` → build），workflow 加一步 `run: make ci-web`（与已有的 `make test-cache-contract`（目标在 `Makefile:77`、步在 workflow `:87`）同形态，记得同步 `Makefile:4` 的 `.PHONY` 列表）；`make ci` 保持 `lint test eval` 不加 JS 段 ⇒ Python-only 机器（含 126 宿主）仍跑得动 `make ci`。**但光加 step 不够**：`.github/workflows/agent-platform-ci.yml` 的 `on.push.paths`（`:7-22`）与 `on.pull_request.paths`（`:24-39`）**两处都不含 `web/**`** ⇒ 只改前端的 PR 根本不触发 CI（§12 第 3 条）。
- PR-0 必含 §3 的 `describeError` / `describeStreamError` 两个收敛点。
- PR-0 必含 `.dockerignore` 两条补充（`**/node_modules`、`web/dist`），理由见 §12 第 4 条。
- PR-0 同步关掉 `docs/TODO.md` §1 第 104 行那条 P0（等的前提 D-2 已定案为 A，见 §3）。**另两条同批该动**（2026-10-30 复取行号未漂）：`:103`「前端技术栈选型（未定，…不预先绑定 Vue/React）」已被 ADR-0010（已决 C）推翻，`:104` 的审计件 `docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` 已入库⇒ 两条是**账面未跟**；`docs/TODO.md:53` 那行「前端 | 3」的开项数随之变。属账面拍板（**§12-B**，已答：随 PR-0 落地那一批改）。“另两条”指 `:103` 与 `:105`（`:104` 就是上一句那条 P0），逐条理由见 §12-B。
- `check_doc_sync.py` 只校 AGENTS/ARCHITECTURE/README 中**版本控制清单内**的路径；新增 `web/` 后须同步更新 `ARCHITECTURE.md` 的目录表与 `AGENTS.md` 的目录结构表，否则文档与现实漂移。

## 6. 范围边界

**本批不做**（§1 六条需求里的其余四条，各需独立方案）：RBAC/租户/审计/成本面板、human_task 审批队列、知识库生命周期与多租户 ACL 管理页、nl2sql 问答面板与图表、kefu 客服窗、agent_federation 的 WS 多 Agent 会话。

**不引入**：Element Plus（延后）、`@ant-design/x`（属已作废的轮 2 方案）、若依系 `request.js` 与其 `code/msg/data` 信封及 header 隐式开关（`isToken`/`repeatSubmit`）——后者属"未文档化代码路径隐含依赖"，违反本报告 §8 的不变量。可搬的是若依的**页面组织模式**，不是代码。

**本机能力**：node v24.12.0 / npm 11.6.2 / pnpm 10.33.0 / corepack 0.34.5 实测在位，本机构建可行；126 宿主无 Node，故产物必须由 CI 或本机产 `dist` 后进镜像，**不要在 126 上构建**。

## 7. 工单拆分（每个 PR < 400 行，可独立验证）

| 工单 | 内容 | 完成判据 |
|---|---|---|
| **PR-00**（**零代码**） | **纯取证批**：用**现状未改动**的 `console.html` 跑通 #18 四步链路 → 留截图 + 日志 ⇒ **关 roadmap #18**。不写一行代码（实测依据见 §11.5：曾试补 revert，被基线 6 测试拦停并已全量回退）。**状态（2026-10-29）：已执行完毕**，读数与档位见 `docs/operations/evidence/2026-10-29-roadmap-18-console/readings.md`——四步形状已证、零代码改动已核（`git diff` 对 `applications/`+`packages/` 为空），但本机无模型密钥 ⇒ "真跑通"未达 ⇒ **#18 保持开项，不翻已完成** | A9 |
| PR-0 | `web/` 骨架：pnpm + Vite + TS + Pinia、`describeError`/`describeStreamError` 收敛点、CI JS 段、FastAPI 托管 `dist`（多阶段 Dockerfile，Node 只活在构建期）、`index.html` 的 `no-store`——**具体做法见 §9，已定死** | A1、A5、A6 |
| PR-1 | SSE 客户端：`fetch` + **`eventsource-parser`** 解帧（不自写循环，选型理由见 §10.3 第 2 条）、事件类型 TS 联合（对齐 §1 全 **12** 类（2026-10-30 按源复取，上一版写 13），以 `serialize_stream_event` + `_node_event` + router 直发字面量为源，见 §12 第 1 条）、`done` 终止语义、未知事件不吞、**§3 第 4 条的 `error`→`done` 抑制规则** | A2 的前半、A3、A7、`check-events.mjs` 断言绿（§10.5） |
| PR-2 | 对话页：输入框 + 过程时间线（按类型分色）+ 答案区 + 依据列表 | A2、A4、A8 |
| PR-3 | 会话历史 + `/session/revert` 交互。**开工前置已出方案（2026-10-29，见 §11.6）**：原写的"`checkpoint_id` 取不到"只是三层缺口的表层——实测另两层为「主路径每线程无历史点」与「revert 新行 uuid4 撞字典序⇒抽样 8%–13% 静默失效 / 其余遮蔽后续写入」。方案与待拍板项存 `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md` | `/history` 渲染真数据；revert 分支形状**由该方案 §7-#1 定夺后才能定**（命中/404 两分支不成立，因为有"无历史点"第三态）；A10 |
| PR-4 | `/health` 状态灯页（逐字段直读接口，不做本地推断） | 每盏灯的文本可追溯到字段值 |

依赖：**PR-00 与 PR-0 无代码耦合**（PR-00 零代码，只共享一个可跑服务的环境），可先于 PR-0 单独完成并关 #18。PR-0 → PR-1 → PR-2 串行；PR-3、PR-4 可在 PR-1 之后并行。PR-3 额外受 §11.5 的 `checkpoint_id` 缺口前置约束（方案未定不得开工）。

## 8. 分支与提交

远端恒 `main` + 唯一集成分支；工作分支从集成分支切出、PR 合回、本地与远端当场删（`git branch -d`）。合入 `main` 须用户显式批示。远端名先 `git remote -v` 取（本仓为 `company` 与禁推镜像 `github-legacy`，**无 `origin`**）。公开镜像推送前 `lint_public_mirror.py --mode publish` 必须 rc=0——`web/` 里不得写内网主机名/网段。

## 9. PR-0 的文件清单与已定死的技术决策

> 本节存在的目的：新会话拿到的必须是**零待选项**的工单。以下每条都是本轮实测后定下的，不是建议。

### 9.1 托管方式（本轮实测推翻了直觉方案）

`applications/agent_server/tests/test_console_router.py:130-133` 有一条**恒等性断言**锁住 console_router 的路由集合：

```python
paths = {(r.path, tuple(sorted(r.methods))) for r in console_router.router.routes}
assert paths == {("/console.html", ("GET",))}, paths
```

⇒ **`dist` 绝不能挂在 `console_router` 上**（会直接弄红既有测试）。而装配链已查清：`main.py:718` 只 `app.include_router(router)`，router 在 `applications/agent_server/api/routes.py:18-27` 聚合 9 个子路由。

定下的做法（三处改动，均在 `main.py` 的 `create_app()` 内）：

1. **条件挂载**——全仓目前**零 `StaticFiles` 用法**（grep 实测 0 命中），本批是第一次。必须只在 `web/dist` 存在时挂载，否则 `DATABASE_URL= uvicorn agent_server.main:app` 这条 AGENTS.md 明文零依赖冒烟路径会启动即崩。
2. 挂载点 `app.mount("/ui", NoStoreStaticFiles(directory=..., html=True), name="web_ui")`。选 mount 而非新增子路由：StaticFiles 本身就是 ASGI app，不需经 `routes.py` 聚合，不碰恒等性约束。
3. `NoStoreStaticFiles` = 子类覆写 `file_response()` 加 `Cache-Control: no-store`——因 §2.3 纪律而 StaticFiles 默认**不给**此头。它带内容 hash 的 JS/CSS 本不需 no-store，但 `index.html` 需要；最小实现一律 no-store，不引入分文件类型的复杂度。

**不做 SPA history fallback**：最小核心无前端路由（单页），`html=True` 已够。深链刷新 404 属已知边界，待 §6 第二批多页时再计。

### 9.2 Vite 与工具链

- `base: '/ui/'`——**不是缺省值 `/`**。因为产物挂在 `/ui` 下，写错则静态资源全 404，而症状看起来像"打包失败"。
- dev 代理 `/query` `/history` `/health` `/session` → `:8000`（CORS 已放行 5173，见 `config.py:128`）。
- pnpm 与 uv **两套独立**：`web/package.json` 不进 pyproject workspace；`make lint` / `make test` 不碰它（P2 与 R19 门禁只扫 `.py`，`web/` 天然不在作用域）。
- `.gitignore` **无需改动**：现有第 12 行 `dist/` 与第 17 行 `node_modules/` 无路径锚定，已覆盖 `web/dist` 与 `web/node_modules`（本轮实测）。但 `web/pnpm-lock.yaml` **必入库**（CI 用 `--frozen-lockfile`）。

### 9.3 文件清单

```
web/
  package.json  pnpm-lock.yaml  pnpm-workspace.yaml(不建)
  vite.config.ts  tsconfig.json  index.html
  src/main.ts  src/App.vue
  src/api/client.ts        # fetch + X-API-Key，待命令
  src/api/errors.ts        # describeError / describeStreamError 两个收敛点（§3）
  src/api/sse.ts           # fetch + eventsource-parser 解帧（§2.1、§10.3）
  src/api/events.ts        # 12 类事件的 TS 联合（§1，期望集从 serialize_stream_event / _node_event / router 直发三处派生，不写死数）
  scripts/check-events.mjs # 存在性断言：事件全集在 TS 联合与 handler 分支一一对应，缺则红（§10.5 采纳项）；另加一条后端侧断言 `StreamEventType` Literal ⊆ `serialize_stream_event` 分支集（§12 第 2 条）
  src/stores/session.ts    # Pinia：对话态与事件时间线
  src/components/Timeline.vue  Answer.vue  ApiKeyBox.vue
applications/agent_server/main.py        # + 条件 mount + NoStoreStaticFiles
Dockerfile                                # 改多阶段：node:24-alpine 构建 → python:3.11-slim 运行
.dockerignore                             # + 两条：`**/node_modules`、`web/dist`（§12 第 4 条）
.github/workflows/agent-platform-ci.yml   # + JS 段一步 `run: make ci-web`（目标内容见 §5）；**且两处 `paths:` 都要补 `web/**`**（§12 第 3 条）
Makefile                                  # 已拍板（§12-A = 形状二）：新增 `ci-web:` 目标，`ci:` 不动
ARCHITECTURE.md  AGENTS.md                 # 目录表新增 web/ 行（§5 防漂移要求）
```

Dockerfile 现为**单阶段**（`FROM python:3.11-slim`，只 `COPY applications/agent_server`）⇒ 需新增 builder 阶段与 `COPY --from=builder` 的 `web/` 源码层。Node 只活在构建期，产物进镜像，**不在 126 上构建**（§6）。

## 10. 开源 agent 项目前端实测参照

> 取证方式：`raw.githubusercontent.com` 直取 `package.json` / `Dockerfile` / `next.config`，配合 `gh api .../git/trees?recursive=1` 定位真实文件。**不引二手博客**。默认分支逐一实测，路径为返回值。

### 10.1 栈分布

| 项目 | 前端位置 | 框架 | 构建 | 状态层 | 流式库 |
|---|---|---|---|---|---|
| Dify | `web/package.json` (158 deps) | React + **Next** | vite | zustand + jotai + react-query | — |
| Langflow | `src/frontend/package.json` (135) | React 19 | vite 7 | zustand + react-query | — |
| RAGFlow | `web/package.json` (175) | React 18 | vite 7 | zustand + react-query | `eventsource-parser` |
| Open WebUI | `package.json` 根 (135) | **Svelte 5** | vite 5 | — | `eventsource-parser` |
| AnythingLLM | `frontend/package.json` | React 18 | vite 4 | — | `@microsoft/fetch-event-source` |
| LobeChat | `package.json` 根 (402) | React 19 + **Next 16** | vite | zustand + swr + react-query | — |
| Flowise | `packages/ui/package.json` | React 18 | vite 5 | redux + RTK | `@microsoft/fetch-event-source` |
| n8n | `packages/frontend/@n8n/design-system` | **Vue** + element-plus + pinia + vue-router | vite | pinia | — |
| Khoj | `src/interface/web` (74) | React 18 + **Next 15.5** | — | swr | — |
| gpt-researcher | `frontend/nextjs/package.json` | React 18 + **Next 14** | — | — | `eventsource-parser` |
| Langfuse | `web/package.json` | React 19 + **Next 16** | vite 7 | zustand + react-query | — |
| agno | `cookbook/.../openui/frontend` | React 19 | vite 7 | — | —（cookbook 示例，非产品 UI） |
| OpenHands | 默认分支 tree 内已无 `frontend/` | React 19 | vite 8 | zustand + react-query | **主 UI 位置未定位，不计入计数** |
| Jan | `app/package.json` 404 | 未取到 | — | — | — |

**计数（可定位且为产品 UI 的 11 个）**：React 系 9、Svelte 1（Open WebUI）、**Vue 1（n8n）**。样式层 tailwind 10/11；重量级组件库只有 MUI（Flowise）与 **Element Plus（n8n）**。

### 10.2 托管形态（三种，Dockerfile 逐行实测）

| 形态 | 实例 | 关键行 | 运行时 Node |
|---|---|---|---|
| **A. 静态产物进 Python 镜像** | Open WebUI（Svelte） | `FROM node:22-alpine AS build` → `npm run build` → `FROM python:3.12-slim` → `COPY --from=build /app/build /app/build` → `CMD ["bash","start.sh"]` | **无** |
| **A″. 同形态，但是 React + Vite** | **RAGFlow**（Python 后端 + React 18 + Vite 7，295 行 Dockerfile 实测） | `FROM runner-${TARGETARCH} AS web-builder` → `COPY web/package.json web/package-lock.json …` → `FROM base AS production` → **`COPY --from=web-builder /ragflow/web/dist /ragflow/web/dist`**（无 node_modules、无 Node server） | **无** |
| **A′. 同上，产物落在 Python 包目录内** | Khoj | `FROM oven/bun:1-alpine` → `bun run build` → `COPY --from=web-app .../out ./src/khoj/interface/built` → `collectstatic` | **无** |
| **B. Next SSR，运行时背 Node** | gpt-researcher `Dockerfile.fullstack` | `COPY --from=frontend-builder .../.next` **和 `.../node_modules`** 入 final 镜像 + nginx + `CMD ["/usr/bin/supervisord",...]` | **有** |
| **C. 静态产物 + nginx 一体（兼 API 反代）** | yak-ops（Java 后端 + React/Vite，实测其 108 行根 `Dockerfile`） | `FROM nginx:latest AS frontend-runtime` → 从 Maven dist tar.gz 解包 → `cp -r /tmp/yak-ops/web/. /usr/share/nginx/html/`；配 `docker/nginx/default.conf`：`location / { try_files $uri /index.html; }` + `location /api/ { proxy_pass …; proxy_buffering off; proxy_read_timeout 3600s; }` | **无** |
| **D. dev server 当服务跑（本仓明确不采纳）** | 同一仓库的开发/演示通道 `yak-ops-ui/Dockerfile`（10 行，实测） | `FROM node:22-alpine` → `RUN npm install` → `EXPOSE 5173` → `CMD ["npm","run","dev","--","--host","0.0.0.0"]` | **有**（且是 Vite dev server，不是生产构建） |

⇒ 同一个仓库**并存 C 与 D 两条通道**，这是本轮新得到的一类：回答"要不要 Node 运行时"时必须先问"哪条通道"——生产镜像（C）无 Node，开发容器（D）有。

**A / A′ / A″ 与本文 §9.1 同构**——本仓方案有三个生产先例，且**先例覆盖三种框架**（Svelte / Next 静态导出 / React+Vite）。这坐实一件事：**"要不要 Node 运行时"跟选 React 还是 Vue 是两个正交问题**，只取决于是否用需要 Node server 的 SSR/ISR 形态。

**形态 C 引出一条本仓必须先查后用的事实（本轮已查）**：nginx 反代 SSE **必须显式 `proxy_buffering off`**，否则流会被攒到结束一次性吐出——症状看起来像"前端卡顿"，实为代理层缓冲，极易误诊。yak-ops 的配置就是这条纪律的实物证据（它还配了 `proxy_read_timeout 3600s`）。**本仓当前不存在此风险源**：`deploy/k8s` 全仓**零 `kind: Ingress` 资源**，`20-agent-platform.yaml:260` 明写 `type: ClusterIP   # 访问用 port-forward 或 minikube service，不直接暴露`，即访问链是 `port-forward → Pod`，**无 HTTP 反代层**。⇒ 不引入新配置；但**日后若接 ingress/apisix，SSE 路径的 no-buffering 是开工前置项而非事后排查项**。port-forward 对长流式连接的实际表现本轮未实跑，不下结论（待 §4 A2 验证时观察）。

取证注记：Langflow 本想作为第四个先例，但 `docker/Dockerfile` 路径未命中，fallback 抓到的是 `.devcontainer/Dockerfile`（uv 镜像，非产品镜像）⇒ **Langflow 的托管形态不算已取证**，不列入上表。

### 10.3 四条对本计划的直接影响

1. **§0.3 与选型文档的表述需精确化**："开源自部署多一个 Node 运行时面"这句话把 **Next 这个名字**当成了成本来源，但 **Khoj 就是反例**：它的 `next.config` 写了 `output: isProd ? 'export' : undefined` + `distDir: 'out'`，同样是纯静态、运行时无 Node（§10.2 形态 A′）。真正该否决的是**需要 Node server 的 SSR/ISR 形态**（gpt-researcher 形态 B 是实物证据：`.next` + `node_modules` 都进 final 镜像，还要 nginx + supervisord）。修正后的推论**比原表述更强**：若只用静态导出，Next 相对 Vite 的部署收益为零，而框架成本照付——这才是"不选 Next"的完整理由，而不是"Next 必带 Node"。
2. **§2.1 的 fetch 纪律在 5 个可证项目上一致，PR-1 可以不自写解帧**：11 个项目里有 **5 个**装了 SSE 解析库（其余 6 个未装，其中 Dify / Open WebUI 另背 `socket.io-client`），而这 5 个**无一使用原生 `EventSource` 构造**，全部建立在 `fetch` 之上：`@microsoft/fetch-event-source`（AnythingLLM、Flowise）与 `eventsource-parser`（RAGFlow、Open WebUI、gpt-researcher）。**此为 5/11 的证据，不是 11/11**；但本仓要携带 `X-API-Key` 头这一条已足以单独否决 `EventSource`（§2.1），无需外部背书。选 **`eventsource-parser`**（只做解析、不管重连与头），因 §2.2 要自己控制未识别事件的循环；重连与鉴权头仍由我们控。
3. **§0"第一批不装 Element Plus"站得住**：tailwind 10/11，重量级组件库只 2 例。但 n8n 给出了另一个信号：**它把组件层单独立为 `@n8n/design-system` 包**——即"用 EP 也要先封一层"。对本仓的含义：不装 EP 的同时，也不要把裸 HTML 散在业务页里，先建 `src/components/` 三个原子件即可。
4. **Vue 是少数派，这一条必须知情**：11 个项目只有 n8n 用 Vue。代价是社区示例与 AI 生成语料少；支撑本仓选 Vue 的仍是**中文企业管理台生态 + 无专职前端下 SFC 单一写法稳定性**，而 n8n 至少证明 **Vue3 + Element Plus + Pinia 在超大型产品里生产可行**。

   **但不得把"主流"读成"部署代价更低"**：换 React 的运行时成本为**零**（§10.2 形态 A″，RAGFlow 就是 Python 后端 + React/Vite 只 `COPY web/dist`）。⇒ 两栈的权衡**全部发生在开发期（生成稳定性、生态、人才池）**，不在部署期。PR-1..PR-4 的事件契约、三条错误通道、`done` 终止语义、CI JS 段、Dockerfile 多阶段骨架——**全部与框架无关**，换栈不重做。

### 10.4 未取证项（不得当结论用）

- **各家 SSE 帧是否用具名 `event:` 行**——本仓 `_sse` 把 `payload.type` 提升为 event name；这一做法是否主流**未拿到源码证据**（猜测的 4 个文件路径全 404）。
- **各家对"未识别事件类型"的处理**——同上，无证据。
- **其余 6 个项目的流式传输方式**（未装两个已知解析库的那些）——可能是 WebSocket、自写 reader 或其他库，本轮**未取证**，不得拿它们给"fetch 是共识"加权。
- **各家是否真的不用 `EventSource`**——只能证明装库的 5 家基于 fetch，**不能证明未装库的 6 家没用原生构造**（未 grep 其源码）。

上述四项仍只能以本仓 `serialize_stream_event` + `_node_event` + `console.html` 为唯一依据（§1/§2.2）。

### 10.5 yak-ops 专项：它是"工程约束可迁移"的那一类参照

`weifuwan/yak-ops`（大数据治理平台，主语言 Java，59 stars，末次推送 2026-10-28）与上面 14 个不同：**价值不在栈分布数据点，在工程约束与门禁可直接搬到本仓**。以下均为本轮实测内容。

- **结构同构度最高**：`yak-ops-ui/apps/web`（产品应用）+ `yak-ops-ui/packages/yak-ui`（领域无关控件，公共 API 收在 `src/index.ts`）—— 与本仓 `web/` + `src/components/` 一一对应。它用 npm（`package-lock.json`）而非 pnpm，与本仓 §9.2 是口味差异，不影响。
- **依赖面极克制，且比 n8n 更贴本仓规模**：`apps/web` 仅 7 个 deps（`react` `react-dom` `react-router-dom` `@tanstack/react-query` `echarts` `lucide-react`），`yak-ui` 仅 2 个（`@base-ui/react` `class-variance-authority`）——**无 MUI / antd / element**，组件层自建。这是 §10.3 第 3 条"先封一层"的实例，并给 §0"第一批不装组件库"提供了比 tailwind 计数更硬的证据：**不装库也能把管理台做完**。
- **分层规则与本仓 §9.3 几乎重合**：`app/<domain> → service/<domain> → service/http`、"HTTP transport 集中（含一致的响应与鉴权错误处理）"即本仓 `src/api/client.ts` + `errors.ts`；"domain service 不得依赖 App 代码"即本仓 `events.ts` 不得 import 组件。
- **门禁可搬，本仓已采纳一项**：`yak-ops-ui/scripts/check-architecture.mjs`（232 行）做三类存在性断言——`forbiddenDirectories`（遗留目录不得复活）、`requiredAppShellFiles`（**硬编码 21 个具体路径必须在位**，防功能被静默删除）、`forbiddenFeatureForwarders`（已删的兼容转发层不得悄悄回来）。本仓采纳**中间那类**，落成 §9.3 的 `scripts/check-events.mjs`：断言 §1 的**事件全集（2026-10-30 按源复取 = 12 类，上一版此处错写 13）**在 TS 联合与 handler 分支中一一对应，缺则 CI 红；**期望集从三个出口源派生，不写死数字**（§12 第 1/2 条）。这把 §2.2"未知事件不吞"从**人工核对变成机器判**。
- **测试可搬，但必须定性**：20 个 `scripts/verify-*.mjs` 是两层混合——① `import` 被测 `.ts` 纯函数做 `assert.deepEqual`（样：`getExecutionProgress("RUNNING", 37)` 的 9 个枚举分支逐一断言）；② `readFileSync` **读 `.tsx` 源码文本**做字符串断言。`engines: node >=22.13` 正是为 Node 原生 type-stripping 服务，**因此全程没有 vitest/jest/Playwright**。本仓 §9.2/§9.3 原本也未引测试框架，与此一致，不新增依赖。但第 ② 层是**脆断言**（改个变量名即红），**只适合锁结构不变量（事件分支齐备），不得用来锁行为**——否则与本仓 AGENTS.md「禁止收窄断言凑绿」红线相互缠绕。
- **一条纪律已上升为本文 §3 第 4 条**：`FRONTEND_RULES.md` 的 "Components must not parse HTTP envelope details or **turn API failures into successful empty results**"，正中本仓 error→`done(answer:"")` 的形状；同文 "Do not create speculative `common` or `shared` layers" 比 §10.3 第 3 条更硬，本仓 `src/` 划分按此执行。
- **不照抄的三件**：多页路由 + workspace 切换 + 历史 URL 重定向（本仓最小核心无前端路由，§9.1 已定不做 SPA fallback）；**前端产物经 Maven assembly 进 tar.gz 再解包**（本仓无 Java 构建链，走 §9.3 的 Dockerfile 多阶段 `COPY --from=builder`）；上表的形态 D。
- **一条必须拆开的混淆（与本仓决策直接相关）**：本节采纳的 yak-ops 做法——分层规则、`requiredFiles` 存在性断言、不引测试框架、依赖面克制——**全部与选 React 还是 Vue 无关**。反而 Vue 的 SFC 把 template 与 script 放在同一文件里，`check-events.mjs` 这类源码文本断言在 `.vue` 上**更好写**（一次 grep 同文件即可同时验事件名与模板分支）。⇒ **观赏这套工程纪律 ≠ 要换 React**；两者应当分开拍板。

## 11. 拍板落地记录（2026-10-29）与仍未获表态的三项

### 11.1 已落地（三处同批，无一处只改本文）

| 文档 | 改了什么 |
|---|---|
| `docs/adr/0010-ui-stack-selection.md` | 状态行由「未决」→「已决（选 C）」；**只追加其 §6，不重写其 §1–§5 历史论述**（ADR 是决策记录，改写历史等于销毁证据；这里的 §6 指该 ADR 自身小节，非本文 §6） |
| `docs/plans/plan-frontend-stack-selection-2026-10-27.md` | 状态行「待拍板」→「已拍板（仅栈一项）」；§7 三点逐项标 ✅/⚠；§8 决策日志**保留不删** |
| 本文 | 状态行改为用户已拍板；新增本节 |

### 11.2 本轮新发现的一个坑：两个"A"同名异义

选型文档 §7 第 2 点原写"确认错误契约走审计倾向的 **A 方案（4xx 统一为 `{code,msg,request_id}`）**"，而 `packages/agent-core/agent_core/guardrails/errors.py:15-16` 定案的 **D-2=A** 结论是"**不改** 4xx 的 `{detail}` 信封"——**两个 A 的含义正好相反**。

这条直接影响本文 §3 的结论是否合法：§3 说"`docs/TODO.md` §1 第 104 行那条 P0 可以关掉"，**关掉是对的，但理由必须是"后端已定案为不收敛 4xx"（以代码为准），而不是"审计的 A 方案已获批"**——后者从未发生。若误读成后者，会得出"4xx 已收信封"的错误契约，前端 `describeError` 的 4xx 分支就写错。已在选型文档 §7 就地标注"引用时不得裸写 A 方案"。

### 11.3 三项待表态——**已于 2026-10-29 同日采纳**（用户原话"按推荐的方案继续"）

| # | 事项 | 采纳结果 | 回滚影响面 |
|---|---|---|---|
| ① | 是否取消 roadmap #18 的 A 取证步骤 | **不取消、守原顺序——但采纳后开工即发现原顺序本就不需要改代码**（§11.5）。当时的实测依据"页面只缺 revert、半天可补"是**错的**：revert 不属 #18 判据，且补它违反基线 6。已采纳的结论（走 A 取证）仍成立，理由换成"现状页面已覆盖四步" | 已全量回退 `console.html` 改动（`git diff` 为空、12 passed）；ADR §6 同步订正 |
| ② | `web/` 目录名 + 是否随批更新两份目录表 | 定名 `web/`，随 **PR-0** 同批改 `AGENTS.md`/`ARCHITECTURE.md` | §9.3 |
| ③ | `eventsource-parser` 新依赖 | 采纳，PR-1 用它做 SSE 解帧 | §2.1 与 PR-1（退回自写只改 `src/api/sse.ts`） |

**读法提醒（不得被"已采纳"掩盖）**：这三项是**整体采纳**而非逐项讨论——"按推荐的方案继续"未对 ②③ 单独表态。若其中某项与本意不同，说一项即可定位到上表的回滚面。

### 11.4 提交边界（本轮实测出门禁盲区，必须记住）

`docs/adr/0010-ui-stack-selection.md` **已入库**，而它的**状态行**引用了 `plan-frontend-stack-selection-2026-10-27.md` 和本文——两份都**不在版本控制清单内**（`git ls-files --error-unmatch` 双双 exit=1，本轮实测）。⇒ 已入库文档指向仓内不存在的路径，就是本节下方清单要防的事。

**同批必 add 清单（2026-10-29 取证批，5 项；末列只算「按路径」的引用边。取数口径 = `git grep -F --untracked -e <路径> -- "*.md"`；**不是终态**，复跑读数见下表后注）**：

| # | 路径 | 现态 | 按路径引用它的地方 |
|---|---|---|---|
| 1 | `docs/adr/0010-ui-stack-selection.md` | M（已入库） | — |
| 2 | `docs/plans/plan-frontend-stack-selection-2026-10-27.md` | ?? | ADR **状态行 L3**（带 §4.1 锚）、本文 |
| 3 | `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` | ?? | ADR **状态行 L3**、取证件 L18 |
| 4 | `docs/operations/evidence/2026-10-29-roadmap-18-console/` 内的 **3 件**（`readings.md` + 两支探针）——**5 张 PNG 不入库**（用户 2026-10-29 批示，口径见取证件 §4.1）⇒ **禁止对整目录 `git add`** | ?? | **仅本文 §7 PR-00 行**一处（它是本批交付件本体）|
| 5 | `docs/research/react-nextjs-ssr-seo-deep-research.md` | ?? | 选型文档 §2 对比表 Next.js 行（本轮新增引用）|

注：ADR §6 对其余三件的指代是**文字**（"选型文档"、"实施件 §11.5"、"取证件"）而不带路径 ⇒ 不构成悬空路径断言，也就不进上表。

复跑（rev `896f966e`，脚本 `.tmp-scratch/c-mask/nb307_recount.py`，作用域 `*.md`，两口径都报）：默认（仅已跟踪）口径下 **#4a/#4b/#4c/#5 四项的引用边全为 0 行**——这批文档彼此都在未跟踪态，默认 `git grep` 扫不到它们，拿它取“零引用边”会把结论读反（读成“可以不入库”）。带 `--untracked` 实测：#2 = **9 行 / 4 文件**、#3 = **6 行 / 5 文件**（含本文自指 1 行）、#4a = **2 行 / 2 文件**、#4b = #4c = 各 **1 行 / 1 文件**、#5 = **3 行 / 2 文件**、#1 = **13 行 / 6 文件**。⇒ 上表末列是**写下那一刻的快照**，引用边只会随后续轮次增加（现已增加：#2 实取 4 文件而表内记 2 个引用者）；本清单的用途（这些件必须同批入库）不因数字变化而失效，但原写文中的“终态”两字已撤。

⚠ 工作区另有**不属于本批**的未提交改动，不得混入：`AGENTS.md`、`docs/operations/nl2sql-release-checklist.md`、`docs/operations/unconfirmed-items.md`、`docs/operations/evidence/2026-10-28-nl2sql-release/` 及**两件 10-28 旧线回捞件**（10-29 那轮它们是 `AM` 态；本轮同 rev 复跑：索引已空、两件为 `??`，逐项读数见下一段）——本批三处已跟踪改动（`AGENTS.md` / `nl2sql-release-checklist.md` / `unconfirmed-items.md`）内容全为 **10-28 nl2sql 发布批次**的 126 构建/IO 守卫读数（与前端无关）。⇒ 提交必须逐路径 `git add`，**禁用 `git add -A` / `git commit -a`**。

**但逐路径 `git add` 防不住“已经在索引里”的件（机制仍成立，本行原先的状态读数已过期）**：10-29 那轮实测 `git diff --cached --stat` = 379 行新增（全为 10-28 批次的“旧线逐字回捞”件）；**本轮同 rev `896f966e` 复跑 = 0 行**（rc=0、空输出），两件现处 `??` 未跟踪态 = `docs/analysis/2026-09-21/05-exhibition-positioning-evaluation.md`（回捞自 blob `460da734`）与 `docs/operations/evidence/2026-10-13-business-corpus/readings.md`（blob `874e4cad`；两 blob `git ls-tree -r HEAD` 命中 **0** ⇒ 当时它们只存在于索引）。它们如何退出暂存，本轮**未逐文件追认**（HEAD 未动 ⇒ 期间无 commit）。
⇒ 留下的判据与具体动作分开：**`git commit` 提交的是索引不是工作区**，所以提交前必须先 `git diff --cached --stat` 看索引里有什么；上一条“先 `git restore --staged <两件>` 再逐路径 add”的**具体步骤当前无需执行**（索引已空），但**只要跑过一次 `git add -A` 它就重新成立**（本仓 10 个已跟踪修改文件横跨两批内容）。

**待提交面的敏感内容逐项扫描（2026-10-29 本轮实取；面 = 14 件未跟踪 + 7 件已改 − 交集 = 21 件，合计 406,679 bytes）**：

| 扫描项 | 手段 | 命中 | 判读 |
|---|---|---|---|
| 凭据赋值 | 正则找 api_key / secret / token / password / access_key / authorization / bearer 后跟 `:` 或 `=` | 4 处 | 全是**空值赋值或文字描述**（探针跑的是 `API_KEY=""` 即鉴权关；`bce-auth-v1%2FALTAK…` 是被截断的“一律排除”说明）⇒ **无活凭据入面** |
| 内网标识（按门禁自己的 7 条模式复判） | 本机脚本 `.tmp-scratch/mirror_prejudge.py`（直接 import `lint_public_mirror` 的 `_PATTERNS` 与 `_skip_hit` 扫工作区 ⇒ **不提交就能预判**） | **2 处，均不属本批**：`nl2sql-release-checklist.md:98` = `<internal-node-01>`（P-2 主机名）、`evidence/2026-10-28-nl2sql-release/readings.md:139` = `<operator-lan-ip>`（P-1）。本批 9 件 + corpus 暂存件**零命中** | 两处都**未登记台账、未获豁免** ⇒ 一旦提交，registry 模式按 L244-250 当场报 **P-4**，而 registry 在 `make lint` 里 ⇒ **`make ci` 会红**。提交前必择一：换成 `<internal-*>` 占位符，或在 `_REGISTRY` 登记“为何 legitimately 保留 + 推镜像时怎么脱敏” |
| 个人绝对路径 | 正则找 osmondy / `X:\Users` / `X:\Study` 形态 | 原 2 处 → **本批 1 处已就地改掉**（本文 §0.3），剩 1 处属 10-13 批次 L15 未动 | 仓内不可能存活的本机路径，引用它对后人只造噪声 |
| 二进制 | `git status --short -uall` 逐项 | **0** | 5 张 PNG 已移出跟踪面（取证件 §4.1） |
| PII / 商业敏感 | 手机号 / 身份证 / `tenant_id=` 字面值 / 公司名 / 金额词 | **0** | 探针与取证件只带合成 thread_id 与本地健康检查降级页读数 |
| ruff | `uv run --with ruff ruff check` 对六支探针 | rc=0 | `make lint` 的 `ruff check .` 会扫到 `docs/` 下的 `.py` ⇒ 不干净就会红 CI |

**上表“内网标识”那一行是订正**（本轮首遍扫描我把 `checklist:98` 判成假阳性，因为输出被截断没看清；当时报的“2 处 IP”里 corpus 那处的 `LLM_BASE_URL` 其实是公网域名 modelscope、门禁不判）。⇒ 待提交面的真新增 = **2 处内网标识（1 主机名 + 1 IP）**，不是“2 处 IP”。

另记一条**存量口径与本批无关但必须说清**：真实内网标识早就已在仓里——HEAD 树内 3 个已登记文件携带真实网段/主机名（`docs/operations/env-126-inventory.md` 为最大一处），这是《分支卫生》#4 明文允许的形态（防线在公开镜像那层，不在“不进内网仓”）。另有 **2 个测试文件靠“路径形状豁免”过关**，其中 `tests/governance/test_cache_single_track_governance.py:188` 命中的是**真主机名 `<internal-node-01>`**（不是合成 fixture），而 `_skip_hit` 不看内容只看路径、publish 模式又与 registry 共用它（脚本 L289）⇒ **真机名可以随测试文件上公开镜像**。这条是门禁真缺口，堵法属仓级策略变更（改豁免分流，或把那行注释遮成 `<internal-node-01>`），**本轮只登记不动**。

⚠ **与上面 docsync 盲区同族的第二条**：`lint_public_mirror.py` 的枚举口径是 `git ls-tree -r <ref>`（脚本 L144）⇒ **未跟踪与暂存内容它根本看不见**。所以今天 registry 模式 rc=0 **不构成“本批内容可安全进公开镜像”的背书**；那两处内网标识（1 主机名 + 1 IP）一旦提交就进扫描面，必须在提交后、推镜像前另跑 publish 模式对**该树**实测（《分支卫生》#4 的原要求，本轮补的只是“提交前的 rc=0 不能当背书”这句读数口径）。

> **复跑订正（2026-10-30，按批次提交批 B5 落库时实取）**——上面那张敏感内容表的读数已部分被后续批次推翻，别再照它行动：
> - 「内网标识」行那条 **预测**（“两处一旦提交 ⇒ registry 当场报 P-4 ⇒ `make ci` 会红”）**没兑现**。本轮拿门禁同一套 `_PATTERNS` 逐行复扫待提交面：B5 四件 **0 命中**、B6 两件 **0 命中**。成因 = B3（提交 `efe938c1`）把真值就地遮成占位符，包括本节 L339 点名的 `test_cache_single_track_governance.py` 那一行（+1/−1）。现取两例：`nl2sql-release-checklist.md:98` 装的是占位符 `<internal-node-01>`；`evidence/2026-10-28-nl2sql-release/readings.md:139` 已不是当时的命中行而是表格分隔符 `|---|---|---|`（文件增长后**行号漂移**）⇒ 本文里按行号写的坐标都要先复跑再引。
> - L339 登记的**机制缺口仍成立**（`_skip_hit` 至今只看路径不看内容，真机名可以随测试文件上公开镜像），但**该实例已消失**；堵法（改豁免分流 vs 逐处遮蔽）仍是 D2，本轮未动。
> - registry 模式在 B4 入库后复跑：`1 文件 / 1 命中 / 台账 1 项 / 违规 0`，rc=0。上一段那句“未跟踪内容它看不见 ⇒ rc=0 不构成背书”**依旧有效**，推镜像前仍须对该树实测 publish 模式（本轮未做，属 D3 待批示）。

且这个悬空**不会被门禁抓到**：`scripts/check_doc_sync.py` 只校 AGENTS.md / ARCHITECTURE.md / README.md 的引用路径（本轮实测：改完 ADR 后它仍 exit=0）。⇒ AGENTS.md 那条"存在性判定基准 = 版本控制清单"的纪律，作范围上**覆盖不到 `docs/adr/` 与 `docs/plans/` 之间的互相引用**；引用是否悬空只能靠提交时把同一批文档一起 `git add` 来保证。要堵这个洞得扩 `check_doc_sync.py` 的扫描面，属另行方案（本文不做）。

**同一盲区本轮抓到一条真实的错锚（2026-10-29）**：选型文档 §0「项目类型」行原引 `docs/research/competitive-landscape.md` **§1.4**——该文件在版本控制清单内（`git ls-files --error-unmatch` exit=0），路径断言因此**本来就绿**，但它用的是中文数字编号（一/二/三 + 2.1/3.1），**全文没有 §1.4**；所指内容实际在 §3.3（L135）。⇒ 两条可复用的结论：① **路径存在 ≠ 锚点存在**，跨文档引用要校到小节级；② 这类错锚能长期存活，是因为它落在门禁扫不到的那两类边上（§-锚 + 非根三文档）。已就地改为 §3.3 并附原文行号。

**交付前自检扩到三个维度后又抓到第二条（同日交付前自检复跑）**：ADR-0010 §6 L54 原写“选型文档 **§10** 风险表”，而选型文档最大编号到 §8，风险表在 §6（同口径另见其 §4.4）——已就地改为 §6 并在该行留下错锚记账。这一条与上一条不同型：**路径/别名都在，错的是“别名指代”的解析**（行文用“选型文档”而非路径，门禁与路径断言都扫不到）。⇒ 自检脚本（`.tmp-scratch/selfcheck_docs2.py`，不入库）因此扩了三类断言：行号引用（形如“文件名冒号行号区间”逐条比实际行数）、别名→文档映射（选型 / 实施 / 方案 / 取证件）、条目锚（形如“§X-#N”要在小节内真有第 N 项）。六份文档的硬断言（路径 / 行号 / 本文内悬空锚 / 条目锚）失败 0（后出的体检件与 ADR-0012 并入后为八份，取证件 §5 复跑读数为准）；脚本给出的“跨文档待判”清单逐条人工判过，其中两处是本文与 ADR 故意留下的错锚记账复述（上两条的“原写 §1.4 / §10”），余下均为“行内最近路径”启发式误挂，所指小节在本文内均存在。

写法口径本轮也定了一次（避免下轮再翻）：本文与其 §11.7 引用的 gitignored 路径（`.tmp-scratch/selfcheck_docs2.py`、`.tmp-scratch/wt-main`）**保留反引号**。判据三条，均实取：① 「本机才有、不入库的路径写成普通文本」那条纪律的作用域是门禁扫描面（`check_doc_sync.py` 的 `DOC_FILE_REF_DOCS` 只有 AGENTS/ARCHITECTURE/README 三份，且其 docstring 明写「新增仓内路径引用时仍应写反引号，让门禁真正校到它」）⇒ `docs/` 下的件不受该门管制；② 仓内既有入库文档对 gitignored 路径一律用反引号（`docs/operations/evidence-format.md` §4、`testing-playbook.md`、`observability-pitfalls.md` 三处实取，均过 CI）；③ 去掉反引号会让引用从本件自检脚本的 [P] 类断言里消失，正是那份 docstring 记的代价「去掉反引号即可静默逃逸」。两处引用点自身都带「不入库」字样，不会被读成仓内路径。该自检脚本的 [P] 类只判**带扩展名的文件路径**（`PATH_TAIL` 以已知后缀结尾），所以无扩展名的目录引用（wt-main 这种）本来就不进断言面 ⇒ 这是脚本的已知漏报面，本轮如实登记，**不当成“已校过”**。探针文件用 `grep` 式检索时须注意 regex 元字符坑：本轮实取 `docs/operations/*.md` + `docs/plans/*.md` 中无任何被转义的 `\.tmp-scratch` 写法（命中 0），故用普通子串检索不会误伤。

**调研件归位（同一轮）**：原落在仓库根的 `DEEP_RESEARCH_React_NextJS_SSR_SEO.md` 已移为 `docs/research/react-nextjs-ssr-seo-deep-research.md`（该目录惯例 = kebab 主题名、无日期前缀；根目录只应留 AGENTS/ARCHITECTURE/CHANGELOG/README 四份 md，本轮实取）。移动前已验：文件**未入库，且无文档按旧路径引用**。取数命令与两口径读数（本轮复取，rev `896f966e`）：`git grep -n -F --untracked -e "DEEP_RESEARCH_React_NextJS_SSR_SEO.md" -- "*.md"` → **1 行 / 1 文件**，而那唯一一行**就是本句自身**（不是“它自身文件”——被移动的文件正文不含自己的路径）；不带 `--untracked` 的默认口径 → **0 行**（本件未入库 ⇒ 默认扫不到，“零引用”会读成“没扫”的假读数）。新路径的反向引用边 = **3 行 / 2 文件**（选型文档 1 + 本文 2）。⇒ 结论（移动零风险、无需改写历史）成立，但**只在 `--untracked` 口径下成立**，且证据形状是“唯一命中为断言自身”这一自指型。

### 11.5 取证批开工即反转：#18 缺的是证据，不是代码（2026-10-29 实测）

按 ① 采纳后动手给 `console.html` 加 revert 交互（+76 行），跑该页在册测试，**2 条红**，随即全量回退（现 `git diff` 为空、`test_console_router.py` 12 passed）。反转链条四条：

1. **#18 判据原文不含"回退"**：`docs/plans/plan-production-delivery-roadmap-2026-10-09.md:94` 写改法四步 = **提问 → 执行 → 展示过程与结果 → 错误提示**，判据 = "一条完整业务链路真跑通，留截图与日志；不新增后端专用接口"。`/session/revert` **不在其中**。
2. **它是选型文档自己加的**：选型文档 §0 第 1 条"缺的只是 `/session/revert` 交互与留证"与 §4.2 P0 行"补 `/session/revert` 按钮"。根源是把"新前端**最终**要复用的接口"（`docs/TODO.md:95` 确实列了它，但那是给 `web/` 的）误读成"#18 取证必须做的环节"。已在选型文档就地订正并留痕。
3. **补它还撞上一条架构边界**：`applications/agent_server/tests/test_console_router.py:22` 将 `/session/revert` 列入 `_FORBIDDEN_ENDPOINTS`，`:19` 白名单只 `{query, history, health}`，docstring 依据 = **1.2 基线 6「运维动作不进浏览器」**。该测试还禁"注释里残留写入口引用"（所以连解释性注释都不能写那个路径），我两条都是靠实跑而非阅读发现的。
4. **ADR-0010 §3 那句要重新读**：原文"「已有控制台 ⇒ #18 已满足」：不成立……这条判据目前**没有任何证据**"——它否的是**没证据**，不是**没功能**。⇒ 取证动作本身即可关 #18。

**教训（可复用的那一条）**：给人推荐"守原顺序 vs 跳过"这类权衡前，除了查"缺什么"，必须同时查**两件事**：① 判据**原文**到底要求什么（不要拿自己上轮写的二手描述当判据）；② 要补的东西有没有被**在册测试/架构边界禁掉**。两项都是分钟级实测，我当时都跳过了，代价是白写 76 行 + 三处文档返工。

**顺带查实的硬缺口（本轮真正的产出，已写进 PR-3 开工前置）**：`checkpoint_id` 从现有对外接口**取不到**——`RevertRequest.checkpoint_id` 必填（`applications/agent_server/schemas.py:188`），而 `/history` 的 `HistoryItem`（`applications/agent_server/schemas.py:199-204`，字段只有 `index/role/content/id/created_at`）无此字段，SSE 全部出口帧也不带（`query_router.py:207,372,379` 的 `done` 只有 `type/thread_id/answer`；全仓 `checkpoint_id` grep 排除测试后无一处在出口侧）。⇒ `web/` 的 revert 交互在现有接口下**做不出可用形态**（否则只能让人手抛一个 uuid），必须先出方案定夺。

> **坐标补全（2026-10-30 前置核查）**：本段上一版写的是**裸文件名** `schemas.py:188` / `:199-204`，而仓内 `git ls-files` 有两个 `schemas.py`（`applications/agent_server/schemas.py` 与 `packages/agent-runtime/agent_runtime/schemas.py`）⇒ 内容逐条对得上，但坐标不可唯一解析，已补全路径。

### 11.6 PR-3 前置已出方案：三层缺口，不是"只是取不到 id"（2026-10-29）

接 §11.5 最后那条缺口动手出方案时，实测发现它比原描述严重点多。三层（编号与方案件一致）：

| 层 | 一句话 | 与 PR-3 原描述的关系 |
|---|---|---|
| **A** | Planner 主路径每线程恒只有一条 checkpoint（原地覆写）⇒ **根本没有历史点可退** | 原描述未涉及：即使把 id 曝出去，退的目标也只能是自己 |
| **B** | `packages/agent-runtime/agent_runtime/revert.py:77`（2026-10-30 补全路径：该文件不在 `applications/agent_server/api/`，那里叫 `session_router.py`）用随机 uuid4 作新行 id，读侧按字典序判最新 ⇒ **抽样 8%–13% 静默失效**；赢了的那条又**永久遮蔽**此后写入 | 原描述未涉及，且它是 A 的**硬前置** |
| **C** | 新行 id 不对外 + `/history` 不列举 checkpoint ⇒ 无任何接口可取 id | 就是原描述那一条（它是最表层、也最易发现） |

关键一条：**A 正在用它的"无害"掩盖 B**——今天 `append_thread` 继承遮蔽行自己的 id 继续原地覆写，所以 B 不发作；
一旦按原计划"让 checkpoint 累积"，B 立即发作。⇒ **"先修 A 再说 B" 这个自然排序被实测否证**。

产物：
- 方案 `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md`（含三个形状候选 A1/A3 + 五条**已否决项**及其实测反证 + 分期 + 非空转反证表 + 6 项待拍板）
- 取证件 `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/`（四支可复跑探针 + readings）

**本批（revert 完整性）必 add 清单（与 §11.4 的 5 项分属不同批次，不得互混）**：

| # | 路径 | 现态 | 按路径引用它的地方 |
|---|---|---|---|
| 1 | `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md` | 新文件（未入库）| 本文 **§7 PR-3 行**（本轮新增）|
| 2 | `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/`（readings + 4 探针）| 新目录（未入库）| **仅方案件首部「证据件」行**一处 |
| 3 | 本文 | 未入库 | 方案件 §9 回填表 + 取证件 §0 |

⇒ 三件必须同批，否则又是一次"已入库文档指向仓内不存在路径"（§11.4 要防的同型事故）。
提交仍需用户显式批示，逐路径 `git add`。

### 11.7 同日另一件：分支月度体检（AGENTS.md《分支卫生》#3）

本轮把月度体检跑了（体检本身只读；处置阶段经批示执行了 1 条本地删除），产出活文档 `docs/operations/branch-hygiene-monthly-checks.md`（命令面 + 2026-10-29 节）。三条需要人看的结论（详细读数在那份件里）：

1. **死枝 1 条→已退役**：`feat/nl2sql-meta-build-recovery`。本轮首判只查了 git 拓扑三件就建议当场 `-d`——**错**：`docs/adr/0012-nl2sql-branch-consolidation.md` §2 把它登记为“唯一 nl2sql 集成分支”，且同件 §4 行 44（10-27 体检）**早已预判**“0 独有不构成死枝判据”⇒ 我是没读完同件就下结论。用户批示「先合后删」后执行：`git merge` → `Already up to date.`（no-op，tip `f6a6b9d8` 本就是当前线祖先）→ `git branch -d` **被拒**（带 upstream 时 `-d` 校“已合入 upstream”而非 HEAD）→ 补取硬判据后在 ADR-0012 §4 写退役结论 → `git branch -D`（本地 9→8，`is-ancestor f6a6b9d8 HEAD` rc=0 复验不丢提交）。全过程与两条可复用结论在体检件 §3。
2. **分支模型终态与现状不符**（三项 D2，需人拍板）：`company` 只有 1 条 `main`（无集成分支）、那条 `main` 是与本地历史**异宗的 2 提交快照线**（`merge-base` rc=1）、本地 `main` 与当前工作线**互相领先**（6 vs 339）。⇒ 这些不是体检能修的，也不是我能顺手定的。
3. **一条旧登记已过时**：`docs/adr/0013-semantic-cache-single-track.md` §9 行 56 第 ④ 项登记的 `.tmp-scratch/wt-main` worktree 本轮 `git worktree list` 已不含它——该行自称时点快照，故**不在那里改写**，以体检件为准。

**体检件的引用边**（入库时必须与本文同批）：它只被本文本节按路径引用，自身不指向任何未入库路径（自检实取：路径/行号/锚点/条目四类均 0 失败）。

⇒ 本小节另带一件已入库文档的改动，**必须与体检件同批 add**：`docs/adr/0012-nl2sql-branch-consolidation.md`（M，§4 新增 2026-10-29 退役登记）。它与上面 §11.4 / §11.6 两批都不同属（那两批是前端与 revert 完整性），若分拆会再造一次“已入库 ADR 指向尚未入库的体检件”。

## 12. 开工前置核查（2026-10-30，rev `3868023c`）：六条订正 + 两条待拍板（同日已答，见本节末表）

**取证件**：`docs/operations/evidence/2026-10-30-frontend-preflight/readings.md`（41 条坐标逐条命中、事件全集与 `/health` 字段集的直读输出都在那里）。
本文本节只写“改了哪六条、拍板了哪两条”（两条的答案在本节末表第五列，含落在本文哪一节；#1 事件数与 #5 字段数同属一类：**散文里的数不等于源里的数**），§5 前置三件事、§7 工单表、§9.3 文件清单、§10.5 门禁那一段均随之同步。坐标复验能全命中不是巧合：`git diff --name-only 896f966e..HEAD` = 30 个文件，
其中 28 个是文档，**未触碰任何被本文引用的后端实现**。

| # | 订正 | 为什么这不是抠字（不订的后果） |
|---|---|---|
| 1 | 事件类数 **13 → 12**（§1 / §7 PR-1 / §9.3 / §10.5 四处同改） | `check-events.mjs` 是本文采纳的**机器判**（§10.5）：它一入库就带着一个源码里凑不出来的常数，实现者只能二选一——把门禁写成永不可满足（红到被人关掉）或硬凑第 13 类（假绿）。两者都是把「非空转」判据直接破坏掉 |
| 2 | 事件期望集改**派生式**，并加一条后端侧断言 `StreamEventType` Literal ⊆ `serialize_stream_event` 分支集（§1 / §9.3） | Literal 加一项而分支没加 ⇒ `serialize_stream_event` 返回 `None` **静默丢事件**（`:792` 自陈），运行期零症状；前端连「未处理的事件类型」都报不出来，因为它根本支不到。§2.2 管的是客户端那半，后端这半以前没人管 |
| 3 | CI 两处 `paths:` 补 `web/**`（§5 / §9.3） | 只改前端的 PR **不触发 CI**；A5 那条反证会拿到一个「门禁没跑」当成「门禁放行」的假绿——这两种绿在账面上长得一模一样 |
| 4 | `.dockerignore` 补 `**/node_modules` 与 `web/dist`（§5 / §9.3） | 该文件自己就是证据：`**/__pycache__` 带 `**/` 而 `node_modules` 不带 ⇒ 不带斜杠只命中根。后果是宿主几百 MB `node_modules` 进上下文，以及本机预建的 `dist` 进镜像遮蔽 builder 产物（与本仓记过的「可变 tag + IfNotPresent ⇒ 静默跑旧代码」同族） |
| 5 | `/health` 字段集 **13 → 30**，并把权威源从 `console.html` 改为两层模型（§1） | PR-4 的判据是「每盏灯的文本可追溯到字段值」。漏 17 个里包括 `revert` / `admission` / `cache_ready` / `langfuse_ready` —— 恰好最能区分「接线」与「启用」的那几盏 |
| 6 | 坐标补全路径（§11.5 / §11.6）+ 顺手修 `README.md:643` 一条过期行号 | 仓内两个 `schemas.py`，`revert.py` 不在 `api/`；README 那行引 `health.py:25-40`（实际是 `DependencyHealth` 区间，`HealthResponse` 在 `:67`）。`check_doc_sync.py` 只校路径存在性不校行号⇒ 这类错锚不会被任何门禁抓到，只能靠引前复跑（本文 §11.4 记的同族） |

**两条待拍板 → 同日已答（2026-10-30，用户拍板）**

| # | 事项 | 候选与推荐 | 不拍的后果 | 拍板结果与落在本文哪一节 |
|---|---|---|---|---|
| A | JS 门禁落点（§9.3 新增的 `Makefile` 行） | 形状一：并进 `make ci`（忠于 workflow `:45` 那句「复用 `make ci` 单一真相」，但 `Makefile:158` 的 `ci = lint test eval` 从此要求 Node 在场，无 Node 的机器跑不动 `make ci`）；**形状二（推荐）**：新增 `make ci-web` 目标 + workflow 加一步 `run: make ci-web`（与已有的 `make test-cache-contract`（目标在 `Makefile:77`、步在 workflow `:87`）同形态，命令仍在 Makefile 里，不违 `:45`，Python-only 环境不受影响） | PR-0 开工时实现者只能替本文选一个，而选完就写进了 CI——拍板前这是本文 §0「决策完备」那句唯一真破了的地方（已闭合，见末列） | **形状二已采纳** ⇒ §5 首条与 §9.3 的 `Makefile` / workflow 两行已改写为定死形（`ci-web:` 目标 + `.PHONY` 同步 + `ci:` 不动）。这一格从此不再是选择 |
| B | `docs/TODO.md:103` / `:104` 两条勾沉（§5 新增那条） | 三条都该动：`:103` 选型已被 ADR-0010 定为 Vue3（本文行仍写「未定…不预先绑定 Vue/React」），`:104` 审计件已入库且 D-2 已定案，`:105` 仍是开项（它的交付物就是 PR-0 的 CI 段）。⇒ `:53` 那行「前端 | 3」随之变 1 | 账面与现实不符。危险方向只有一个：**下一个人拿 `:103` 那句「未定」当活的重新评一轮选型**，而不是把已定的当未定 | **本轮不动，随 PR-0 落地那一批改**（已采纳）——与 §5 那条「PR-0 同批」的原约束一致，不是额外偏离。**复审触发条件**：PR-0 提交时若 `docs/TODO.md:103` 仍写「未定」则该批不得合（账面未跟项堆到 3 条以上就会重现今天这个“文档与 ADR 冲突”的形状）|

**新增门禁的非空转反证表**（按 `docs/operations/evidence-format.md` §4 要求，PR-0/PR-1 交付时逐项实取，本批先定形状）：

| 变异 | 期望 |
|---|---|
| 从 `events.ts` 的 TS 联合删一个成员（不动 handler） | `check-events.mjs` 报红（存在性判据击中） |
| 从 handler 删对应分支（不动 TS 联合） | `check-events.mjs` 报红（双向都对得上才算一一对应） |
| `StreamEventType` Literal 添一项、`serialize_stream_event` 不加分支 | 新增那条后端侧断言报红（§12-#2 那招不是装饰） |
| 把事件全集写回一个硬常数（如 12）后删一个出口字面量 | 仍须报红——派生式的价值就在这里：写死数的版本这一格会“凑巧绿” |
| 把一个只改 `web/` 的提交推上去 | CI **必须跑**（`paths:` 补了 `web/**` 才绿；没补就是本表唯一能抓到第 3 条订正的手段） |

**2026-10-30 二次核查（rev `f659c02f`，本批只做一件事：确认 §1–§10 的后端坐标不需重取）**：`git diff --name-only 3868023c..HEAD` = **12 个文件**，其中 11 个在 `docs/` 下；唯一非 `docs/` 的根 `README.md` 那一行就是本节 #6 自己的订正（hunk 头 `@@ -640,7 +640,7 @@`，改前改后各 1 行）。⇒ 判据不是“我没看见改动”，是**这些路径在两棵树里内容逐字相同**：`applications/`、`packages/`、`scripts/`、`Makefile`、`.github/workflows/`、`Dockerfile`、`.dockerignore`、`docs/TODO.md` **零文件出现在清单里** ⇒ 41 条行号坐标与「12 类事件 / 30 个 `/health` 字段」两组直读数在本 rev 仍成立。**换 rev 仍须复跑**：上面那条 diff 清单就是复跑入口，不必重取 41 条坐标，但只要清单里出现非 `docs/` 文件就得重跑取证件。

**本批未做**（不得当已验证）：零产品代码与 `web/` 文件；未跑 `pnpm install`；A1–A10 一条读数未取；PR-3 仍受 `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md`（状态仍为 **Proposed（待拍板）**，§7 六项未答）阻塞——**PR-0/1/2/4 不受该阻塞影响，可先走**。
