# Batch 6 方案：kernel sanitizer 的 CodeQL 模型缺失（合入后默认分支重扫暴露 7 条新告警）

> 状态：**已执行并已验收**（PR #36 合入 `main` = `0bc5175`，主干重扫实测：open 9 → **6**，详见 §9 验收结果）。
> **执行时推翻的关键前提**：本文 §4 原推荐「切 advanced setup」是基于**错误认知**——default setup 只接受已发布模型包这一限制只对**组织级**扩展成立，**仓级 local 包放 `.github/codeql/extensions/` 即被自动检测加载**（两模式均识别）。实际落地为零基础设施变更，详见 §4 纠正块与 §9。
> 触发：PR #33（CodeQL Batch 1~5）与 PR #34（doc-sync 门禁）于 2026-10-01 08:25Z / 08:32Z 合入 `main` 后，默认分支自动重扫的结果核对。
> 上游方案：`docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md`（本文件同时纠正其中一处已被证伪的判断）。

## 1. 实测事实（全部可复跑，命令见 §7）

合入前 `refs/heads/main` open **21** 条 → 合入后 open **9** 条。原 21 条中 **19 条闭合**（`state=fixed`、无 dismiss），仍 open 仅 2 条。

| 类别 | 合入前 | 结果 | 证据 |
|---|---|---|---|
| A `py/path-injection` ×8 | `agent_federation/api/server.py` | **7 条闭合**，`#23` 残留 | 残留位置是 `:264` `FileResponse(abs_path, ...)`（sink 在调用点，不在 kernel 内） |
| B `py/weak-sensitive-data-hashing` ×5 | 4 站点 + kernel | **4 条闭合**（`#31`/`#32`/`#33`/`#35`） | `#34`（`gateway/gray.py:40` `md5(user_id)` 灰度分桶）按方案定性为真误报，**待人工 dismiss** |
| C `py/stack-trace-exposure` ×4 | exhibition ×3 + agent_server ×1 | **全部闭合** | `#27`~`#30` 均 `fixed` |
| D `actions/missing-workflow-permissions` ×3 | 三个 workflow | **全部闭合** | `#1`/`#17`/`#37` 均 `fixed` |
| E `py/incomplete-url-substring-sanitization` ×1 | runtime 测试 | **闭合** | `#36` `fixed` |

**新增 7 条**（这是本方案的真正议题）：

| 新告警 | 严重度 | 位置 | 规则 | 性质 |
|---|---|---|---|---|
| `#38` | warning | `packages/agent-core/agent_core/guardrails/auth.py:92` | `py/weak-sensitive-data-hashing` | 原 PR 作用域告警迁入 main（预测命中，非新问题）；定性见上游方案：误报 |
| `#39` | warning | 同上 `:117` | 同上 | 同上；定性：形状属实、不可消除，已由 P6-2 锁死调用面 |
| `#40` | error | `guardrails/fs.py:119` `Path(base).resolve()` | `py/path-injection` | **新问题**：kernel helper 自身被识别为 sink |
| `#41` | error | `fs.py:134` `_ensure_within(root, current.resolve())` | 同上 | 同上 |
| `#42` | error | `fs.py:162` `candidate.resolve()` | 同上 | 同上 |
| `#43` | error | `fs.py:93` `logger.warning(... input=%r ...)` | `py/clear-text-logging-sensitive-data` | **新规则类**：拒绝路径时把入参原文写进日志 |
| `#44` | error | `fs.py:103` `logger.warning(... resolved=%r ...)` | 同上 | 同上 |

`#40`~`#42` + `#23` 是**同一根因**：CodeQL 的内建模型不认识 `safe_join` / `resolve_within` / `safe_filename` 是 sanitizer，于是（一）调用点的污点照样流到 `FileResponse`（`#23`），（二）污点一路追进 kernel，把 helper 内部的 `resolve()` 当成 sink 报出（`#40`~`#42`）。`#43`/`#44` 是独立问题：日志出站点，与路径模型无关。

## 2. 必须记下的一次推理纠错

上游方案 L167 写过：「PR 重扫**没有**报出任何新的 `py/path-injection`……**无需为此补 data-extension**」。**该判断不成立**，已被 §1 的主干重扫证伪。

误因：把「PR 模式的重扫结果」当成全量反证。`?ref=refs/pull/33/head` 与 `?ref=refs/heads/main` 返回的是**两套不同的告警集合**——前者只覆盖本次分析在该 ref 上产出的检出，默认分支模式则会做跨过程全量追踪并把污点追进新增的 kernel 文件。正确的推论应是「PR 模式未报 ≠ 主干模式不会报」，而我据此把「补 data-extension」这一候选直接排除了。教训：**证据的作用域不能超出产生它的分析模式**；凡涉及「已经排除了某风险」的结论，必须在最终作用域（默认分支）复验后才可入库。

## 3. 目标与非目标

**目标**
- 让静态分析与本仓已建立的「单一实现 + 强制门禁」不再互相打架：kernel helper 被 CodeQL 认作 sanitizer，`#23`/`#40`/`#41`/`#42` 由**根因消除**而非靠注释豁免。
- `#43`/`#44` 做出明确处置（改码或 dismiss），并写下理由。

**非目标**
- 不放宽 `lint_architecture.py` P6/P6-2/P7/P8 的任何判定面来换告警归零（红线：不为凑绿改契约）。
- 不动对外契约（`/api/download` 的 `path` 入参仍接受绝对路径回传，只要求落在 base 内）。
- 不改变量名/函数名去「躲检测器」。

## 4. 选型

| 选项 | 做法 | 评价 |
|---|---|---|
| **A（推荐→已执行）仓内 CodeQL 模型包** | 新增 `.github/codeql/extensions/agent-platform-python/`（`codeql-pack.yml` + `models/*.model.yml`），用 `barrierModel` 声明 `safe_filename`/`safe_join`/`resolve_within` 返回值为 `path-injection` barrier，用 `barrierGuardModel` 声明 `Path.is_relative_to` 为守卫 | 唯一能让「收敛到 kernel」这一架构选择与 CodeQL 长期兼容的路。**原列的「停用 default setup / 新增 workflow / 切换期告警重开 / 多花 Actions 分钟」四项代价经核查均不存在**（见下方纠正块） |
| B 在调用点内联 containment 复检 | `FileResponse` 前手写 `if not abs_path.is_relative_to(base): raise` | **否决**：与本仓 P7-1 不变量（白名单外禁手写 `.is_relative_to(`）正面冲突，要它就得给 lint 开洞；且完全消不掉 kernel 内部的 `#40`~`#42` |
| C default setup 下用「已发布的模型包」 | 把模型包 publish 到注册表，再在组织 Security 设置「展开 CodeQL 分析」中引用 | **否决（原因本身是错的）**：本文原写「GitHub 文档明确 default setup 只接受**已发布**的模型包」——那句只适用于**组织级**扩展；仓级本地包无需发布，故本选项的额外成本纯属虚构 |
| D 全部人工 dismiss 附证据 | `#23`/`#40`~`#42` dismiss `false_positive`（理由：containment 已由 kernel 单一实现强制，且有 `test_file_endpoints.py`/`test_guardrails_fs.py`/P7 三层佐证） | 作为**模型包生效前的过渡**保留面板可信度；不是终态——每加一个新调用点就可能再冒新告警 |

> **⚠️ §4 前提纠正（2026-10-01 查证官方文档《编辑默认设置配置》/《创建并使用 CodeQL 包》）**
> 原判断「本地 `.model.yml` 需配 advanced setup 才能可靠加载」**错误**。原文：**在仓库的 `.github/codeql/extensions` 目录中复制模型包目录（含 `codeql-pack.yml` 与数据扩展 `.yml`），模型包将在 code scanning 分析中被自动检测并使用**；且「如果以后将配置更改为使用高级设置，`.github/codeql/extensions` 目录中的任何模型包也将被识别和使用」。
> → **无需停用 default setup、无需新增 workflow、无扫描黑窗、不多花 Actions 分钟**。本批最终形态即「只加两个文件」。
> 教训与 §2 同源且更进一步：**选型前必须把「能不能」查到原文出处**；把组织级限制误当仓级限制，会直接导致向用户推荐一个带风险的多余基础设施变更。

**推荐组合**：**A 为终态**，落地前用 **D** 维持面板干净（一次性 6 条：`#23`/`#40`/`#41`/`#42` + `#34`/`#38`/`#39` 里未处置的部分）；`#43`/`#44` 单独决策，见 §5。

## 5. `#43`/`#44` 的两个可接受终态（需二选一）

两处的 `logger.warning` 是 Batch 3 的刻意设计：**越界线索只进服务端日志，绝不进异常消息/出站响应**（异常消息只带 `reason`）。CodeQL 判 `clear-text-logging-sensitive-data` 的触发链是日志值经 `resolve_thread_id(thread_id, api_key)` 派生自 API Key（实为 HMAC 指纹摘要，非密钥本体）。

- **终态 1（保取证，走 dismiss）**：日志保留入参原文。理由——被记的是**摘要**与**请求路径**，不是密钥；而拒绝事件若无原文就无法区分攻击形态。dismiss `false_positive`，理由同步写进 `fs.py` docstring。
- **终态 2（保告警清洁，改码）**：`_reject`/`_ensure_within` 不再打 `input=%r`/`resolved=%r`，改打 `reason` + `base` + 入参长度；原文取证降级为「需要时在调用点临时开 DEBUG」。成本是越界排障线索变弱，且新增/修改 kernel 单测断言日志内容。

**默认取终态 1**（取证价值 > 面板整洁，且出站已由 `PathTraversalError` 的「异常消息不带原文」与 P8 双重封住）。若你更看重告警归零，改选终态 2 即可，代码面很小。

> **模型包无法覆盖此类的实测依据**：官方 Python 数据扩展的在册 sink kind 只有 `code-injection` / `command-injection` / `path-injection` / `sql-injection` / `html-injection` / `js-injection` / `url-redirection` / `unsafe-deserialization` / `log-injection`，**不含 `clear-text-logging-sensitive-data`**，并明说「并非每个 query 都支持自定义 sink」。故 `#43`/`#44` 无 barrier 可写，终态 1（人工 dismiss）是技术上唯一可行路径，不再是风格偏好。

## 6. 影响面与验收标准

**影响面（实际执行形态）**：仅新增 `.github/codeql/extensions/agent-platform-python/` 下 2 个 YAML；**不改任何产品代码、不改 CI workflow、不动 Security 面板配置**。

**已实施记录见 §9。**

**验收标准**
1. ✅ 已测：`#23` 闭合（`state=fixed`）。⚪ `#40`~`#42`：`#40`/`#41` 已闭合，`#42` 未闭合且经分析为**结构不可消除**（见 §9.1），改走人工 dismiss。
2. **模型包非空转自证**（仍未做，待下轮）：临时移除 `models/*.model.yml` 中 `resolve_within` 的 barrier 行 → 重扫必须重新报出 `#23`；随后恢复。（本机无 CodeQL CLI，只能在 CI 侧做。现已有旁证：`#23` 在加包前 open / 加包后 fixed，且代码未动，但这仍不等于反证已做。）
3. ✅ 已测：包格式非法会使分析整体失败——实际 PR #36 的 `CodeQL` / `Analyze (python)` / `Analyze (actions)` 均 pass，包已正常加载。
4. `make ci` 全绿：`lint_architecture.py`（P4-2/P2/P5/P6/P6-2/P7/P8）+ 各 pytest session 无回归，尤其 P7 判定面未被放宽。
5. `scripts/check_doc_sync.py` 通过（新增 workflow/config 路径若在文档中被引用，须能解析）。
6. open 告警中除 `#34`/`#38`/`#39`（+ `#43`/`#44` 若取终态 1，以及 `#40`~`#42` 若 guard 未生效）外无其他项，且每条 dismiss 都附可复核理由并入库。

## 7. 可复跑命令

```bash
# 合入前后对比（open / closed 分组）
gh api "repos/Light-Towers/agent-platform/code-scanning/alerts?state=open&per_page=100"
gh api "repos/Light-Towers/agent-platform/code-scanning/alerts?state=closed&per_page=100"
# 单条详情（含实例位置与消息）
gh api "repos/Light-Towers/agent-platform/code-scanning/alerts/40" --jq .most_recent_instance.message.text
# 主干最近分析（确认合入是否触发重扫）
gh api "repos/Light-Towers/agent-platform/code-scanning/analyses?ref=refs/heads/main&per_page=3"
# 是否阻断合并（本仓 main 无保护 → 红检查不阻断）
gh api "repos/Light-Towers/agent-platform/branches/main/protection"   # 实测 HTTP 404
```

## 8. 遗留人工项（与代码无关）

- `security_events` scope：`gh auth refresh -s security_events` 后 §4-D 的 dismiss 才可脚本化，否则须在面板手工执行（凭据级动作，不代做）。
- 部署侧：配 `AGENT_PLATFORM_SECURITY_PEPPER`（一经使用勿再变更），上线前 dry-run `scripts/migrate_thread_identity.py`。
- `docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md` L167 的证伪结论已在原文处加纠正标记。

## 9. 实施记录（2026-10-01 Batch 6 落地）

**产物**（仅 2 个新文件，零产品代码变更）：
- `.github/codeql/extensions/agent-platform-python/codeql-pack.yml`——`library: true`、**无 dependencies**（官方对模型包的硬约束）、`extensionTargets: codeql/python-all: "*"`、`dataExtensions: models/**/*.yml`。
- `.github/codeql/extensions/agent-platform-python/models/agent_core.guardrails.fs.model.yml`——`barrierModel` 6 行（3 个 helper × 2 种 type 形态）、`barrierGuardModel` 2 行（`Path.is_relative_to` × 2 形态）。

**与原方案的两处写法修正**（均在查到官方原文后确定，非臆测）：
1. 原文写的「声明为 `sanitizer`」在 Python 数据扩展里不存在这个谓词——官方给的是 **`barrierModel(type, path, kind)`**（3 列，kind 与要抑制的 sink kind 同名，样例即 `html.escape`）与 **`barrierGuardModel(type, path, acceptingValue, kind)`**（4 列，样例即 django 的 `url_has_allowed_host_and_scheme`）。接收者用 `Argument[this]` 而非 `Receiver`。
2. 原文写的「`PathTraversalError` 声明为 taint-blocking 异常」在 Python 侧无对应可扩展谓词（Java/C# 模型有 `throws` 类修饰，Python 官方谓词表里没有），**故本批未声明异常阻断**；kernel 体内 `#40`~`#42` 指望的是 `is_relative_to` 的 guard 建模，不生效则走 §4-D 人工 dismiss。

**本机已验（证据层级：本地工具可查）**：两个 YAML 均 `yaml.safe_load` 通过，列数与官方谓词签名一致（barrierModel 3 列 / barrierGuardModel 4 列）、pack 无 dependencies；`check_doc_sync.py` 0 警告、`lint_architecture.py` exit 0（P7 判定面未动）。

**未验（必须诚实标注）**（本段为实施当时的状态，已由 §9.1 补验）：模型包是否真被 default setup 加载、`#23`/`#40`~`#42` 是否因此闭合——本机无 CodeQL CLI，只能靠 PR 的 CodeQL 作业不报红 + 合入后主干重扫的告警差集判定（§6 验收项 1~3）。

### 9.1 验收结果（2026-10-01，PR #36 合入 `0bc5175` @09:19:03Z，主干重扫 09:20:29Z，CodeQL 2.27.1）

**open 9 → 6**，闭合的三条全部 `state=fixed` 且 `dismissed_at=None`（**自动闭合，非人工 dismiss**）：

| 告警 | 位置 | 结果 | 归因 |
|---|---|---|---|
| `#23` | `agent_federation/api/server.py:264` `FileResponse(abs_path)` | **fixed** ✅ | `barrierModel` 对 helper 返回值生效——同时反证模型包**确被 default setup 加载** |
| `#40` | `fs.py:119` `Path(base).resolve()`（`safe_join`） | **fixed** ✅ | `barrierGuardModel`（`is_relative_to`）生效 |
| `#41` | `fs.py:134` `_ensure_within(root, current.resolve())` | **fixed** ✅ | 同上，guard 就在此行之后的分支里 |
| `#42` | `fs.py:162` `resolved = candidate.resolve()`（`resolve_within`） | **仍 open** | 结构性不可消除，见下 |

**`#42` 为何单独存活（不是漏修）**：`resolve_within` 的顺序必然是 `candidate.resolve()` → `_ensure_within(root, resolved)`（`:162` → `:167`）——**不先 resolve 就无从判断是否越界**，所以 sink 永远在守卫之前，`barrierGuardModel` 的作用域不可能覆盖它。`#40`/`#41` 能关是因为那两处的污点流经过已建模的守卫。要消掉 `#42` 只能把 `Path.resolve` 的返回值全局声明为 barrier——**那是假的**（`resolve()` 本身不做任何净化，且会屏蔽全仓其他真实路径注入），按「不为躲检测器而改结构/编模型」的纪律否决，转人工 dismiss 附本段理由。

## 10. 回滚

本批回滚 = 删除 `.github/codeql/extensions/agent-platform-python/` 整个目录（2 个 YAML）。**不动面板配置、不动 workflow**（本来就没改），default setup 下一次重扫自动回到当前告警集；产品代码未改动，故无数据/行为回滚面。风险面仅在「若包格式非法会使分析整体失败」——已由 PR 的 CodeQL 作业先行验证后才合入。
