# Plan：横切关注点「散点重复实现」存量普查与根因复盘（2026-10-01）

> 触发：修复 CodeQL `py/weak-sensitive-data-hashing` 时发现「同一 `sha256(api_key)[:12]` 派生逻辑在 4 处各写一遍」。用户要求在动手修 Batch 之前，先做**根因复盘 + 全仓同类散点普查**。
> 本文性质：**审查清单（只记录，不改代码）**。遵循 AGENTS.md「先方案后编码」红线；结论均基于 main 树实读代码（逐文件 file:line 可复核，不凭模式猜）。
> 普查范围：main 树生产代码，排除 `courses/*`（僵尸 manifest）、`**/tests/**`、`*.md`、`.codeartsdoer`。
> 判定口诀（AGENTS.md）：动手前先问——"这件事现在是全局统一处理的，还是每处都写一遍？"
> 关联：已批准的 CodeQL 收口方案 `plan-codeql-codescanning-remediation-2026-10-01.md`；承重/冗余区分依据 `p0-execution-retrospective-2026-09-24.md` §7。

---

## 1. 一页结论

对 8 条横切候选逐条实读后，散点分布高度规律：**凡是立过项主动上收的横切，都收敛得很干净；凡没立项、又恰好被并行应用各写一遍的，就成了散点。**

| ID | 横切关注点 | 现状 | 定性 | 是否有 lint 拦截 |
|---|---|---|---|---|
| **DUP-1** | api_key → 稳定指纹（会话 id / 限流桶 / 缓存键） | ~~4 处各写，截断语义分裂（full vs `[:12]`）~~ → **2026-10-01 Batch 2 已收敛**：kernel `fingerprint` 单一实现 + 4 站点改指 + P6 lint | ~~纯债~~ **已修**（核心） | ✅ 有（P6） |
| **DUP-2** | `error_body` / `ERROR_CODES` 错误信封 | kernel 已上提，但 knowledge-service 保留逐字节相同的副本且未改指 | **纯债**（迁移半成品） | ❌ 无 |
| **DUP-3** | `resolve_thread_id` 会话防劫持整函数 | agent_server 与 agent_federation 各一份（知情复制）→ **Batch 2 已合并至 kernel `derive_thread_id` + `DEV_THREAD_ID`** | ~~纯债~~ **已修**（含于 DUP-1 收敛） | ✅ 有（P6） |
| **DUP-4** | env 配置读取入口 | 三范式并存；federation/exhibition 模块级裸读散点最广 | **债 + 承重混合**（服务边界） | ⚠️ 难通用 lint |
| **DUP-5** | SSE 打包格式 | `shared_schemas.sse_pack` 单实现，余为薄适配器 | **已收敛**（正例） | — |
| **DUP-6** | LLM 客户端构造 | `agent_core.llm.get_llm_client` 门面已建，采用不齐 | **承重-在途**（既有追踪，非新债） | — |
| **DUP-7** | 重试 / 熔断 | `agent_core.resilience` 单引擎；残留手写 HTTP 重试循环 + tenacity 并行选型 | **纯债(部分) + 承重(部分)** | ❌ 无 |
| **DUP-8** | 限流滑动窗口 | `SlidingWindowRateLimiter` 单实现，admission 复用、ks shim 重导出 | **已收敛**（正例） | — |
| **DUP-9** | 缓存 key 生成 | `build_cache_key` 收敛；main_agent 角色缓存键本地化 | **大体已收敛**（1 处半承重） | — |

**核心洞察**：缺的不是方法论（DUP-5/6/8/9 证明"单一实现+全局装配"一旦做了就有效），而是**第③层强制门禁对"横向重复"这一维度完全空白** + **收敛依赖人工立项**。详见 §3。

---

## 2. 存量普查明细（每条含 file:line / 实现差异 / 目标 kernel / lint 可拦截性 / 承重·纯债）

### DUP-1 ★ api_key → 稳定指纹派生（本次 CodeQL B 类的根）

**重复站点（4 处，同一"从 api_key 派生稳定 token"操作）：**

| file:line | 实现 | 截断 | 用途 | 是否安全相关 |
|---|---|---|---|---|
| `packages/agent-core/agent_core/guardrails/auth.py:46` `resolve_client_key` | `sha256(provided.encode("utf-8")).hexdigest()` | 全量 | 限流桶 key `key:<digest>` | 弱（避免明文常驻） |
| `packages/agent-core/agent_core/llm/registry.py:45` `_hash_api_key` | `sha256(api_key.encode("utf-8")).hexdigest()` | 全量 | LLM 客户端缓存键 | 弱（缓存分区） |
| `applications/agent_server/api/auth.py:29` `resolve_thread_id` | `sha256((api_key_header or "").encode()).hexdigest()[:12]` | **[:12]=48bit** | **会话身份 `user-{digest}`（防跨租户串会话）** | **是** |
| `applications/agent_federation/api/auth.py:27` `resolve_thread_id` | `sha256((api_key or "").encode()).hexdigest()[:12]` | **[:12]=48bit** | **会话身份 `user-{digest}`** | **是** |

**实现差异**：① 截断语义分裂（两处全量 64hex、两处 `[:12]` 48bit）；② 输入归一不同（`or ""` 内联 vs 前置判空）；③ **四处均无服务端 pepper**（纯 `sha256(key)`，同 key 跨消费者可关联）；④ `[:12]` 用于安全相关的会话隔离，48bit 截断 + 无 pepper 是**真实弱点**，非纯误报。

**应收敛到的目标 kernel**：`agent_core.guardrails.auth.fingerprint(secret: str, *, length: int | None = None) -> str` = `HMAC-SHA256(服务端 pepper, secret)`，定长摘要。4 处调用它（会话派生传 length、限流/缓存可用全量）。**这正是 CodeQL 方案 Batch 2 的落点。**

**lint 可拦截性**：可。新增一条"禁裸 `hashlib.(md5|sha1|sha256)(api_key/secret)`，白名单 `guardrails.auth.fingerprint` + 明确的非敏感分桶（如 `gateway/gray.py` md5(user_id)）"。**当前 lint 无此维度 → 必须补。**

**定性**：会话派生 2 处 = **纯债**；限流桶/缓存键 2 处 = **半承重**（不同消费者合理，但应共用 fingerprint 以统一 pepper/截断）。`gray.py:40` md5(user_id) 灰度桶 = **唯一真误报/承重**（非密钥非隔离）。

### DUP-2 ★ error_body / ERROR_CODES 上提残留双份

**重复站点（2 份逐字节相同）：**

| file:line | 内容 |
|---|---|
| `packages/agent-core/agent_core/guardrails/errors.py:28-50` | `ERROR_CODES` + `error_code_for_status` + `error_body`（canonical；kernel docstring 自陈"从 knowledge_service.utils.error_response_utils 上提到 kernel，供全仓共享"） |
| `applications/knowledge-service/knowledge_service/utils/error_response_utils.py:15-37` | **同名三符号，与 kernel 逐字节相同** |

**实现差异**：**无（完全重复）**。关键：`knowledge_service/api/errors.py:21` 仍 `from knowledge_service.utils.error_response_utils import error_body, ...`——**上提了 kernel，却漏把源副本改指 kernel/删除**，形成"共享了但源头还在各自用旧的"半成品。

**目标 kernel**：`agent_core.guardrails.errors`（已存在）。修复 = ks 改导入 kernel + 本地 `error_response_utils` 降为 shim 或删除。

**lint 可拦截性**：较难精确 lint（跨包同定义检测成本高），可用"禁在非 kernel 位置重复定义 canonical `ERROR_CODES`/`error_body`"的符号唯一性检查，或纳入既有 `check_doc_sync` 式人工核查。

**定性**：**纯债**（迁移未走完）。低风险、独立，可与 DUP-1 并行。

### DUP-3 resolve_thread_id 会话防劫持整函数（含于 DUP-1 收敛）

`applications/agent_server/api/auth.py:25` 与 `applications/agent_federation/api/auth.py:17` 是**同函数名、同 `user-{[:12]}` 逻辑**的两份，仅配置来源不同（`get_settings().api_key` vs 模块级 `API_KEY = os.getenv("API_KEY","")`）。federation docstring **自陈"对齐 app/api/auth.py 已验证策略"——属知情复制**（见 §3 根因）。收敛入口同 DUP-1（kernel `derive_thread_id`/`fingerprint`）。**纯债**，随 DUP-1 一并解决。

> 附：常量时间比较 `secrets.compare_digest` 在 `agent_server/api/auth.py:20`、`agent_federation/api/server.py:173,194`、`guardrails/web.py:132` 均正确使用同一原语（无时序缺陷），属"各自调正确 stdlib 原语"，**非安全漏洞**，可并入统一 auth wrapper 但不紧急。

### DUP-4 env 配置读取入口（三范式并存）

**已收敛正例**：`knowledge_service/core/config.py`（单 `Settings` dataclass，`load_dotenv()` 仅一次，字段集中 `os.getenv`）、`agent_core/config.py`（`_getenv_*` helper 家族）、`agent_server/config.py`（`get_settings()` pydantic）。

**散点负例**：
- `agent_federation/**`：模块级 `os.getenv` 遍布约 15 文件——`api/auth.py:14`、`api/server.py:42/43/131/140/146/179/226`、`agent/main_agent.py` 十余处、`agent/llm.py:27-68`、`tools/db_tools.py`、`tools/sql_guard.py`、`evaluation/judge.py`（含 `os.environ[...]` 读写切换）等。
- `exhibition-agent/**`：`os.environ.get` 散落 `skill_loader/app.py:32-36`、`llm_client.py:34-39`、`foundation/execution_context.py:70/203`、`skills/data_analysis/skill.py:33` 等。
- `agent_server/capabilities.py:229-333`：绕过 `settings` 直读 `KNOWLEDGE_SERVICE_URL` 等服务 URL；`rag/embed.py:25-32`：直接写 `os.environ`。

**实现差异**：pydantic settings / dataclass Settings / 模块级裸读 三范式并存；federation 无集中入口。

**目标 kernel/位置**：各 app 收敛到自身 `config` 模块单一入口（federation/exhibition 补 Settings；agent_server 把 capabilities 的 URL 读入 settings）。跨 app 不强制同一实现（属应用层）。

**lint 可拦截性**：⚠️ 弱。env 直读合法场景多（脚本/CLI/沙箱），通用 lint 噪声大；建议以"评审关：新增配置读取须过 app config 模块"替代，或对 federation 局部 grep 基线。

**定性**：**债 + 承重混合**。federation/exhibition 裸读属债，但根因是"缺集中 config"（架构补齐），非"同一逻辑抄多遍"的典型散点。**优先级低于 DUP-1/2/3**，建议单列后续评估，勿混入本轮。

### DUP-5 SSE 打包（已收敛，正例）

`packages/shared-schemas/shared_schemas/sse.py:13 sse_pack` 为**单一实现**。`agent_server/api/query_router.py:385 _sse` → `sse_pack(event_name, payload)`；`scripts/opencode_gateway.py:67 _sse` → `sse_pack("", data)`；`knowledge_service/utils/sse_utils.py:6,72,95` → `_sse_pack(...)`。本地 `_sse` 均为**有意的薄适配层**（绑 event 名/签名），非重复实现。**无需动作**；作为"方法论有效"的反证写入 §3。

### DUP-6 LLM 客户端构造（门面已建，采用不齐——既有追踪，非新债）

kernel 门面 `agent_core.llm.get_llm_client` + `registry`（LRU + `_hash_api_key`）+ `providers.ChatOpenAI`（唯一构造点）。已迁移：`knowledge_service/lm/lm_utils.py`（shim 委托 kernel）。**仍绕过**：`agent_server/agent/llm.py:21-22`（直接 `ChatOpenAI` primary+fallback）、`nl2sql_service/agent/llm.py:49 build_llm()`、`exhibition/skill_loader/llm_client.py LLMClient`、`agent_federation/agent/llm.py`（env 驱动自建）。

**定性**：**承重-在途**——AGENTS.md「技术债追踪」已**显式登记**"llm_client 散落…按 `agent_core.llm` 统一门面处理（**非新增任务**）"。本清单**不重复登记为新债**，仅标注归属既有追踪。

### DUP-7 重试 / 熔断（引擎已收敛，残留手写循环 + 并行选型）

**收敛正例**：`agent_core.resilience`（`retry`/`retry_async`/`CircuitBreaker` 单引擎 + 策略）· `agent_runtime.circuit_breaker`（async 适配）· `skills/middleware`（`CircuitBreakerMiddleware`/`RetryMiddleware`）；`agent_federation/agent/circuit_breaker.py:3` 自陈"复用 agent_core.resilience.CircuitBreaker"。

**散点负例**：手写 HTTP 重试循环——`agent_core/memory/embedder.py:64 _http_post_json`（**在 kernel 内部**，`for attempt in range(retries+1)` + `time.sleep`）、`knowledge_service/lm/siliconflow_client.py:40`、`knowledge_service/api/import_router.py:234`、`exhibition/client/warehouse_client.py:176`；另 `agent_federation/tools/*.py` 用 **tenacity**（`@retry`）为并行第三选型。

**实现差异**：kernel retry（指数退避、装饰器）vs 手写 for+sleep（分散阈值/退避常量）vs tenacity（三方）。

**目标 kernel**：`agent_core.resilience.retry`/`retry_async`。手写 HTTP 循环（embedder/siliconflow/import_router）可归并；warehouse_client 含契约特定 `Retry-After` 解析 = **承重**保留；tenacity 属 federation 既有选型 = **待评估**（非本轮新债）。

**lint 可拦截性**：中。可 lint"禁裸 `for attempt in range(` + `sleep` 手写退避"引导用 `retry`，但需白名单合法并发探测。

**定性**：embedder/siliconflow/import_router 手写重试 = **纯债**；warehouse_client = **承重**；tenacity = 既有追踪。

### DUP-8 限流滑动窗口（已收敛，正例）

`agent_core.guardrails.ratelimit.SlidingWindowRateLimiter` 单实现；`agent_runtime.admission:21,42-44` 复用；`knowledge_service/utils/inbound_rate_limit_utils.py` + `rate_limit_utils.py` 均为重导出 shim（docstring 明写"过渡期保留，稳定后改指 kernel"）。**无需动作**。注意：DUP-1 中 `guardrails/auth.py:46` 的限流桶 key 与 fingerprint 收敛相关，一并处理。

### DUP-9 缓存 key 生成（大体已收敛，1 处半承重）

`agent_core.cache.base.build_cache_key`（`sha256(intent|query|kb_versions|tenant|gray)`）为语义缓存键单一实现（CHANGELOG TB-4 记录上收）；`agent_runtime/cache.py` 对齐。**例外**：`agent_federation/agent/main_agent.py:356` 角色缓存 `sha256(sorted(role_specs))` 本地化——含 role_specs 维度，属角色动态 Agent 专用，**半承重**；`registry._hash_api_key` 归 DUP-1。

---

## 3. 根因定性（为什么项目里还会存在这类重复）

**结论：三者叠加，但主因是「第③层强制门禁对『横向重复』维度完全空白」+「收敛依赖人工立项」，而非原则本身缺位。**

### 3.1 证据链

1. **门禁维度错配（主因）**：`scripts/lint_architecture.py` 现有 3 条不变量——`registry.execute()` 越权、裸 `FastAPI(`、workspace 顶层包名冲突——**全是"禁止某危险调用点"式检测，无一条是"某横切能力须经 kernel 唯一实现"式检测**。api_key 指纹散点**不是危险调用、而是重复**，根本不在扫描维度内，故 lint 从未可能拦住它。

2. **反证——凡立项上收的横切都收敛得很干净**：`sse_pack`（DUP-5）、`build_cache_key`（DUP-9）、`SlidingWindowRateLimiter`（DUP-8）、`resilience` retry/breaker（DUP-7 引擎侧）、`get_llm_client`（DUP-6 门面侧）、kernel `error_body`（DUP-2 canonical 侧）——**这些"单一实现+全局装配"一旦做了就被广泛复用**，证明 AGENTS.md 三层方法论**本身有效**，问题不是原则错。

3. **散点分布与"是否立项"强相关，与"逻辑难度"无关**：没人为 api_key 指纹建 kernel helper（DUP-1 连第①层"单一实现"都缺——kernel 只有语义不同的 `resolve_client_key`/`_hash_api_key`，没有可复用的 `fingerprint`）、error_body 上提了却没删源副本（DUP-2 半成品）、env 从未在 federation 建集中 config（DUP-4）——**恰好是没被点名的点成了散点**。

4. **并行演进放大器（双应用无收敛关）**：`agent_server`（pydantic settings + `secrets.compare_digest`）与 `agent_federation`（模块级 `os.getenv`、standalone 服务）两套独立长大的应用各写 `resolve_thread_id`。federation docstring 明写"对齐 app/api/auth.py 已验证策略"——**知道有兄弟实现，却选择复制而非共享**：因为 kernel `guardrails/auth.resolve_client_key` 的语义是"限流桶 full sha256"，不匹配"会话 id `[:12]`"需求，于是**宁拷不改 kernel 扩参**。缺"新增横切实现前须先查 kernel 是否已有 / 能否参数化"的强制评审关。

### 3.2 对 AGENTS.md 三层的映射

| 层 | 状态 | 说明 |
|---|---|---|
| ① 单一实现（收敛到 kernel） | **点依赖** | 立过项的点齐备；api_key 指纹从未建 kernel helper（缺第①层） |
| ② 全局装配（工厂/门面/中间件） | **基本到位** | sse_pack/get_llm_client/middleware 有装配；但缺"构造保证不可漏接"的强制点（app 仍各写 auth） |
| ③ 强制门禁（不变量 lint） | **对横向重复全空白** | 3 条 lint 全是危险调用检测，无"同类逻辑多实现"检测 → 无兜底，靠自觉，破窗 |

### 3.3 修复方向（2026-10-01：第 1、2 条已随 Batch 2/3/4 实施，余下仍为登记）

- ✅ **随 CodeQL Batch 2 落 `fingerprint` 时同步补第③层（已做）**：`lint_architecture.py` 新增 **P6**——同一行出现弱哈希调用 + `api_key|apikey|secret|password|access_key|private_key` 语义标识即失败，全仓扫描，白名单仅 kernel 单一实现文件；`hmac.new(secret, msg, hashlib.sha256)` 不命中（无紧跟 `(`），`md5(user_id)` 灰度桶不含密钥语义名——三层已补全到 DUP-1 这一点。
- **把"横切重复"作为 lint 的一类新维度**（已开三例，继续扩容）：P6 只覆盖"裸哈希"一种危险模式；**CodeQL Batch 3（2026-10-01）已落 P7**——用户可控路径的 containment / 文件名净化收敛到 kernel `guardrails/fs`，P7-1 禁白名单外手写 `is_relative_to`，P7-2 要求 api 层文件 I/O 出口必调 `safe_join`/`resolve_within`（同类散点虽在同一文件内，但性质与 DUP-1 一致：私有写法无法被工具/人认定为统一 sanitizer）；**CodeQL Batch 4（2026-10-01）已落 P8**——HTTP/SSE 出口回显异常消息/堆栈（`str(e)`、f-string 插值 `{e}`、`traceback.*`）即失败，单一实现为 kernel `guardrails/errors.mask_exception_for_client`，P8 的白名单**故意置空**（与 P6/P7 "白名单只放单一实现"不同：本不变量不允许未说理的例外）。error_body 符号唯一性 / env 集中入口仍未进门禁。纯语义检测成本高，可先用"符号唯一性"（canonical 定义仅允许出现在 kernel）+ 危险模式（P6/P7/P8）双路径。
- **评审关前移**（待落实）：AGENTS.md 增补"新增任何鉴权/错误/限流/哈希/配置读取实现前，须先 grep kernel 是否已有或可参数化复用"，把 federation 那次"知情复制"变成"必须共享"。

---

## 4. 后续排期建议（仅清单，本轮不动码）

| 优先级 | 条目 | 建议批次 | 理由 |
|---|---|---|---|
| P0 | DUP-1（+DUP-3） | CodeQL **Batch 2** | ✅ **已落地（2026-10-01）**：kernel `fingerprint`/`derive_thread_id` + 4 站点收敛 + P6 门禁 + 会话迁移脚本 |
| P1 | DUP-2 | 独立小 PR | 低风险、纯删重；可即刻，与 Batch 2 并行 |
| P2 | DUP-7（手写 HTTP 重试归并） | 单列后续 | 需逐处判定退避语义，勿与 security Batch 混 |
| P3 | DUP-4（env 集中入口） | 单列架构评估 | 面大、涉各 app 部署边界，非"同一逻辑抄多遍"典型 |
| 观察 | DUP-6 / DUP-8 / DUP-9 / DUP-5 | 归既有追踪/无需动作 | 门面已建且在收敛，勿重复登记 |

> **红线复申**：本文件为**只记录**产物。DUP-1/2 之外的收敛须各自"先方案后编码"；承重项（warehouse_client 重试、gray md5 分桶、各 standalone 服务配置边界）**保留不并**，勿为压重复数强拆。
