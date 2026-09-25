# 方案：M1.1 异常分类（Execution HA 前置能力）

> 状态：**Proposed**
> 关联：§20 生产就绪收尾后的执行可靠性基座；用户评审结论「M1.1 现在做、控制范围、不做大型异常体系；M3 Phase 2 继续 deferred」
> 范围：**最小三分类层 + 执行层接入**（agent-core 内核 + agent-runtime 执行链）；不触碰 federation/zhanggui 应用层、不改 `retry_async` 签名行为

## 一、目标

把「记录异常」（M1 已做的 `logger.warning`）升级为「**异常驱动执行控制流**」：

- 新增最小分类层 `ErrorClass(RETRYABLE / RECOVERABLE / FATAL)` + `classify_exception(exc)`；
- 执行层（ExecutionGraph 节点、`GuardMiddleware`、`RetryMiddleware`）据分类决定 重试 / 降级 / 终止；
- **致命异常必须向上冒泡**（不降级成空结果、不吞成字符串继续跑）；
- 明确「重试边界」：transport（SDK）`1–2` < skill 级（`RetryMiddleware` 2） < 执行级业务重试（本方案 2），禁止无限叠加。

不做：大型 `AgentException` 继承树。仅 1 个 enum + 1 个函数 + 2 个显式标记异常。

## 二、现状盘点（已复用，不重复造）

- `agent_core.resilience`：`retry`/`retry_async`（默认 `exceptions=Exception`——全量重试，危险）、`timeout`、`CircuitBreaker`。
- `agent_runtime.skills.middleware`：**洋葱链**已落地——`RetryMiddleware`（默认**类名启发式** `_default_transient`）、`GuardMiddleware`（**绝不向上抛**，无条件降级 fallback）、`CircuitBreakerMiddleware`、`RateLimitMiddleware`、`AuditMiddleware`。
- transport 层已有短重试：`memory/embedder.py`（429/5xx/URLError）、`agent_server/rag/rerank.py`（同款）。
- 执行图 `planner/execution_graph.py:_run`：`except Exception → str(exc)`，节点级隔离，**无分类、Fatal 不冒泡**。
- **两个 `GuardMiddleware`**：① `agent_runtime.skills.middleware.GuardMiddleware`（skill 超时/降级洋葱层，本次改）；② `agent_federation.gateway.guard_middleware.GuardMiddleware`（输入护栏 PII/injection，**不碰**）。
- skill 链 `GuardMiddleware`/`RetryMiddleware` **未接入生产默认 registry**（仅测试用 `RetryMiddleware`），改动爆炸半径小。

## 三、设计

### 3.1 分类层（落 `agent_core.resilience.py`，零依赖内核）

- `ErrorClass(Enum)`: `RETRYABLE` / `RECOVERABLE` / `FATAL`
- `RetryableError(Exception)`：显式标记瞬态可重试
- `FatalError(Exception)`：显式标记致命不可恢复
- `classify_exception(exc) -> ErrorClass`，优先级：标记异常 > 类型白名单 > `status_code` 属性 > 类名启发式 > 默认
  - RETRYABLE：`asyncio.TimeoutError` / `ConnectionError` / `urllib.error.URLError` / `status_code in {429,500,502,503,504}` / 类名含 `RateLimit|Timeout|Transient|Unavailable|Retryable` / `RetryableError`
  - FATAL：`TypeError`/`ValueError`/`KeyError`/`AttributeError`/`AssertionError`/`ArithmeticError`/`RecursionError` / `FatalError`（编程错误与状态不一致）
  - 默认未知第三方异常 → `RECOVERABLE`（保守可用性；已知错误均已显式归类）

### 3.2 执行层接入（关键改动）

**`execution_graph._run` 节点错误分类**：

- 先解析 `input_refs`：上游不在 `graph.nodes` → **FATAL**（编程错误）；上游在图内但无结果（上游已失败）→ 本节点**降级跳过**（RECOVERABLE），不把依赖失败误判为 Fatal。
- 捕获执行异常后 `classify`：
  - RETRYABLE → **有限业务重试**（默认 +2 次，指数退避 0.2/0.4s；transport 短重试已在底层 SDK，不叠加）；重试耗尽 → 降级为节点 error 事件（继续，不致命）。
  - RECOVERABLE（含默认未知）→ error 事件 + 继续（现状行为，显式化）。
  - FATAL → yield error 事件（`error_class="fatal"`）并**终止整次执行**（不再跑后续层）。
- StreamEvent error payload 新增 `error_class` 字段（向后兼容，旧字段 `error/skill/layer/node` 保留）。

**`RetryMiddleware._default_transient`**：改为优先 `classify_exception(exc) is RETRYABLE`（保留现有类名启发式为内部规则之一，行为超集，不丢现有语义）。

**`GuardMiddleware`**：新增 `propagate_fatal: bool = True`；当捕获异常分类为 `FATAL` 时 **re-raise**，不再降级成空 fallback（编程错误必须冒泡）。爆炸半径小（未接入默认生产链）。

### 3.3 复用与边界（不改动）

- 不改 `retry_async` 签名/默认行为（全仓库调用方多），仅在其 docstring 补「`exceptions` 应收窄为 `RetryableError` 等可重试类型，避免全量重试」的指引。
- transport 层（embedder/rerank）既有短重试保持；本方案执行级重试明确位于其上、且 attempt 上限小，不叠加成 27 次。
- 两个标记异常供**新代码主动 raise**；旧 `except Exception` 点位不强制改写（Phase 2 另起方案逐个升级）。

## 四、影响面

| 文件 | 改动 |
|---|---|
| `packages/agent-core/agent_core/resilience.py` | +`ErrorClass`/`classify_exception`/`RetryableError`/`FatalError` + `retry_async` docstring 指引 |
| `packages/agent-runtime/agent_runtime/skills/middleware.py` | `RetryMiddleware._default_transient` 用 classifier；`GuardMiddleware.propagate_fatal` |
| `packages/agent-runtime/agent_runtime/planner/execution_graph.py` | `_run` 分类 + 业务重试 + 依赖跳过 + Fatal 终止；error 事件加 `error_class` |
| `packages/agent-core/tests/test_resilience.py` | +分类层单测 |
| `packages/agent-runtime/tests/test_execution_error_classification.py` | +执行层三分类单测 |
| `docs/plan-m11-exception-classification.md` | 本方案 |

**不触碰**：federation / zhanggui 应用层、M1 已落 warning 点位、两个 federation 输入护栏、db.py / durability / 其他生产模块。

## 五、迁移策略

- **Phase 1（本方案）**：内核分类层 + 执行链接入（ExecutionGraph / RetryMiddleware / GuardMiddleware）+ 单测。使「瞬态可重试、编程错误冒泡、未知降级」成为执行层默认行为。
- **Phase 2（另起方案，未含本方案）**：M1 的 10 个 warning 点位**逐个**升级——执行路径点位（rerank/router/main_agent/siliconflow_client 等）按 `classify` 结果改为重试/降级/raise；telemetry 点位（langfuse_adapter/path_utils/word_converter 等）显式声明为 RECOVERABLE 语义。zhanggui 按既有边界不动。

## 六、验收标准

1. `packages/agent-core/tests/test_resilience.py` 新增分类层用例全绿：`ConnectionError`/`asyncio.TimeoutError`/`RetryableError`/含 `status_code=503`/`类名含RateLimit` → RETRYABLE；`TypeError`/`ValueError`/`FatalError` → FATAL；未知 `Exception` → RECOVERABLE。
2. 新增 `test_execution_error_classification.py` 全绿：
   - 瞬态节点失败 1 次后成功 → 节点完成（无 error 事件，重试生效）；
   - `TypeError`（Fatal）→ 整次执行终止，后续节点不执行，error 事件 `error_class="fatal"`；
   - 未知异常 → error 事件 + 独立下游节点仍运行；
   - 上游失败 → 下游依赖节点降级跳过（error 事件 `error_class="recoverable"`），不误判 Fatal。
3. 既有 `test_middleware_durability.py` 中 `RetryMiddleware` 用例仍通过（分类器超集兼容）。
4. 全门禁通过：`pytest tests/`、`packages/*/tests`、`applications/agent_federation/tests/unit`、`eval/run_eval.py --fail-below 0.8`（12/12）、`ruff check .`、`scripts/lint_architecture.py`。

## 七、原则

- 试验证，不重构：`execution_graph` 仅扩展错误分支，不改变「节点级隔离」基础语义（仅 Fatal 升级为终止）。
- 最小闭环：先让「异常→分类→控制流」在 agent-core + agent-runtime 内自洽，作为 Execution HA / Durable Execution 的前置能力（HA 演练期发现需扩展再迭代）。
- 后续 Durable Execution 可自然复用：`classify` → RetryPolicy → Checkpoint → Resume/Fail。
