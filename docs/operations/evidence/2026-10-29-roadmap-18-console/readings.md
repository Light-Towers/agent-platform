# roadmap #18 取证读数：只读控制台跑通四步链路（2026-10-29）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档。
**判据对象：** `docs/plans/plan-production-delivery-roadmap-2026-10-09.md:94` 条目 #18，判据原文
= **「一条完整业务链路真跑通，留截图与日志；不新增后端专用接口」**，改法四步 = **提问 → 执行 → 展示过程与结果 → 错误提示**。
**取证页面对象：** `applications/agent_server/static/console.html`（**本批零改动**，见 §1 字段 3）。

---

## 0. 结论与档位（先看这里）

按 `evidence-format.md` §3，本项落 **第二档「标准环境已验证」，且带降级限定**：

- **已证**：判据四步在本地部署上全部真实发生，界面逐可见，留 5 张截图 + SSE 逐帧原文；取证全程**未改一行产品代码**、**未新增任何接口**。
- **未证**：判据里的**"真"跑通**没达成——`llm=False`（本机无 `.env`，无模型密钥）⇒ 答案文本是平台自述的降级句 `（无 LLM 模式）…`，且 `embedding_real=False`、知识库未启用 ⇒ 检索是退化读数而非真命中。
- ⇒ **#18 不翻为已完成**。剩余半 = **待放行（模型密钥）**，本文件不承诺日期。

另有一条**判据层面的更正**（重要度不低于上面的读数）：#18 四步**不含"会话回退"**。曾按选型文档的旧表述去给该页补 `/session/revert` 交互，被该页在册测试拦停（1.2 基线 6「运维动作不进浏览器」），改动已全量回退。因果链与教训存 `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` §11.5。

---

## 1. 五个必填字段

**① 代码版本**：rev `896f966e`。工作区在本批之前的既有未提交改动**不含任何产品代码**——
`git diff --stat -- applications packages` 输出为空（本批取证结束时实取），故所有读数绑定这棵树的
`applications/agent_server/` 内容，与 rev `896f966e` 逐字一致。

**② 执行命令**（原样可复制；Windows PowerShell 实跑形式）：

```powershell
# 起服务（端口 8123，本机）
$env:DATABASE_URL=""; $env:API_KEY=""; uv run uvicorn agent_server.main:app --port 8123 --host 127.0.0.1

# 探针 A：/health 读数 + /query 两问的 SSE 逐帧 + /history + /console.html
uv run python docs/operations/evidence/2026-10-29-roadmap-18-console/probe_a_health_query.py

# 探针 B：错误通道 + /session/revert 失败分支读数
uv run python docs/operations/evidence/2026-10-29-roadmap-18-console/probe_b_error_revert.py

# 只读约束未破的反证（12 条在册用例）
$env:DATABASE_URL=""; uv run pytest applications/agent_server/tests/test_console_router.py -q
```

bash/Linux 等价：`DATABASE_URL= API_KEY= uv run uvicorn agent_server.main:app --port 8123 --host 127.0.0.1`。

**③ 读数 + 分母**：

| 目标 | 命令 | 读数 | 结论 |
|---|---|---|---|
| 服务就绪态 | 启动日志行 | `storage=memory llm=False pool=False coordination=True admission=False revert=True otel=False mcp=False planner=deterministic runtime_mode=local` | 降级面在启动时已自报，非事后推断 |
| `/health` | 探针 A | `status=healthy`；`llm=False`、`storage=memory`、`revert=True`、`auth_enabled=False`、`identity_mode=insecure`、`guard_enabled=False`、`embedding_real=False`、`coordination=True`、`admission=False`（9 个字段逐一取，未合并） | 页面状态灯与接口逐字段一致 |
| `/query` 第一问 | 探针 A | HTTP 200，`text/event-stream`，**10 帧**：`route`→`evidence`→`status`→`answer`→`done`（各帧 event + data 双行） | 四步的前三步成立 |
| `/query` rag 特征问 | 探针 A | HTTP 200，**16 帧**：`route(capability=rag)`→`evidence`→`replan(iteration=1)`→`evidence`→`replan(iteration=2)`→`evidence`→`status(steps 3 项)`→`answer`→`done` | **多步过程可视化真实发生**（2 次推翻前判 + 3 次依据帧，非演示桩） |
| `/history` | 探针 A | HTTP 200，`thread_id=console`，`count=2`，items 为 user/assistant 原文 | 会话回溯可读 |
| `/console.html` | 探针 A | HTTP 200，`cache-control: no-store`，16878 bytes | 页壳可达且不可缓存 |
| 只读约束反证 | `pytest test_console_router.py` | **12 passed**（全量口径：该文件 12 条用例，无 skip、无 deselect；rev 归 §1 字段 ① = `896f966e`，与本文所有读数同一棵树） | 取证未破坏基线 6 |
| **零代码改动** | `git diff --stat -- applications packages` | **空输出** | 判据"不新增后端专用接口"以 diff 为空为凭 |

**④ 未跑与待环境**（不写"已验证"）：

| 没跑的部分 | 原因 | 档位 |
|---|---|---|
| 带真实模型的回答（`llm=True`） | 本机无 `.env`，`Test-Path .env` = False，无模型密钥 | **待放行** |
| 真检索命中（`embedding_real=True` + 知识库有语料） | `DATABASE_URL` 未配 ⇒ 知识库自述"未启用"，Embedding 落 Mock | **待环境** |
| 4xx/401 鉴权错误通道（`auth_enabled=True` 下的 401 分支） | 本部署 `API_KEY=""` ⇒ 鉴权关，401 无从触发 | **待环境** |
| 会话回退的**成功**分支 | 内存 checkpointer 下无已知 `checkpoint_id` 可填（见 §3 第三条） | **待方案** |
| 多租户隔离下的界面表现 | 本机 `identity_mode=insecure` | **待环境** |

**⑤ 所需依赖**：`uv sync --all-packages --extra dev` 的 workspace venv；`httpx`（探针用，dev extra 内）；
**不需要** PG / Milvus / Valkey / OTel SDK / Docker——上述任一缺失只降级读数，不影响本批取证可复现。
端口 8123 需空闲；浏览器截图需内网可达 `127.0.0.1:8123`。

---

## 2. 判据四步逐条对照

| 判据环节 | 第一手证据（接口原文） | 屏上可见（截图） | 达成 |
|---|---|---|---|
| 提问 | `POST /query` 200 + 10 帧 | `console_step2_qa.png` | ✅ |
| 执行 | `route(capability=rag, reason="命中知识库特征词")` + `replan×2` + `status.steps 3 项` | `console_step2_qa.png`（时间线多行、按类型分色） | ✅ |
| 展示过程与结果 | `evidence(preview="知识库未启用（DATABASE_URL 未配置）")` + `answer` + `done` | `console_step2_qa.png`（答案区 + 依据 chips）；`console_step3_history.png`（回溯 6 条） | ✅ 形状达成 / ⚠ 内容是降级自述 |
| 错误提示 | 探针 B 第 4 项：`{"detail":[{"type":"missing","loc":["body","checkpoint_id"],…}]}` | `console_step4_key_error.png`（前端本地拦截）；`console_step5_422.png`（后端 422 原文上屏） | ✅ 两条通道，但见 §3 第一条与 §4 |

---

## 3. 三条实测副产品（这是本批真正的增量，均已写进实施件）

**一、4xx 的 `detail` 有两种形状共存，`describeError` 只按字符串写会漏。**
业务类 4xx（如 `HTTPException(404, detail="CHECKPOINT_NOT_FOUND")`）给**字符串**；
FastAPI 校验类 **422 给数组** `detail: [{type, loc, msg, input, ctx}]`。
第一手：`/session/revert` 缺 `checkpoint_id` ⇒ `HTTP 422 | {"detail":[{"type":"missing","loc":["body","checkpoint_id"],"msg":"Field required","input":{"session_id":"console"}}]}`。
现状页面靠 `typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)` 兜住（不崩，但把 2100 字符的 `input` 原文整段铺屏，可读性差——截图 5 可见时间线被撑高）。⇒ `web/` 的 `describeError` 必须显式分形处理，且**不得把 `input` 回显上屏**。

**二、`done` 帧在只读控制台上是"未处理事件"，但 §3 第 4 条的风险定位被证实为真。**
屏上出现 `未处理的事件类型：done`（`console_step2_qa.png`），因为该页 switch 无 `done` 分支、落 default。
⇒ 两点：① 只读页**侥幸**没踩"error 后紧跟的 `done.answer:""` 覆盖已渲染内容"这个坑（它压根不信 `done`）；② `web/` 一旦按判据把 `done` 当权威信号处理，就必须实现抑制规则（实施件 §3 第 4 条）。风险是**实现引入的**，不是现网已有的。

**三、`checkpoint_id` 前端取不到 ⇒ revert 交互做不出可用形态（PR-3 开工前置）。**
第一手：`/session/revert` 带不存在的 uuid ⇒ `HTTP 404 | {"detail":"CHECKPOINT_NOT_FOUND"}`（**失败分支形状已确认**）；
而 `RevertRequest.checkpoint_id` 必填（`schemas.py:188`），`/history` 的 `HistoryItem` 无此字段（只有 `index/role/content/id/created_at`），SSE 全部出口帧也不携带（`done` 只有 `type/thread_id/answer`）。
另记一条易误读的读数：`GET /history?session_id=`（**空值**）返回 **200** 而非 422，`thread_id` 归一为 `dev-default-thread`、`count=0` ⇒ 空会话号被静默归桶，前端**不得把这条 200 读成"该用户没有历史"**。

---

## 4. 截图清单与转述声明（`evidence-format.md` §2-3）

5 张截图**不在本目录**（处置口径见 §4.1：已按用户批示移出仓内跟踪面，本机留存于 `.tmp-scratch/evidence-untracked/2026-10-29-roadmap-18-console/`），**由浏览器子代理操作页面并拍摄**，属**转述**而非本仓复跑：
`console_step1_status.png`（状态灯 12 行）、`console_step2_qa.png`（时间线 + 答案 + 依据 chips）、
`console_step3_history.png`（历史 6 条）、`console_step4_key_error.png`（密钥非 ASCII 拦截）、
`console_step5_422.png`（后端 422 上屏）。

界面文字读数与上表接口读数**交叉一致**（时间线各行文本 = SSE 帧的 `capability/reason/count/preview` 字段值），
故采纳截图作为"屏上可见"的证据；但两处不采信任其叙述、以第一手为准：

- 子代理叙述"三次 `推翻前判`"与其自身摘录（2 行）矛盾 ⇒ 采探针 A 的 `replan iteration=1、2` 两帧。
- 子代理称 `console_step4` 那行错误"文字是深灰不是红色" ⇒ 与代码一致（`.ev.error` 只染左边框 `3px solid #b00020`），
  这条**不是缺陷**，但说明"错误提示"在屏上靠边框区分、色弱场景可辨识度低，留给 `web/` 的判断，本批不改只读页。

### 4.1 截图的处置：已裁定没有原件入库（用户 2026-10-29 批示）

用户原话：「**截图与日志 忽略，不提交**」⇒ 本批 5 张 PNG **不进版本控制**；另因用户追问“为什么变更记录里还有”，本轮把它们**移出仓内跟踪面**（不再是“靠 add 纪律”）：

- 现位置：`.tmp-scratch/evidence-untracked/2026-10-29-roadmap-18-console/`（5 张合计 678,906 bytes，逐字节未改，仅移动）。
- **磁盘上其实有两份同内容副本**（本轮 `Get-FileHash` 实取，5/5 张 MD5 全等）：另一份在根 `.evidence-out/`，那是浏览器子代理的**原始落盘目录**（`docs/` 里那 5 张是当时复制进去的）。此前本文说“5 张”只数了 `docs/` 那一份，口径在此修正为：**本机 10 个文件、两个位置，两处都已被 git 忽略**（`.evidence-out/console_step1_status.png` 同样回显命中 `.gitignore:61:.*/`，且 `git ls-files .evidence-out` = 0 行）。是否删掉重复份属另一回事，本轮**未删**（删了就没有原件可回看）。
- 为何那儿不算“入库”：`.gitignore:61` 的 `.*/` 规整忽略顶层点目录，`git check-ignore -v` 对移动后的 PNG 回显命中该行 ⇒ 它们从变更记录里消失，且**任何人 `git add .` 也带不进去**（构造保证，不靠自觉）。
- **未改 `.gitignore`**（那是需人批的仓级策略变更）⇒ 改用“挪位置”达成同一效果，可逆（`Move-Item` 反向即可）。
- 本目录现只剩 **3 件**（`readings.md` + 两支探针）⇒ 整目录 `git add` 与逐文件 `git add` 结果相同，不再有“顺手把 PNG 拖进去”的风险。

上表「屏上可见」列保留文件名，但它的含义从「仓内原件」降为「**转述，原件不在仓内**」（属 `evidence-format.md` §2-3 的转述禁令口径）。

这一条与实施件 §11.4 要防的「已入库文档指向仓内不存在路径」**不同型**，因为本文自身也未入库，两者同批提交。原先登记的“不得对整目录 add”风险已由“挪位置”构造消除（目录内已无 PNG），不必再靠下一条纪律。

**对 #18 判据满足度的真实代价（不粉饰）**：判据原文就要「留截图」，而仓内无图像原件 ⇒ 即便模型密钥放行、链路真跑通，本项也只能以「**可复跑探针 + SSE 逐帧原文（=日志，已在正文）+ 转述**」的形态满足。若验收口径要求「仓内查得到图像原件」，那就得改判据文本或改本处置，**不能拿本文当已满足**。

为何不靠门禁兜（本轮实取，记下免得后人重新推）：`scripts/lint_public_mirror.py` registry 模式用 `git grep -I`（docstring 明写「-I 跳二进制」）、publish 模式用文本 `git diff`（二进制只出 "Binary files differ"）⇒ **两种模式都扫不到 PNG 里的字**，门禁 rc=0 与图片内容无关。⇒ 不入库反而消除了这个盲区（镜像树上根本不会有这 5 张）。

**两条路里选了哪条（登记口径）**：要“不入库且不在变更记录里”，可选① 改 `.gitignore`（如加 `docs/operations/evidence/**/*.png`）或② 把文件移出跟踪面。① 是**仓级策略变更**（会连带禁止今后任何取证图片入库）⇒ 属 D1、需人批，本轮**未采**；② 零策略影响、可逆 ⇒ **已采**。若今后确实要“取证图片一律不入库”，再单开①。

（本轮实取的体积与先例，留作当时判据的背景：5 张合计 678,906 bytes；仓内跟踪的图片类文件只有 1 个 `applications/agent_federation/frontend-backend-flow.png`，455,576 bytes。）

**“移出之后 git 侧到底还剩什么”——三个面逐一取（2026-10-29 复跑，rev `896f966e`）**：

| 面 | 命令 | 读数 |
|---|---|---|
| 工作区变更 | `git status --short` 全量后按图片扩展名过滤 | **空**（0 行） |
| 暂存区 | `git diff --cached --name-status` | 仅 2 个 `.md`（10-13 批次遗留），图片 **0** |
| 已跟踪清单 | `git ls-files '*.png'` | **1**（就是 `agent_federation` 那张旧图，未动） |

⇒ git 侧已彻底无图片。若界面仍列着它们，判据是看条目的**路径前缀**：显示 `docs/operations/evidence/…\*.png` = 视图**旧快照**（该目录现只剩 3 件，刷新即消失）；显示 `.evidence-out/…` 或 `.tmp-scratch/evidence-untracked/…` = 那是**会话文件操作列表**在记“本次会话里创建过这些文件”，它按 AI 动作记账、不看 `.gitignore`，因此**不等于待提交内容**，`git add`（含 `git add .`）拿不到它们。这条区分本身是转述（我看不到你的界面），可核的是上表三行。

---

## 5. 本批明确未做的动作

- **未翻任何复选框**（`docs/TODO.md` §1 与 roadmap #18 的状态列均保持原样），理由见 §0 档位。
- **未改产品代码**：`console.html` 的 revert 尝试已 `git checkout` 全量回退，`git diff` 对 `applications/`、`packages/` 为空。
- **未提交**：提交须用户显式批示。本批同批必 add 的路径清单（含工作区里**不属于本批**的 10-28 nl2sql 发布批次改动，不得混入），及 `check_doc_sync.py` 扫不到 `docs/adr ↔ docs/plans` 互引这一门禁盲区，均存实施件 §11.4。
- **5 张截图不入库，且已移出仓内跟踪面**（用户 2026-10-29 批示 + 追问“为何变更记录里还有”⇒ 现存 `.tmp-scratch/evidence-untracked/2026-10-29-roadmap-18-console/`，口径与代价见 §4.1）。本批 add 面 = 3 件：`readings.md` + `probe_a_health_query.py` + `probe_b_error_revert.py`。**日志无需单独提交**：SSE 逐帧、HTTP 状态码与 422 原文已作为文本写在本文正文（§1/§2/§3），本目录内无其他二进制或 `.log`/`.txt` 产物（本轮 `Get-ChildItem` 实取）。
