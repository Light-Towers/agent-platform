# 错误契约的分阶段切分：把「增量能力」与「存量改写」从一枚默认值上拆开

## 0. 本件状态（先划诚实边界）

- 状态：**G1 approved / G2 proposed**。2026-11-06 用户批示「从全局治本的视角分析、解决」⇒ 按 §4 六条动手（可逆方向），G2 那批仍待逐条拍板。批准范围 = §4，不越界到 §5。
- 触发源：登录面后端（HELD-5）被闭包判为「依赖未入库符号 AppError」，导致按 HEAD 部署的现网呈现「登录框在、账密登录必 404」。
- 本件**不替代** `docs/plans/plan-error-contract-alignment-2026-11-04.md`（那份是 D-2/D-4 的审计与七项待拍）；本件做两件事：把那七项按「是否改变存量对外形状」重切成两批（§1/§4/§5），并补一条跨载体不变量（§3.3 + §4 第 6 条）—— 后者才是「登录框在、后端没有」这一型能不再复发的根因处置。
- 全部读数的取证件（九组，当轮现取）：.tmp-scratch/ap-visual/k67-rootcause-readings-20261106-105024.txt，基线 HEAD=2d5bb0ff、已部署 rev=d4d3d329（ahead=8）。件只在本机、不入库，故书写不加反引号。

## 1. 问题陈述：卡住登录面的不是缺一个类，是两件事被焊在一起

那簇未入库改动共 12 文件 +639/−70。逐 hunk 读下来，它同时做了两件**性质完全不同**的事：

- **G1 增量能力**：kernel 里新增 `AppError` 异常类、它的 handler 注册、`error_body` / `make_error_response` 的可选 `details` 参、shared schema 新增 `ErrorEnvelope`。这些**没有任何存量调用点**（HEAD 里零处 `AppError`），装上也不改变任何一个现存请求的响应体。
- **G2 存量改写**：六个服务现有 4xx/422/503 的**对外体形状**从 FastAPI 原生 `{detail}` 换成 `{code, msg, request_id}`。这会改变下游消费者读到的字节。

焊接点**只有一枚布尔默认值**，实物行号（同一件 R2 段）：

- errors.py 工作区版 L318 `app.add_exception_handler(AppError, app_error_handler)` 与 L320 `if normalize_http_errors:` —— **注册在开关之外**。
- 同一件 L283 `normalize_http_errors: bool = True,`（kernel）与 app_factory.py L29 同值（工厂透传，L61 传参）。工厂是所有生产 app 的唯一装配点，默认 True ⇒ 经工厂的 app 一次性进入最终态。

⇒ 结论（这条决定了这一趟怎么动）：**把默认值改为 False，G1 就能独立入库、登录面立刻可用，而 G2 的影响面一格都没碰到。** 那簇自己的 docstring 已经写明了这个用法（FACTORY-L44「`normalize_http_errors=False` 仅保留历史 `Exception → 500` 兜底，供尚未迁移的调用方显式降级」），实现里两条路都通，只是默认值选了难逆的那一条。

## 2. 与在册决定的关系（不能把已拍过的当没拍）

- `docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` L47 记的是一条**审计倾向（非拍板）**：理由是「6 个 app 全部无在仓前端 ⇒ 现在不收敛，将来有前端时再改就是真打破」。**这条事实今天已经变了**：`web/` 自 PR-0 起是在仓前端且已在现网托管。所以那句话说的是「趁没有消费者先收敛」，而今天面对的是「消费者已存在且就是自己的前端 + 未知的外部 API 调用方」。本件不拿它当批准，也不拿它当否决。
- 真正在册的**已拍项**是 D-2=A：HEAD 的 kernel 自陈「仅注册 `Exception → 500` 兜底，4xx 不改」，并且有一条用例把它钉着。而那簇**把这条用例删了**（同一件 R3 段，逐字）：

  -def test_http_exception_4xx_detail_unchanged():
  -    """D-2=A：仅兜底 Exception→500，4xx HTTPException 仍走 FastAPI 默认 {detail} 信封。"""
  -    assert resp.json() == {"detail": "bad input"}

  删一条契约用例是合法动作，但**前提是那条契约被正式废止**。翻一条已拍板的架构决定属 D2/D3，不能靠「实现已经写好了」把它变成既成事实。本件的处置：**恢复它，并让它继续钉默认值**（见 §4 第 3 条），而不是留着删。

## 3. 那簇实现里的两处设计缺陷（与拍板无关，是独立要修的）

### 3.1 八处 503 的运维文案会被脱敏抹掉

同一件 R4/R5 段：auth_router 里 `AppError-token-lines=14  AppError-503=8  AppError-4xx=6  details-passed=0`，而 handler 体 L302 是无条件的 `msg = sanitize_5xx_msg if exc.status_code >= 500 else exc.msg`。

⇒ 「登录未启用：签名密钥未在位」「签发参数与验签参数不一致」「用户目录不可用」这八条**服务端自己声明的常量文案**会被换成同一句通用 5xx。P8 那条不变量的射程是「未捕获异常的消息/堆栈不得外泄」，`exc.msg` 是代码里写死的常量、不是 `str(e)`，把它一起抹掉属于**射程过宽**：它抹掉的恰好是唯一能把「部署被改坏」和「用户输错」分开的线索。修法：脱敏只作用于未捕获异常通路；`AppError` 的 5xx 保留服务端自声明文案（要真含内部信息，就不该把它写进 msg —— 这条边界写进 docstring 与用例）。

### 3.2 新出口会让一条门禁齿静默失去依据

同一件 R6 段：`lint-arch-marker-contains-AppError = False` —— `scripts/lint_architecture.py` 的 `_HTTP_EXIT_MARKER`（L484）不含 `AppError(`。两条后果：

1. 文件粒度前置靠这组标记判「是不是 HTTP/SSE 出口模块」。今天改用的两个文件还没漏（query_router 的 marker 命中 20→16、federation server 19→19，都 >0），**但那是被装饰器撑住的，不是设计保证**：一个只写 `AppError` 而不带其他标记的新文件会整片退出 P8 判定面。
2. 行级放行 `_STATUS_4XX`（L494/L512）匹配的是 `status_code = 4xx` 关键字写法。query_router 里 `status_code=4xx` 字样 **HEAD=3 → WORKTREE=0** ⇒ 那三行不再被放行（方向上变严，可接受），但 L481 那条注释「D-2=A：不动各 app 现有 4xx {detail} 信封」的依据已经与代码分叉。

⇒ 门禁的第三层（强制齿）必须跟着新出口换射程，**而不是放宽**。修法见 §4 第 4 条。

### 3.3 第三处缺陷与本件主题无关，但它是「登录面为什么能上线到一半」的真根因

现网之所以是「登录框在、账密登录必 404」，不是因为分区判错了，是因为**没有任何一把齿跨得过载体边界**：

- 在册的闭包齿（归属三集合 + 候选树基准）只理解 **Python import**。`web/src/api/auth.ts` 里那四个 `'/auth/*'` 字面量是一条 **HTTP 调用边**，在 AST 里与「一个字符串常量」不可区分 ⇒ 前端入 own、后端入 held，两半各自闭包自洽，齿一格都不报。
- `web/scripts/check-events.mjs` 与 `verify-sse.mjs` 已经把「后端 Literal → 前端 handler → 消费面」这条链的四向对齐做成了门禁，射程覆盖**事件名**，但没覆盖**端点存在性** —— 缺的就是这一格。
- 更根本的一条：那两件的基准是**本机文件系统**。就算它们查端点，11-06 当时的盘上 auth_router.py 一直在，照样绿。这与 `scripts/check_doc_sync.py` 在册那条「存在性判定基准 = 版本控制清单，不是本机文件系统」（10-04 实踩）是**同一型缺陷的第三次显形**。

⇒ 所以治本不是「把 auth_router 补进下一次提交」，而是让「消费方引用了提供方没有的东西」这件事在**待提交的那棵树**上就判红。落点见 §4 第 6 条；它同时把这条不变量从文档规矩升格为机器齿（《架构决策原则》三层齐备的第三层）。

### 3.4 四条同型根因：输入与基准脱钩

这四条载体不同、形状同一，只修其中一条，其余三条会在下一轮换个名字再来。`scripts/evidence/face_basis.py` 与本节的对应关系也在这里定死。

1. **面基准四套**：门件用 `git diff HEAD`、两把 derive 用 `git status --porcelain`、归因件用 unstaged-only 再补一轮未跟踪、文档同步用 `git ls-files`。四套读出的面互不相等，而**守恒等式在两边同时错时依然成立** ⇒ 齿一格都不报。治本 = 面只准从 `scripts/evidence/face_basis.py` 取，经 `scripts/evidence/k71-basis.ps1` 一层解析；量具体内禁止再拼基准，由 B6 齿看住。
2. **判决当输入**：上一轮的「谁家的活」是**判决**不是事实；抄成纯路径清单后，文件被本轮批准范围改动，下游照旧减掉 ⇒ 已批准的活被静默排除，而齿问的是「路径还在不在面上」，答不了「这一行判决还成立不成立」。治本 = 归属表每行带内容指纹（blob OID），减 ext 之前先验新鲜度（derived / ext-fresh 两模式）。
3. **量具不入库**：判据本体住在本机 gitignored 目录，账面写「任何一次合入后必须重跑」，而新克隆上脚本不存在 ⇒ 判据只在某台机器的工作副本成立。治本 = 稳定量具进 `scripts/evidence/`，在 `scripts/evidence/README.md` 与 `ARCHITECTURE.md` 登记调用边，受 `scripts/check_doc_sync.py` 的版本控制清单校验保护。
4. **键绑件名不绑内容**：账面写 `KEY=VALUE` 并引一个件名，而那个件里从没打印过这个键（或印的是 `KEY: value` 冒号形）⇒ 数看起来有出处，实际无处可查。治本 = 键按**件的打印形状**书写、改绑到真正打印该键的件；不放宽量具、不硬造键名、不新开登记口子。与 §3.3 那条「本机文件系统当基准」同族：都是把输入与实物解耦，只是这次解耦的是内容而不是路径。

## 4. G1 的落地设计（六条，每条带判据与反证）

| # | 改动 | 判据（怎么算对） | 反证（种个错必须红） |
|---|---|---|---|
| 1 | kernel `install_error_handlers` 与 `build_api_app` 的 `normalize_http_errors` 默认 **True → False**；docstring 的「工厂强制不变量」措辞回到「统一 500 脱敏 + AppError 通路」，并写明最终态需逐 app 显式开启 | 用 HEAD 已有的 `make_error_response` 逐字比对：`{code, msg, request_id}` 三键，与那簇 `details` 分支在 `details=None` 时同形（同一件 R1 末行 + R6）；默认路径下 4xx 体 = `{"detail": ...}` | 把默认改回 True ⇒ 恢复的那条默认值用例必须红（证明它真的在钉默认值，不是装饰） |
| 2 | `AppError` 类 + `app_error_handler` + L318 那行注册**原样入库**（注册保持在开关之外）；`error_body` / `make_error_response` 的 `details` 可选参入库 | 闭包判决：门件重算分区后 HELD-5 应转为 OWN（判据由树给，不由我给）；auth_router 那 14 处 `raise AppError` **一行都不改** | 把 L318 那行注册删掉 ⇒ 登录面 12 处读 `["code"]` 的断言必须红（证明全局装配是这条路的一部分，不是可选装饰） |
| 3 | 恢复 `test_http_exception_4xx_detail_unchanged`，把它升格为**默认值不变量用例**；那簇 5 处靠默认 True 断言信封的新用例（L214 / L236 / L254 / L278 / L309）改为**显式传 `normalize_http_errors=True`** | 用例名与断言原文回到 HEAD 的形状；显式传参的那 5 条断言一字不动 | 「显式传参」不等于「放宽」：反证 = 把这 5 条的显式 True 撤掉，它们必须红（说明它们测的确实是最终态通路，不是在默认态蒙对） |
| 4 | `lint_architecture.py`：`_HTTP_EXIT_MARKER` 补 `AppError\(`；L481 那条放行注释的依据改为「默认 False，G2 未开」；`_STATUS_4XX` 放行保持不放宽 | 全仓 rc=0；且新增一个「只含 AppError 的出口文件」样例能被扫到 | 在样例文件里种一行 `f"{e}"` 形式的 AppError 文案 ⇒ 齿必须咬（证明换射程不是把判定面缩小） |
| 5 | §3.1 的 5xx 文案射程修正（handler 内一条判断 + 一条用例） | 八处 503 出口里任取一处，客户端读到的是服务端声明的那句，而不是通用句；`request_id` 与 `X-Trace-Id` 仍成对 | 把判断写成 `>= 400` ⇒ 用例红；写成「5xx 也抹」的原样 ⇒ 同一格红（两向都判） |
| 6 | `web/scripts/check-events.mjs` 新增端点成对性格（§3.3）：消费集从**索引树里的** `web/src/**` 派生，提供集从**索引树里的** agent_server 装配链（main.py → routes.py → 各 `*_router.py` 的装饰器 + 可选 prefix）派生，判据 = 消费集 ⊆ 提供集 | 基准是索引树（`git show :path`）不是盘：取不到 git ⇒ fail-closed 报红，不退回 `readFileSync`、无旁路开关；两向自测（种一个不存在的端点字面量必红 / 端点在索引里补齐必绿） | 把 auth_router.py 从索引里 `git rm --cached` ⇒ 这一格必须红（这条不需要种：11-06 的 HEAD 就是它的真载体，红是实测不是推定） |

**G1 明确不做**：不改 `web/src/api/errors.ts`（那 26 行含 `STREAM_TEXT_KEYS` 顺序变更，属 G2 的前端侧，本批不碰）、不改 `identity_middleware.py` / `query_router.py` / `agent_federation/api/server.py` / shared schema 的存量改写部分、不开任何 app 的 `normalize_http_errors=True`。

## 5. G2 的待拍清单（真 D2，另批）

沿用 11-04 方案件 §9 那七项，本件只补两条进去：

1. D-2 总方向（推荐双写过渡）· D-4 流式帧统一 · D-2.1 校验状态码 · D-2.2 校验结构（`details` 不含 `input`）· D-2.3 兼容窗口退出条件 · D-3 边界（KS 是否继续 `install_handlers=False`）· shared schema 新增 vs 原地改。
2. **新增**：逐 app 开启顺序与每格的读数判据（谁先翻 True、翻完读什么、怎么回滚）。
3. **新增**：`STREAM_TEXT_KEYS` 从 `['error','msg','message']` 改为 `['msg','error','message']` 的影响面 —— 一帧同时带 `error` 与 `msg` 时上屏文字会变，这条今天**没有实测**，不得按「只是顺序」读。

## 6. 已知债登记（带复审触发条件，本批不动）

- **重复实现**：`git grep -n "def error_body" HEAD` 出两处 kernel 之外的副本 —— knowledge-service 自带一份 `applications/knowledge-service/knowledge_service/utils/error_response_utils.py:35`。这是「单一实现」层的既有缺口，早于本簇存在，也是 G2 收敛清单里必须一并收掉的一格。**复审触发条件**：任一 app 开启 `normalize_http_errors=True` 时，该副本必须先收敛到 kernel，否则那次开启的 diff 里出现第二份信封构造代码即应判红。
- **形态债**：G1 落地后 `http_exception_handler` / `_normalize_detail` / `stream_error_frame` 在默认路径下**存在但未安装**。按在册「未完成功能用 flag 隐藏」这是有意状态，不是死代码；**复审触发条件**：G2 任一 app 翻 True 那一批，本条登记作废并换成逐 app 的实装读数。

## 7. 验收标准（G1）

1. 门件重算分区：HELD 里那 5 件消失（由树判，不由我判），`GATE_RC=GREEN`。
2. 存量对外形状零变化：恢复的默认值用例绿；`make test` 里 kernel / agent-server / shared-schemas 三 session 与本轮基线差集为空。
3. 现网探针（部署后）：`/auth/login` 与 `/auth/register` 可达、账密真跑一次、失败帧与错误体逐格绑件；`/ui/` 仍 200 + no-store + sha 对齐。
4. 三层齐备复述：单一实现 = kernel 一处；全局装配 = `build_api_app` 内注册；强制门禁 = lint 齿随动 + 门件闭包 + 端点成对性格（第 6 条，基准 = 索引树）。缺一层即本件未达成。
5. 成对性齿的**真载体自证**：把本批六件后端文件从索引里取出（`git rm --cached`，不删盘上文件）后该格必红，再 `git add` 回去必绿 —— 拿历史 bug 本体做反证，不拿种出来的假 bug 冒充。

## 8. 本件未做 / 不得读成已批

- 未改一行产品代码（本件纯方案）。
- 未批准 = G2 全部；G1 待用户点头，批准范围仅 §4 六条（与 §4 表内六行、§7 第 5 条「本批六件后端文件」及 §4 标题一致；本行原写「五条」是初版遗留，2026-11-06 就地订正）。
- 本机跑不了全量验证这件事本件没有改变（在册：三处卡点同形状 = 测试构造真实 LLM/DB/OTLP 客户端而本机无链路），G1 的第 2/3 条验收**必须在现网取**，不得以本机部分绿灯冒充。
- 「登录面已上线」在 §7 第 3 条读数取到之前不得声明。
