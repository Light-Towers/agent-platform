# Plan：Code Scanning（CodeQL）21 条告警的全局收口方案

> 触发：`/security/code-scanning` 下 **21 条 open**（全 CodeQL，14 high / 7 medium）。用户要求「站在项目全局整体角度，先出方案」。
> 本文性质：**方案（待批准后再编码）**。遵循 AGENTS.md 红线——安全敏感代码（鉴权/路径/错误处理）改动前必须先出方案；横切关注点走「单一实现(kernel) + 全局装配(构造保证) + 强制门禁(lint)」三层收敛，禁止逐处散点打补丁。
> 取证基于实读代码（非仅 CodeQL 标签），file:line 均可复核。

## 0. 一页结论

21 条按规则聚为 5 类，**处置性质三分**：真修 / 横切收口 / triage 误报。

| 类 | 数(sev) | 位置 | 实读判定 | 处置档位 |
|---|---|---|---|---|
| **A. py/path-injection** | 8 high | `agent_federation/api/server.py` 244–289 | download/list **已有 `is_relative_to` 防护**、upload 已有 `_sanitize_filename`（`Path().name`）——**均可控遍历，CodeQL 不认这些为 sanitizer**；但 284/300 把 `str(e)` 塞进 detail | **真修（横切）**：抽 kernel 级 `safe_join` 单一实现 + 停用 `str(e)`；让 CodeQL 与人共同可识别 |
| **B. py/weak-sensitive-data-hashing** | 5 high | `agent_core/guardrails/auth.py:46`、`agent_server/api/auth.py:29`、`agent_federation/api/auth.py:27`、`agent_federation/gateway/gray.py:40`、`agent_core/llm/registry.py:45` | **同一「从 api_key 派生稳定 token」的操作被抄了 4 遍、且强度不一致**：`auth.py:29`/`federation:27` 用 `sha256(key)[:12]`（48bit 截断）派生**会话身份**（防跨租户串会话，安全相关，真该修）；`auth.py:46`(限流桶)/`registry.py:45`(缓存键) 全量 sha256（弱安全相关）；`gray.py:40` `md5(user_id)` 灰度 0–99 桶（**非敏感、非隔离，唯一真误报**） | **根因修（收敛），非 dismiss**：抽单一实现 `agent_core.guardrails.auth.fingerprint(key)`＝HMAC-SHA256 + 服务端 pepper + 定长摘要，替换 4 处；仅 `gray.py:40` dismiss。**dismiss 只用于「已证明非真问题」** |
| **C. py/stack-trace-exposure** | 4 medium | `exhibition-agent/.../skill_loader/app.py` 109/148/181、`agent_server/api/query_router.py:382` | 路由**主动** `except Exception as e: return JSONResponse({"error": f"...{e}"})`，绕过 `install_error_handlers`（各 app 已装配） | **横切收口**：删手动 traceback 回显、交全局 handler 兜底；补 lint 门禁 |
| **D. actions/missing-workflow-permissions** | 3 medium | `.github/workflows/{eval-llm,ha,agent-platform-ci}.yml` | workflow 缺顶层 `permissions:` 块，默认全授权 | **真修（快赢）**：加最小 `permissions:` |
| **E. py/incomplete-url-substring-sanitization** | 1 high | `packages/agent-runtime/tests/test_skills_remote_dag.py:22` | **测试文件**夹具里的 URL 子串判断 | **先核生产代码是否同模式**：若生产用同款弱判断→根因修生产；确认仅测试夹具→dismiss |

**净可编辑真修**：A(8) + C(4) + D(3) + **B 收敛(4 api-key 站点)** = 真修主体，其中 A/B/C 归并为「kernel 横切能力（safe_join / fingerprint）+ 站点收敛 + lint 门禁」，D 独立快赢。
**仅真误报可 dismiss**：B 中 `gray.py:40`(1) + E(待核) 。**原则：dismiss 是「证明其非真问题」的收尾，不是压告警的手段**；凡真实反模式一律根因收敛。

## 1. 全局原则（对齐 AGENTS.md P2 先例）

AGENTS.md 已确立「入站错误脱敏」三层收敛范例：`build_api_app`(全局装配) + `agent_core.guardrails.errors`(单一实现) + `lint_architecture.py`「裸 `FastAPI(` 即失败」(门禁)。本方案把 **路径** 与 **错误回显** 也纳入同一范式：

| 关注点 | 单一实现(kernel) | 全局装配 | 强制门禁 |
|---|---|---|---|
| A 路径注入 | 新增 `agent_core.guardrails.fs.safe_join(base, *user_parts) -> Path`（resolve + `is_relative_to` 包含判定，越界抛错） | federation 各文件端点统一调用它 | `lint_architecture.py` 新增：api 层禁用裸 `Path(<request>)` 直接 I/O（白名单 helper 外） |
| C 堆栈回显 | 复用 `agent_core.guardrails.errors.install_error_handlers`（已存在） | 各 app 已装配（main.py/server.py 均引用） | `lint_architecture.py` 新增：api handler 内 `return ...(f"...{e}" / traceback / str(e))` 即失败 |
| B 敏感指纹 | 新增 `agent_core.guardrails.auth.fingerprint(secret) -> str`（HMAC-SHA256 + 服务端 pepper，定长） | 4 处 api-key 哈希改调它（消除 4× 重复 + 无 pepper/截断弱点） | 禁裸 `hashlib.(md5|sha1|sha256)(api_key)`（白名单 helper + gray 路由桶外） |

> **dismiss 仅用于「已证明非真问题」**：B 中只有 `gray.py:40`（非密钥、非隔离的 md5 分桶）属此类；E 需先核生产代码后定。**不以 dismiss 压告警数**。

## 2. 关键取证（实读，可复核）

- `agent_federation/api/server.py`
  - `:197` `_sanitize_filename` = `Path(name).name` + 正则白名单 + `.`/`..` 归 `_`（**已防目录穿越**）。
  - `:244/251` upload 路径经 `_sanitize_filename`，base 固定 `updated_dir`。
  - `:258–271` `/api/download`、`:274–300` `/api/files`：**已 `abs_path.is_relative_to(output_dir)` → 403**；唯 `:284` `detail=f"路径无效: {e}"`、`:300` `detail=str(e)` **回显异常**。
- `agent_core/guardrails/auth.py:46` `sha256(api_key).hexdigest()` → 限流桶 key（注释「避免内存留存明文」）。
- `gateway/gray.py:40` `md5(user_id)` → 灰度百分比分桶（**非敏感、非安全用途**）。
- `skill_loader/app.py:105–110` `except Exception as e: return JSONResponse({"error": f"Agent 处理失败: {e}", ...}, 500)`（**主动回显**）。
- 各 app 已 `install_error_handlers`（grep 命中 main/server/app_factory）→ 全局兜底在位，站点却各自 catch。

## 3. 分批实施（批准后执行；每批独立 PR + 全门禁 + L3 + eval）

**Batch 1 — 快赢（D，独立）**：3 个 workflow 加顶层 `permissions:`（按最小权限：如 `contents: read`，需写产物的 job 单独 `pull-requests: write` 等，逐 job 核）。验收：CodeQL `missing-workflow-permissions` 归零。

**Batch 2 — 敏感指纹收敛（B，根因修）**：
1. kernel 新增 `agent_core.guardrails.auth.fingerprint(api_key)`＝`hmac.new(server_pepper, api_key, sha256)`，返回定长（≥ 32 hex）摘要；pepper 来自配置（无则启动告警）。含单测：同 key 稳定、异 key 不等、不同 pepper 结果不同（防跨部署碰撞）。
2. 替换 4 处 `hashlib.sha256(key)[:12]`/全量：`auth.py:46`、`agent_server/api/auth.py:29`、`federation/api/auth.py:27`、`registry.py:45`。
   - **注意**：`thread_id`/会话目录已按旧 `[:12]` 落盘——切换派生法需**兼容迁移**（新键 + 一次性 rename 或双读过渡），避免用户历史会话失联；此项列入实施风险。
3. `gray.py:40`（md5 非敏感）→ **dismiss 附证据**，不改码。
4. `lint_architecture.py` 增「禁裸哈希 api_key（白名单 helper 外）」。
验收：B 4 条从根因消除、gray dismiss；会话迁移有回归测试；make ci 绿。

**Batch 3 — 路径横切（A，原 Batch 2 顺延）**：
1. kernel 新增 `agent_core/guardrails/fs.py::safe_join`（含单测：正常拼接 / `..` 越界抛 `PathTraversalError` / 绝对路径拒绝）。
2. `server.py` 4 个文件端点改用 `safe_join`；`:284/:300` 的 `detail` 改固定脱敏文案（异常仅入服务端日志）。
3. `lint_architecture.py` 增「api 层裸路径 I/O」规则 + 白名单。
验收：A 8 条消除；新增 fs 单测过；make ci 绿。

**Batch 4 — 堆栈回显横切（C）**：
1. `skill_loader/app.py` 3 处 + `query_router.py:382`：移除 `f"...{e}"`/`str(e)` 回显，改为不 catch（交全局 handler）或返回 `SANITIZED` 固定文案（异常 `logger.exception`）。
2. `lint_architecture.py` 增「api 响应体禁回显异常/traceback」规则。
验收：C 4 条消除；lint 反例用例过（沿用 `test_guardrails_errors.py` 风格）。

**Batch 5 — 误报收尾（E）**：先核 `test_skills_remote_dag.py:22` 对应的**生产逻辑**是否同款弱判断；若生产有则并入 A/新批次根因修，若纯测试夹具→dismiss 附注「测试专用」。
验收：open 告警降到 0（或仅剩登记在案的已接受风险）。

## 4. 验收门禁（对齐用户"实跑证据"纪律）

- 每批：`uv run --with ruff ruff check .` + `lint_architecture.py` + `check_doc_sync.py` + 受影响 pytest session + `make eval` 冒烟；声称完成前 `make test` 对齐 CI。
- 横切新增 kernel 能力**必带单测**（safe_join / fingerprint / lint 反例）。
- 安全敏感改动 push 前走 **L3 深度审查**。
- **红线**：不得为消警放宽断言/删用例；dismiss 必须附可复核证据注释。

## 5. 不做 / 边界

- **不改对外 4xx `{detail}` 信封形状**（沿用 errors.py 的 D-2=A 零破坏原则）；错误体收敛为独立决策，另案。
- **不在本方案处理 Dependabot #26**（13 项例行升级，非安全；当前卡 CONFLICTING + 本机 SSH 限流，另议）。
- B 是否引入 HMAC helper 为 D-0 决策点，取决于「消警彻底度 vs 改动面」权衡，**待用户拍板**。

## 6. 待用户确认的决策点

- **D-0（已定）**：B 走**根因收敛**（kernel HMAC `fingerprint()`）替换 4 处 api-key 哈希；仅 `gray.py:40` 真误报 dismiss。撤销早先「纯 dismiss」倾向（那是压告警非解决）。
- **D-1（已定）**：按 1(D) → 2(B) → 3(A) → 4(C) → 5(E) 执行（先快赢，再安全相关的 B）。
- **D-2（已定）**：新增 lint 门禁**纳入本批**（P6）——三层缺第③层就只是约定，契合 AGENTS.md 全局优先原则。

## 7. 实施进度（随批次更新）

| Batch | 状态 | 落地位置 | 验收证据 |
|---|---|---|---|
| 1（D 类 workflow 最小权限） | ✅ 代码完成（本地 commit `e488c96`，待 push + PR） | 3 个 workflow 顶层 `permissions: contents: read` | 全仓 3/3 workflow 均有顶层 `permissions:`；CodeQL 需重扫确认归零 |
| 2（B 类指纹收敛） | ✅ 代码完成（未 commit） | kernel `guardrails/auth.fingerprint`/`derive_thread_id`/`legacy_thread_id`；4 站点改指；`lint_architecture.py` P6；`scripts/migrate_thread_identity.py` | 实跑结果（2026-10-01）：`ruff check .` 干净；`lint_architecture.py` P4-2/P2/P5/P6 全通过（含全仓零违规）；`check_doc_sync.py` 0 警告；根 session **661 passed**、联邦 **135 passed**、agent_server **41 passed**、agent-runtime **569 passed**、shared-schemas **28 passed**、kefu **43 passed**、nl2sql **18 passed**；`eval/run_eval.py --fail-below 0.8` → **15/15 = 100%** |
| 3（A 类 safe_join） | ✅ 代码完成（未 commit） | kernel 新增 `guardrails/fs.py`（`safe_join`/`resolve_within`/`safe_filename`/`PathTraversalError`）；federation 3 个文件端点收敛 + `:284/:300` 固定脱敏文案；`lint_architecture.py` P7-1/P7-2 | 实跑结果（2026-10-01）：`ruff check .` 干净；`lint_architecture.py` P4-2/P2/P5/P6/**P7** 全通过（当前树零违规）；`check_doc_sync.py` 0 警告；根 session **711 passed, 2 skipped, 17 deselected**、agent-core **268 passed, 2 skipped**、联邦 **152 passed**、agent-runtime **569 passed**、shared-schemas **28 passed**、agent_server **41 passed**、kefu **43 passed**、nl2sql **18 passed**；`eval/run_eval.py --fail-below 0.8` → **15/15 = 100%**；ks 231 passed（+5 存量红）、exhibition 343 passed（+1 存量红），与 Batch 2 基线一致无新增失败。CodeQL A 类归零仍需 GitHub 重扫确认 |
| 4（C 类堆栈回显） | ✅ 代码完成（未 commit） | kernel `guardrails/errors.mask_exception_for_client`（脱敏边界点，复用 `SANITIZED_5XX_MSG`）；6 站点收敛（exhibition `skill_loader/app.py` ×3 + `skill_loader/agent.py` + agent_server SSE 帧 + ks SSE 帧 ×2）；`lint_architecture.py` P8 | 实跑结果（2026-10-01）：`ruff check .` 干净；`lint_architecture.py` P4-2/P2/P5/P6/P7/**P8** 全通过（当前树零违规）；`check_doc_sync.py` 0 警告；**对 HEAD 版本回放 P8 命中 6 条**（与修复前站点逐条对应，规则非空转）；根 session **749 passed, 2 skipped, 17 deselected**、agent-core **274 passed, 2 skipped**、联邦 **152 passed**、agent-runtime **569 passed**、shared-schemas **28 passed**、agent_server **41 passed**、kefu **43 passed**、nl2sql **18 passed**；`eval/run_eval.py --fail-below 0.8` → **15/15 = 100%**；ks 231 passed（+5 存量红）、exhibition **347** passed（+4 新用例，+1 存量红），与 Batch 3 基线一致无新增失败。CodeQL C 类归零仍需 GitHub 重扫确认 |
| 5（E 类夹具核实） | ✅ 完成（未 commit） | 生产面核定：无生产侧同款弱判断（扫全仓非测试面 0 命中）；夹具本身**根因消除**而非仅 dismiss：`test_skills_remote_dag.py:22` 子串包含 → 等值断言 | 实跑结果（2026-10-01）：`uv run pytest packages/agent-runtime/tests/test_skills_remote_dag.py -q` → **5 passed**（断言由子串包含收紧为等值，未放宽）；`ruff check .` 干净；`lint_architecture.py` P4-2/P2/P5/P6/P7/P8 全通过；`check_doc_sync.py` 0 警告。**生产面核定**：packages/ 与 applications/ 非测试代码内对「子串包含判定 URL 域名/主机」命中 **0 条**（正则：字面量含 `.com/.cn/localhost/://` 与 `in <url 类变量>` 两面均零），因此无生产根因可修。**全 9 session 收口复跑（同一时点）**：根 749 passed / 2 skipped / 17 deselected、agent-core 274、agent-runtime **569**、shared-schemas 28、agent_server 41、联邦 152、kefu 43、nl2sql 18、exhibition 347（+1 存量红）、ks 231（+5 存量红）；`eval` 15/15=100%。E 类归零仍需 GitHub 重扫确认 |

**五批收口盘点（本仓代码面已无待修项，余下均为人工/环外动作）**：

| 告警 | 处置 | 尚需人工动作 |
|---|---|---|
| A `py/path-injection` ×8 | Batch 3 已根因收敛（kernel `guardrails.fs` + P7） | GitHub 重扫确认归零；若仍报，补 CodeQL data-extension 将 `safe_join`/`resolve_within` 声明为 sanitizer |
| B `py/weak-sensitive-data-hashing` ×5 | Batch 2 已收敛 4 个 api-key 站点（kernel `fingerprint` + P6）；`gray.py:40` 为真误报 | 仅 `gateway/gray.py:40` 需 dismiss，附证据：非密钥、非隔离的 `md5(user_id)` 灰度 0–99 分桶 |
| C `py/stack-trace-exposure` ×4 | Batch 4 已收敛 6 站点（kernel `mask_exception_for_client` + P8） | GitHub 重扫；若仍报，同 A 补 sanitizer 模型声明 |
| D `actions/missing-workflow-permissions` ×3 | Batch 1 已加顶层 `permissions: contents: read` | push + PR 后由重扫确认 |
| E `py/incomplete-url-substring-sanitization` ×1 | Batch 5 已根因消除（夹具等值断言），无需 dismiss | GitHub 重扫后本条应自行关闭 |
| 运维随 Batch 2 | 指纹/会话 ID 切换 | 部署时配 `AGENT_PLATFORM_SECURITY_PEPPER` 并先 dry-run 后执行 `scripts/migrate_thread_identity.py` |

**Batch 2 实施记录与偏差**：
- 会话摘要宽度定为 **32 hex（128bit）**（方案只写「定长 ≥ 32 hex」）；`fingerprint(length=...)` 对低于 32 的请求直接 `ValueError`，把「弱截断」做不成合法调用而不是靠注释约束。
- pepper env 定名 `AGENT_PLATFORM_SECURITY_PEPPER`（对齐已有 `AGENT_PLATFORM_DATABASE_URL` 前缀）；未配置时**仍可用**，只在首次派生告警一次（不做 fail-open 开关，也不阻断启动）。
- 会话兼容策略选了「**一次性迁移脚本**」而非双读/兼容开关：双读需改对外契约（历史接口返回哪个 thread 的会话），而 pepper/派生法切换本质是一次性运维动作；`dev-default-thread` 字面量顺手上收为 `DEV_THREAD_ID`（DUP-3 残留）。
- **未执行项（需人工）**：GitHub 上对 `gray.py:40` 的 dismiss（附证据：非密钥、非隔离的灰度分桶）；上线时根据部署实际情况跑 `scripts/migrate_thread_identity.py`（先 dry-run）与配 pepper。
- **两处与本批无关的存量红**（已用 `git stash` 回基线复核确认为 **先前就失败**，非本批引入）：
  1. `applications/knowledge-service/tests/unit/test_tracing.py` 5 条 SDK 用例失败（全局 TracerProvider 被先前用例占用 → in-memory exporter 收到 0 span）；
  2. `applications/exhibition-agent/tests/test_server.py::test_query_success_response_carries_traceparent` ImportError：该用例从 `opentelemetry.sdk.trace.export` 导 `InMemorySpanExporter`，而本地 SDK 版本仅子模块 `...export.in_memory_span_exporter` 暴露。
  两者均属可观测性测试的环境/泄漏问题，归后续单列处理，不混进安全批次。

**Batch 3 实施记录与偏差**：
- 拆为**两个入口而非一个**：`safe_join`（拼接语义，绝对片段/`..`/NUL/空一律拒绝）与 `resolve_within`（解析语义，允许绝对入口但必须落在 base 内）。原因见对外契约审计：`/api/files` 返回绝对路径、前端原样回传，若只用严格 `safe_join` 会静默破坏既有消费者（AGENTS.md「全局优先不等于强行统一对外契约」）；仓内 grep 确认 `path` 入参无仓内消费者，外部前端无法在此仓验证，故选宽容入口。
- `PathTraversalError` **异常消息不回带入参原文**（越界线索只写服务端日志），并把该性质固定为单测（`test_safe_join_error_message_does_not_leak_input`）——否则下游一句 `detail=str(e)` 就能把内部路径泄出去。
- 顺带消除两个 **C 类同源站点**：`:284` `detail=f"路径无效: {e}"` 与 `:300` `detail=str(e)` 改固定文案 + `logger.exception`；`/api/download` 的存在判定由 `exists()` 收紧为 `is_file()`（旧实现会把目录当文件回传）。Batch 4 仍负责 `skill_loader/app.py` 3 处与 `query_router.py:382`。
- 文件名净化一并上收为 `guardrails/fs.safe_filename`（原 `_sanitize_filename` 是本文件私有实现，CodeQL 不认），行为等价 + 空串归 `_`。
- P7 拆两条子检查：P7-1 白名单外禁手写 `.is_relative_to(`；P7-2 `applications/**` 下路径含 `/api/` 的模块若有 `FileResponse(`/`.rglob(`/`.glob(` 出口却未调 kernel helper 即失败。白名单：kernel `fs.py` + ks 两个静态页面 router（`PROJECT_ROOT` 常量拼接，无请求输入）。
- **未执行项（需人工）**：A 类 8 条告警的归零确认需在 GitHub 侧重扫（本机无 CodeQL CLI）；若重扫仍残留，下一步是补 CodeQL data-extension model 把 `safe_join`/`resolve_within` 声明为 sanitizer，而非回到各处手写。

**Batch 4 实施记录与偏差**：
- **按不变量收敛，不按告警条数收敛**：CodeQL 只标 4 条（`app.py` 3 + `query_router` 1），实修 **6 处**：另两处是 ks `api/query_router.py:165` 与 `nodes/node_answer_output.py:162` 的 SSE `ERROR` 帧（完全同构的出口，CodeQL 跟不到因为中途经队列传递），以及 `skill_loader/agent.py:243`（工具 502 body 经 `/api/chat` 的 `tool_calls[].result_summary` 回传客户端）。若不一次收干净，P8 上线后这些同模式站点仍会逐批被重新发现。
- kernel **不新增第二套文案常量**：方案已定复用 `install_error_handlers`，但它兜不住流式/手写出口（状态码已发），故只新增一个**边界函数** `mask_exception_for_client(exc, *, logger, context, message)`，文案仍用已有 `SANITIZED_5XX_MSG`（D-2=A 零破坏）。`exc` 参数刻意**不参与返回值**——一旦从异常派生任何字段，泄漏面就重开。
- **日志器类型差异（先实测后发现）**：kernel 内部日志用 f-string 而非 `%s` 惰性格式化，因为 ks 全仓用 **loguru**（`{}` 格式化，`%s` 会被丢弃）；因此 ks 两处站点**不传 logger**（它们已在就地 `logger.error(...)` 记录），exhibition / agent_server（std logging）才传 `logger=`。已写进函数 docstring。
- **4xx 回显从判定面排除**（而不用白名单）：exhibition `server.py:91/96` 的 `detail=f"...{exc}"` 是 JSON/pydantic 输入校验回显，面向调用方自身输入且 CodeQL 未标；按 D-2=A「不动各 app 现有 4xx `{detail}` 信封」，将其作为规则的第 4 条放行面写进 lint 注释与单测（含反例），而非留为静默例外。
- P8 白名单**故意置空**并有单测钉住（`test_p8_whitelist_is_deliberately_empty`）：本不变量不允许未说理的例外，与 P6/P7 “白名单只放单一实现”写法不同。
- **范围外登记（需先做“内部详情 vs 对外文案”通道分离）**：nl2sql `agent/nodes/execute_sql.py:31` 的 `state["error"] = str(exc)` 会经 `SqlQueryResponse.error` 出到客户端，但**同一字段又是 `correct_sql` 节点的 LLM 纠错输入**，直接脱敏会削弱纠错回路；同类还有 federation `tools/*` 的 LLM 观察字符串与 `monitor.report_error(detail=str(e))` 审计遥测、agent_server `planners/graph.py` / `sql/pipeline.py` 的 StreamEvent error payload、exhibition `foundation/production_readiness_gate.py`。均为非 HTTP 出口行内拼接，P8 不命中，归后续单列。
- **测试层次取舍**：ks 两处站点**无行为级回归用例**——ks `tests/unit/conftest.py` 明文“本套测试刻意不依赖任何重型依赖”，导入 router/main_graph 会破其设计；改由 kernel 单测（脱敏性质）+ P8 结构门禁（含以 ks 原始行作为正例）覆盖。exhibition 4 个出口与 agent_server SSE 帧均有端点级行为回归。
- **未执行项（需人工）**：C 类 4 条告警的归零确认同样需 GitHub 重扫；若重扫仍残留（例如认为 `mask_exception_for_client` 不是 sanitizer），下一步是补 CodeQL data-extension model 声明该函数为 sink barrier。
- **附带发现（与本批无关的文档漂移）**：根 `AGENTS.md` 推荐的 `docs/operations/testing-playbook.md` 在仓内不存在（`docs/operations/` 实有 6 个文件，无此名），`check_doc_sync.py` 未覆盖该引用形式故未报警。登记为存量，待单独处理。

**Batch 5 实施记录与偏差**：
- **把 dismiss 升级为根因消除**：方案原定“纯测试夹具→dismiss 附注”，实测发现该断言可改为**更强的等值断言**（`result == "content from http://example.com"`）而无任何覆盖损失，于是不留永久人工动作（dismiss 需去 GitHub 点，且代码里的“已核实为误报”注释债会长期跟仓）。红线「不得为消警放宽断言/删用例」在此不适用——改动方向是收紧。额外补一条 `isinstance(result, str)` 钉住薄包装不得多包一层。
- **不开 P9 lint，并在这里承认它是「三层齐备」的例外**（本例只修了单一形式，第③层门禁故意缺失，故属约定而非门禁）。理由：本仓 `lint_architecture.py` 只走 stdlib 正则、无类型推断，无法区分弱校验形态 `"example.com" in result`（子串包含）与**正确形态** `host in ALLOWED_HOSTS`（集合成员）——同一行内两者写法相似，任何正则判定面都会误伤后者；而正确写法正是我们希望鼓动的。生产面命中为 0，无存量需守，因此该维度继续交给 **CodeQL 自身规则**（已在 code scanning 里）而不是自造窄 lint。
- **同类形状未改码（仅登记）**：`applications/exhibition-agent/tests/test_model_router.py:230` 的 `assert "z***@example.com" in masked` 同为子串包含，但主语是邮箱脱敏结果且 CodeQL 未标（规则只跟 URL）；相邻 `:229` 的 `not in` 反而是「不得泄漏」的正确断言。若日后重扫命中同规则，按本法改等值断言即可，本轮不动。
- **核生产时的两条附带观察（不构成 E 类，不改码）**：
  1. `applications/agent_server/sql/pipeline.py:48` `sqlite3.connect(f"file:{unquote(path)}?mode=ro", uri=True)`——若 `path` 解码后含 `?`，`mode=ro` 会落到首个参数的值里而静默失效（只读「双保险」退化为只靠 SQL 守卫一层）。当前 `path` 源自服务端配置 `SQL_DSN`（非请求入参），故不列为可利用漏洞；登记为硬化候选（用 `?`/`#` 转义或 `uri` 参数拼接）。
  2. 同文件 `:65` 的 `dsn.startswith("sqlite:///")` 是对 URL 的**前缀**判定（非子串包含），属方案选型可接受的写法；仅因与 E 类同属「URL 字符串形状判定」一并登记。
- **未执行项（需人工）**：E 类 1 条在 GitHub 侧的最终关闭确认（本仓无 CodeQL CLI，无法本地复扫）；若重扫因历史基线仍列 open，手动关闭并指回本节即可。
