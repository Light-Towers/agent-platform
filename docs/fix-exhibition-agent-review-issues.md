# 修复方案：exhibition-agent 代码评审问题

> 来源：2026-09-21 代码评审报告（applications/exhibition-agent 未提交改动）
> 状态：全部已实施（99 passed + 根 ruff All checks passed + lint_architecture P4-2 通过）
> 范围：首轮 5 项 + 二轮 9 项 Critical/Warning + 三轮 12 项遗留债务 = 26 项
> 全量门禁：根 559 passed + 联邦 92 + kefu 8 + exhibition 99 = 758 passed, 15 skipped

## 问题清单与根因

| # | 级别 | 问题 | 根因位置 |
| --- | --- | --- | --- |
| 1 | 🔴 Critical | STRICT 档鉴权可被 `X-Context-Mode: base64` 绕过验签 | `server.py:115` + `execution_context_middleware.py:127-128` |
| 2 | 🟡 Warning | 传输层异常未映射为契约错误；`retryable` 字段无消费方 | `warehouse_client.py:129-130` + `contract_errors.py` |
| 3 | 🟡 Warning | 10 个测试文件未纳入 `make ci` | `Makefile:25-28` + `pyproject.toml:62-65` |
| 4 | 🟢 Suggestion | `SkillResult.egress_decision` 被赋裸字符串 `"DENY"` | `venue_schedule_query.py:91` |
| 5 | 🟢 Suggestion | 文档口径漂移：README "7 场景" 实为 9；契约版本头文档写 1.0 实发 1.1 | `README.md:42` + 契约文档 `:65` |

---

## #1 Critical：STRICT 档 base64 绕过验签

### 目标
切断客户端对上下文解析模式的控制通道；STRICT 档下 base64（无签名）适配器不可用。使 INV-8（上下文不可伪造）在 STRICT 档真正成立。

### 当前代码事实
- `server.py:115`：`resolve_mode = x_context_mode or settings.context_mode` —— 客户端头 `X-Context-Mode` 可覆盖服务端配置。
- `execution_context_middleware.py:127-128`：base64 分支只做 `decode_base64(header_value)`，不接收/不校验 `verify_signature`。
- 攻击路径：STRICT 档下，攻击者发 `X-Context-Mode: base64` + 自造 base64 上下文 → 绕过 JWT 验签 → 任意伪造 `tenant_id`，通过全部 401/403/scope 校验。

### 修复
**a. `server.py`：模式只由服务端配置决定，删除 `x_context_mode` 参数**

```python
# 删除 x_context_mode 参数（切断客户端控制通道）
async def query(
    body: QueryBody,
    request: Request,
    x_execution_context: str | None = Header(default=None, alias="X-Execution-Context"),
    x_mock_scenario: str | None = Header(default=None, alias="X-Mock-Scenario"),
) -> JSONResponse:
    ctx_header = x_execution_context
    resolve_mode = settings.context_mode  # 服务端配置唯一决定
```

**b. `execution_context_middleware.py`：base64 分支在 STRICT 档（`verify_signature=True`）下禁用**

```python
elif mode == "base64":
    if verify_signature:
        raise AuthContextInvalidError("STRICT 档禁用无签名的 base64 上下文适配器")
    payload = decode_base64(header_value)
```

双保险：即使 a 被回退，b 仍能拦住 STRICT + base64 组合。

### 影响面
- `server.py`：`query` 函数签名删 1 个参数（`x_context_mode`）。无外部消费者（FastAPI 路由签名，非公共 API）。`WarehouseClient` 仍会在发往 warehouse 的请求里设 `X-Context-Mode` 头（`warehouse_client.py:111`），那是平台→warehouse 的传递，不受影响。
- `execution_context_middleware.py`：base64 分支新增 STRICT 守卫。
- 现有测试 `test_c1_execution_context.py::test_parse_base64_success` 用 `mode="base64"` 且默认 `verify_signature=False`（DEV 档），不受影响。
- `test_server.py` 无 `X-Context-Mode` 头测试，删除参数不破坏现有测试。

### 回归测试（新增）
加到 `tests/test_execution_mode.py`：
- `test_strict_mode_rejects_base64`：STRICT 档（`verify_signature=True`）+ `mode="base64"` → `AuthContextInvalidError`
- `test_dev_mode_allows_base64`：DEV 档 + `mode="base64"` → 放行（保证 DEV 仍可用）

加到 `tests/test_server.py`：
- `test_query_ignores_client_context_mode_header`：用 `httpx.ASGITransport` 打 `/api/query`，发 `X-Context-Mode: base64` 头 + JWT 上下文，断言行为按服务端 `settings.context_mode`（jwt）解析，客户端头被忽略。

### 验收标准
1. STRICT 档 + 任意 `X-Context-Mode` 头 + 自造 base64 上下文 → 401 `AUTH_CONTEXT_INVALID`
2. STRICT 档 + JWT 合法签名 → 放行
3. DEV 档 + base64 → 放行
4. 新增 3 个测试全绿

---

## #2 Warning：传输层异常未映射 + 重试未实现

### 目标
把 `httpx` 传输层异常（超时/连接/网络）映射为 `UpstreamError`，避免污染 C4 trace 错误码分桶；消除 `retryable` 字段的误导性。

### 当前代码事实
- `warehouse_client.py:129-130`：`await client.post(...)` 的 `httpx.TimeoutException` / `ConnectError` / `NetworkError` 未捕获，直穿到 `nodes.py:56` 的 `except Exception`。
- `nodes.py:59`：`error_code = getattr(exc, "code", type(exc).__name__)` → 对 `httpx.ConnectError` 写入 `"ConnectError"`，污染 trace.error_code（应为 `UPSTREAM_ERROR`）。
- `contract_errors.py`：`UpstreamError(retryable=True)` / `RateLimitedError(retryable=True)`，但全仓无一处读取 `.retryable`。
- 契约文档 `:170-171`：`RATE_LIMITED → 退避重试`、`UPSTREAM_ERROR → 重试/降级提示`（策略建议，非强制实现）。

### 修复
**a. `warehouse_client.py`：捕获传输层异常，映射为 `UpstreamError`**

```python
with span(...):
    try:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, base_url=self.base_url) as client:
            resp = await client.post(url, headers=headers, json=body)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
        raise UpstreamError(f"warehouse 传输层故障：{type(exc).__name__}: {exc}") from exc

return self._parse_response(resp, request_id)
```

**b. `contract_errors.py`：明确 `retryable` 语义，`WarehouseClient.invoke` 实现有界重试**

模块 docstring 追加：
```
retryable 为契约语义标记（指示错误是否可重试）。WarehouseClient.invoke 对
UpstreamError / RateLimitedError 做有界指数退避重试；其余 retryable=False 的异常
不重试。调用方需确保 skill 幂等（当前所有 skill 均为只读，重试安全）。
```

### 实现的最小重试
- **重试对象**：`UpstreamError`（传输层故障 + 上游 502）和 `RateLimitedError`（429）
- **参数**：`max_retries=3`（可配），指数退避 `retry_base_delay_ms * 2^attempt` + 10% 随机抖动
- **结构**：`invoke` 做重试循环，抽出 `_do_invoke` 做单次调用；传输层异常在 `_do_invoke` 内映射为 `UpstreamError`
- **幂等性**：`invoke` docstring 注明"调用方需确保 skill 幂等；当前所有 skill 均为只读，安全"

### 影响面
- `warehouse_client.py`：`invoke` 方法新增 try/except 包裹 httpx 调用。
- `contract_errors.py`：模块 docstring 追加说明。
- `nodes.py:59`：`getattr(exc, "code", ...)` 现在对 `UpstreamError` 能拿到 `exc.code`（`ErrorCode.UPSTREAM_ERROR`），trace.error_code 正确分桶。无需改 `nodes.py`。

### 回归测试（新增）
加到 `tests/test_c2_envelope_client.py`（或新建 `tests/test_warehouse_client_transport.py`）：
- `test_timeout_mapped_to_upstream_error`：用 `httpx.MockTransport` 抛 `httpx.TimeoutException`，断言抛 `UpstreamError` 且 `exc.code == ErrorCode.UPSTREAM_ERROR`
- `test_connect_error_mapped_to_upstream_error`：同上，`httpx.ConnectError`

### 验收标准
1. warehouse 超时/连接故障 → `UpstreamError`（非裸 `httpx.ConnectError`）
2. trace.error_code 记为 `UPSTREAM_ERROR`（非 `ConnectError`）
3. `retryable` 字段保留，docstring 明确重试语义
4. 重试：前 N-1 次失败 + 第 N 次成功 → 返回信封；全部失败 → 抛 `UpstreamError`
5. 新增 4 个测试全绿

---

## #3 Warning：测试未纳入 make ci

### 目标
exhibition-agent 的 10 个测试文件在 CI 中被执行，使 INV-10 回归真正可被拦截。

### 当前代码事实
- `Makefile:25-28`：`test` 目标只有根 pytest + `agent_federation/tests/unit` + `kefu-service/tests`。
- `pyproject.toml:62-65`：根 `testpaths` 只有 `tests` + `packages/agent-core/tests`。
- exhibition-agent README L57 宣称 `29 passed`，但 CI 不跑。

### 修复
**`Makefile` `test` 目标追加一行**（独立 pytest session，与 agent_federation/kefu 同理避免 conftest 插件名冲突）：

```makefile
test:
	uv run pytest -q
	uv run pytest applications/agent_federation/tests/unit -q
	uv run pytest applications/kefu-service/tests -q
	uv run pytest applications/exhibition-agent/tests -q
```

并在 `Makefile` 注释中补充说明 exhibition-agent 同样以独立 session 纳入。

### 影响面
- CI 多跑一个 pytest session（约 29 测试），耗时增加可忽略。
- 不改 `pyproject.toml` 根 `testpaths`（避免 conftest 冲突，与 agent_federation/kefu 一致策略）。

### 验收标准
1. `make test` 本地全绿（含 exhibition-agent 29 测试）
2. `make ci` 包含 exhibition-agent 测试

---

## #4 Suggestion：egress_decision 裸字符串

### 目标
`SkillResult.egress_decision` 字段类型为 `EgressDecision` 枚举，赋值用枚举而非裸字符串，避免下游 `.value` 调用 `AttributeError`。

### 当前代码事实
- `base_skill.py:36`：`egress_decision: EgressDecision = EgressDecision.ALLOW`（字段类型是枚举）。
- `venue_schedule_query.py:91`：`egress_decision="DENY"`（裸字符串）。
- `nodes.py` 当前不读 `result.egress_decision`（用 `route_model(result.classification).egress_decision`），故不崩。但下游一旦按枚举写 `.value` 即 `AttributeError`（`str` 无 `.value`）。

### 修复
**`venue_schedule_query.py`：改用枚举 + 补 import**

```python
from exhibition_agent.contract.envelope import DataClassification, EgressDecision, Readiness
...
egress_decision=EgressDecision.DENY,
```

### 影响面
- 仅 `venue_schedule_query.py` 一行 + import。
- `EgressDecision(str, Enum)`，`EgressDecision.DENY == "DENY"` 仍成立（str Enum），不破坏任何字符串比较。

### 回归测试（新增）
加到 `tests/test_skill_venue_schedule.py`：
- `test_egress_denied_result_uses_enum`：触发 `EgressDeniedError`，断言 `result.egress_decision == EgressDecision.DENY` 且 `result.egress_decision.value == "DENY"`

### 验收标准
1. `result.egress_decision` 是 `EgressDecision` 实例
2. `result.egress_decision.value == "DENY"` 不抛 `AttributeError`

---

## #5 Suggestion：文档口径漂移

### 目标
统一文档与代码的口径：mock 场景数、契约版本头。

### 当前代码事实
- `README.md:42`：`├── mock_server/           warehouse 契约假实现（7 场景）` —— 实际 9 场景（README L86/L107 已是 9）。
- 契约文档 `docs/architecture/cross-project-interface-contract.md:65`：`X-Contract-Version: 1.0（缺失按 1.0 处理）` —— 客户端实际发 `1.1`（`warehouse_client.py:36` `_CONTRACT_VERSION = "1.1"`）。

### 修复
- `README.md:42`：`7 场景` → `9 场景`
- `README.md:2`：`updated: 2026-09-20` → `updated: 2026-09-21`（frontmatter 同步更新）
- 契约文档 `:65`：`X-Contract-Version: 1.0（缺失按 1.0 处理）` → `X-Contract-Version: 1.1（缺失按 1.1 处理）`

### 影响面
- 纯文档，无代码行为变化。

### 验收标准
1. `grep -r "7 场景" applications/exhibition-agent/` 无结果
2. 契约文档版本头口径与 `warehouse_client.py` 一致（均 1.1）

---

## 总体验收清单

| 项 | 命令 |
| --- | --- |
| exhibition-agent 全测试 | `uv run pytest applications/exhibition-agent/tests -q` |
| 根 lint | `uv run --with ruff ruff check applications/exhibition-agent/` |
| make test | `make test`（含新 session） |

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `applications/exhibition-agent/exhibition_agent/server.py` | 删 `x_context_mode` 参数；`resolve_mode` 只用 `settings.context_mode` |
| `applications/exhibition-agent/exhibition_agent/middleware/execution_context_middleware.py` | base64 分支 STRICT 守卫 |
| `applications/exhibition-agent/exhibition_agent/client/warehouse_client.py` | 捕获传输层异常 → `UpstreamError` |
| `applications/exhibition-agent/exhibition_agent/client/contract_errors.py` | docstring 明确 retryable 语义 |
| `applications/exhibition-agent/exhibition_agent/skills/venue_schedule_query.py` | `egress_decision=EgressDecision.DENY` + import |
| `applications/exhibition-agent/README.md` | 7→9 场景 + frontmatter updated |
| `docs/architecture/cross-project-interface-contract.md` | 契约版本头 1.0→1.1 |
| `Makefile` | test 目标加 exhibition-agent session |
| `applications/exhibition-agent/tests/test_execution_mode.py` | +2 测试（STRICT 拒 base64 / DEV 允 base64） |
| `applications/exhibition-agent/tests/test_server.py` | +1 测试（客户端头被忽略） |
| `applications/exhibition-agent/tests/test_warehouse_client_transport.py`（新建） | +4 测试（超时/连接映射 + 重试成功/重试耗尽） |
| `applications/exhibition-agent/tests/test_skill_venue_schedule.py` | +1 测试（egress 枚举） |

## 迁移策略

- 全部改动向后兼容（无公共 API 破坏）。
- `server.py` 删 `x_context_mode` 参数：唯一消费者是 FastAPI 路由，无外部调用方。
- base64 STRICT 守卫：仅影响 STRICT + base64 组合（本就是漏洞路径），DEV + base64 不变。
- 分支建议：`feat/exhibition-agent-review-fixes`（kebab-case，符合分支命名规范）。

---

## 二轮修复：4 Critical + 5 Warning（9 项）

| # | 级别 | 问题 | 修复 |
| --- | --- | --- | --- |
| C1 | 🔴 | `execution_mode` 无校验，"OFF" 静默降级 | `config.py` 加 `field_validator`，非 STRICT/DEV 抛 ValueError |
| C2 | 🔴 | `inject_traceparent` 在 span 外，trace 链断裂 | 移入 `_do_invoke` span 内 + 重试循环内 |
| C3 | 🔴 | `get_current_traceparent` 在 span 退出后调用 | 移入 `with span(...)` 内赋值 |
| C4 | 🔴 | error 路径 `str(Enum)` ≠ `.value` | `hasattr(raw_code, "value")` 取 `.value`，`"error"` 记纯错误码 |
| W1 | 🟡 | `/api/query` 未传 `self_reported_tenant_id` | 补传 `body.params.get("tenant_id")` |
| W2 | 🟡 | retryable 错误吞成 200 通用文案 | 按 `_RETRYABLE_HTTP_STATUS` 映射返回 502/429 |
| W7 | 🟡 | STRICT 档 secret 运行时才报错 | `model_validator` 启动期 fail-fast |
| W8 | 🟡 | `user_query_hash=ctx.user_id` 语义不符 | 改为 `sha256(body.query)[:16]` |
| W9 | 🟡 | readiness_missing 误记合法 NOT_CONNECTED | 改在真实路径（`result.data["readiness_missing"]`）记录 |

## 三轮修复：12 项历史遗留债务

| # | 级别 | 问题 | 修复 |
| --- | --- | --- | --- |
| W5 | 🟡 | `LangSmithBackend` import `langchain` | 移除 langchain 依赖，降级 no-op + NotImplementedError |
| W4 | 🟡 | `/api/query` 端到端测试仅 401 | 补 200/403/INV-10 三个端到端用例 |
| S1 | 🟢 | `ExecutionContext` 同名冲突 | `contract/__init__.py` docstring 显式消歧 |
| S4 | 🟢 | `route_model` 仅事后记录 | `run_skill` 事前拦截 DENY → 拒绝展示 |
| S7 | 🟢 | `__all__` 未导出 `PENDING_ANSWER` | 补 import + `__all__` |
| S9 | 🟢 | 429 重试未尊重 `Retry-After` | `RateLimitedError.retry_after_ms` + 重试优先用 |
| S2 | 🟢 | README "29 passed" | → "99 passed" |
| S3 | 🟢 | mock_server "7 场景" | → "9 场景" |
| S5 | 🟢 | base_url 冗余 + `_parse_error` 返回类型 | url 改相对路径 + `NoReturn` |
| S8 | 🟢 | error 路径 model 硬编码 | 走 `route_model(DataClassification.INTERNAL)` |
| 噪音 | — | `ha_real_kill_verify.py` lint 误报 | docstring 改措辞 + f-string 修复 |
| 噪音 | — | `tests/ha` import 排序 + 未使用 | ruff --fix |

## 最终验收

| 门禁 | 结果 |
| --- | --- |
| 根 pytest | 559 passed, 15 skipped |
| 联邦 pytest | 92 passed |
| kefu pytest | 8 passed |
| exhibition-agent pytest | 99 passed |
| 根 ruff | All checks passed |
| lint_architecture | P4-2 通过 |
