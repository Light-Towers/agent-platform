# 错误契约对齐：审计结论与 D-2/D-4 收敛方案（2026-11-04）

- 状态：**Proposed（审计已完成；D-2/D-4 待拍板；零代码改动）**
- 基线：`feat/web-visual-poc` @ `8458651e`（2026-11-04 审计时 HEAD）
- 关系：本文**取代** `docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` 中已失效的读数；旧件保留作历史，不删。
- 关联：`docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md`（D-2/D-3/D-4 原始拍板）、`docs/TODO.md` 前端待办第 2 条、`web/src/api/errors.ts`。

## 0. 一句话结论

仓库实际有 **5 类错误形状**，`web/src/api/errors.ts` 只覆盖 A/B 两类。更关键的是：**B 并不覆盖所有 5xx**——`install_error_handlers` 只注册 `Exception`，显式 `HTTPException(5xx)` 仍走 A。因此 `D-2=A` 的准确含义是「只兜未捕获异常、其余冻结」，不是「错误契约已对齐」。

建议 **D-2 选双写过渡（D-2-3）**、**D-4 选统一流式帧 + 兼容别名（D-4-3）**：目标形状统一为 B，迁移窗口内旧键原样保留，状态码与成功响应体不动。

## 1. 范围、基线与非目标

**在范围内**

- 6 个应用的 8 个 FastAPI app 实例：`agent_server`、`agent_federation`、`kefu-service`、`nl2sql-service`、`knowledge-service`、`exhibition-agent`（`server.py` + `skill_loader/app.py` + mock warehouse）。
- 前端唯一收敛点：`web/src/api/errors.ts`（`describeError` / `describeStreamError`）及其 SSE 调用点 `web/src/api/sse.ts`。
- HTTP 非 2xx 响应体、显式 `HTTPException`、未捕获异常、422 校验、SSE/WS 错误帧。

**不在范围内**

- 外部消费者（网关、第三方客户端）的实际解析行为——本文只给兼容策略，不给外部审计结论。
- 状态码业务语义（哪个操作该返回 409 还是 503）、鉴权模型本身。
- WS 连接生命周期、SSE 重连协议；D-4 只统一错误帧 payload。

**方法**：读代码 + `git grep`，未发请求、未改代码。行号是基线 `8458651e` 的快照；复跑以 §10 命令为准。

## 2. 形状定义与现状矩阵

| 记号 | 形状 |
|---|---|
| **A** | `{"detail": string \| array}`（FastAPI 原生） |
| **B** | `{"code": string, "msg": string, "request_id": string}` |
| **C** | `{"detail": {"code": ..., "message": ...}}` |
| **D** | `{"error": string \| object}` |
| **E** | HTTP 非 2xx，但 body 是业务成功形状，错误码在顶层 `error_code` |
| **H** | 健康检查专用 body（`{"ok": false, "checks": ...}` 或 `{"detail": {"status","pools"}}`） |

| 服务 / 入口 | 非 2xx 实际形状 | 前端 `describeError` | 备注 |
|---|---|---|---|
| `agent_server` | A（字符串 / 422 数组；**显式 5xx 也是 A**）；未捕获 500 = B | ✅ | 3 个机器 token：`BUDGET_EXCEEDED`(429)、`CONCURRENCY_REJECTED`(409)、`SCHEDULER_SLOTS_EXHAUSTED`(503) |
| `agent_federation` | A（`HTTPException` + 手写 401）；SecurityGuards 的 401/413/429 = B；未捕获 500 = B | ⚠️ | 401 文案分叉：A 分支带「密钥未填或不正确」，B 分支不带 |
| `kefu-service` | A；未捕获 500 = B | ✅ | 无自定义错误体 |
| `nl2sql-service` | A；`/health` 503 的 `detail` 是 dict；未捕获 500 = B | ⚠️ | 健康检查 503 落兜底 |
| `knowledge-service` | **全部 B**（含 401/403/429/5xx）；校验失败是 **400 + B 字符串** | ⚠️ | 401 无「密钥」前缀；校验不是 422 数组 |
| `exhibition-agent` server | A（字符串 / 手工 422 字符串 / pydantic 422 数组）；C（auth 与显式 500 的 dict detail）；E（业务映射错误）；未捕获 500 = B | ❌ | C/E 落兜底 |
| `exhibition-agent` skill_loader | D（`{"error": ...}`）；pydantic 422 = A；未捕获 500 = B | ❌ | 无 `detail`/`msg` |
| `exhibition-agent` mock | D（`{"error": {"code","message","retryable"}}`） | — | 非生产入口，web 不连 |
| `shared_schemas.ErrorResponse` | `{"detail", "code"?, "request_id"?}`，不是 B；示例会双层嵌套 | — | 当前无使用点，见 §3.7 |

## 3. 关键发现

### 3.1 B 不是「全 5xx 信封」，而是「未捕获异常 + 部分中间件」

`packages/agent-core/agent_core/guardrails/errors.py` 只注册 `Exception` handler；显式 `raise HTTPException(status_code=500/502/503, detail=...)` 走 FastAPI 默认处理器，返回 A。因此：

- 未捕获异常 → 500 + B；
- 显式 503（如 `SCHEDULER_SLOTS_EXHAUSTED`、`meta 库未就绪`、`knowledge 未启用`）→ A；
- `SecurityGuardsMiddleware` 自带的 401/413/429 → B；
- 各 app 手写 `JSONResponse` → C/D/E。

旧审计「kernel 统一 5xx 覆盖全部 6 app」只对未捕获异常成立，不能作为「5xx 已统一」的证据。

### 3.2 `detail` 是异质容器，不是单一「语义码」

同一条 A 通道里至少有四种内容：

1. 机器 token：`agent_server` 的 `BUDGET_EXCEEDED` / `CONCURRENCY_REJECTED` / `SCHEDULER_SLOTS_EXHAUSTED`；
2. 人类可读文案：`API Key 无效`、`meta 库未就绪（META_DB_DSN 未配置？）`；
3. 422 校验数组：每项含 `loc`/`msg`/`input`；
4. dict：`exhibition` 的 `{"code","message"}`、`nl2sql` `/health` 的 `{"status","pools"}`。

所以 `docs/TODO.md` 里「`{detail}` 语义码是前端要解析的形状」只对第 1 类成立；不能据此设计一个统一的 `detail` 解析器。机器码应统一到 B 的 `code`，人类文案统一到 B 的 `msg`。

### 3.3 同一鉴权失败，文案分叉

`web/src/api/errors.ts` 的 A 分支对 401/403 加「密钥未填或不正确」前缀；B 分支只显示 `msg`。于是：

- `agent_server` 的 401（A）→ 带「密钥」提示；
- `agent_federation` 的 SecurityGuards 401（B）→ 不带；
- `knowledge-service` 的 401（B）→ 不带。

这不是前端 bug，是后端形状分裂直接映射到用户文案。

### 3.4 校验语义 400 / 422 分裂

- `knowledge-service` 的 `validation_exception_handler` 返回 **400** + B（`VALIDATION_ERROR` + 单条格式化文案）；
- 其余服务走 FastAPI 默认 **422** + A 数组；
- `exhibition-agent` 同时存在手工 `raise HTTPException(422, detail="字符串")` 和 pydantic 422 数组。

前端两种都能显示，但「字段校验失败」的结构化程度不同，跨服务文案不可比。

### 3.5 `request_id` 只在 B 里，A 通道日志关联弱

A 类 4xx 的 body 没有 `request_id`；`describeError` 也不读响应头 `X-Trace-Id`（`web/src/api/sse.ts` 只在流式路径读）。用户拿到 A 类 401/422 时，前端只能显示状态码和文案，无法给出可检索的 request id。

### 3.6 C/D/E 的兜底是安全的，但会丢信息

`web/src/api/errors.ts` 明确不为 C/D/E 加特例，落到「服务返回 HTTP xxx，响应体不是可解析的错误信封」。这不会崩、不会假装解析，但：

- `exhibition` 的 C 丢失 `code`/`message`；
- skill_loader 的 D 丢失 `error` 文案；
- `exhibition` 的 E 丢失 `error_code` 与业务上下文。

当前 web 只连 `agent_server`，所以这是范围约定而非线上缺陷；一旦直连 federation/exhibition，必须先补分支或先收敛后端。

### 3.7 `shared_schemas.ErrorResponse` 不是目标信封，且示例会双层嵌套

`packages/shared-schemas/shared_schemas/error.py` 的模型是 `{detail, code?, request_id?}`，没有 `msg`；它的用法示例是：

```python
raise HTTPException(
    status_code=429,
    detail=ErrorResponse(code="BUDGET_EXCEEDED", detail="请求额度已耗尽").to_dict(),
)
```

FastAPI 会把 `detail` 再包一层，实际 body 变成：

```json
{"detail": {"detail": "请求额度已耗尽", "code": "BUDGET_EXCEEDED"}}
```

这不是 A+B 兼容，而是 C 的变体。模型本身可作为「A + code + request_id」的过渡载体，但不能直接当 B 用。当前仓内无调用点，故未造成线上影响。

### 3.8 旧审计为什么仍被 TODO 记为「未做」

`docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` 的读数已漂移：

- 声称「kernel 统一 5xx 覆盖全部 6 app」——只对未捕获异常成立；
- 写 `nl2sql /ready`——现端点是 `/health`；
- 未覆盖 `exhibition skill_loader` 的 D、mock 的 D/E、`ErrorResponse` 的双层嵌套陷阱；
- 未覆盖显式 5xx 仍走 A 这一关键事实。

所以 TODO 保持开项是合理的；本文是替代审计，不是重复登记。

## 4. 目标契约（建议）

### 4.1 HTTP 非 2xx

```json
{
  "code": "BUDGET_EXCEEDED",
  "msg": "请求额度已耗尽",
  "request_id": "req-...",
  "detail": "请求额度已耗尽",
  "errors": [
    {"loc": ["body", "query"], "msg": "字段长度超限"}
  ]
}
```

规则：

- `code`：稳定机器码；优先保留 app 自己的业务码（如 `BUDGET_EXCEEDED`、`AUTH_CONTEXT_MISSING`），没有则按状态码映射（`UNAUTHORIZED` / `FORBIDDEN` / `VALIDATION_ERROR` / `INTERNAL_ERROR` 等）。
- `msg`：人类可读、已脱敏；4xx 只透传安全文案，5xx 一律通用文案；不出现堆栈、内部路径、密钥、`input` 原文。
- `request_id`：所有非 2xx 都带；来源 `request.state.request_id` 或 OTel 上下文。
- `detail`：**仅兼容窗口存在**，新客户端不读；A 类原样字符串，C 类原样 dict，D 类原样 `error`。
- `errors`：**仅校验错误**，可选；每项只保留 `loc` + `msg`，**不转发 `input`**（PII/原文）。
- 状态码不变：401/403/404/409/422/429/500/503 保持现有语义；`knowledge-service` 的校验 400 在窗口内保留，只统一 `code` 为 `VALIDATION_ERROR`。

### 4.2 流式错误帧

```json
{
  "type": "error",
  "code": "INTERNAL_ERROR",
  "msg": "服务器内部错误，请稍后重试",
  "request_id": "req-...",
  "error": "服务器内部错误，请稍后重试"
}
```

规则：

- `error` 是兼容别名，值必须等于 `msg`；旧前端 `describeStreamError` 会先读 `error`，因此零改动可显示。
- `msg` 是目标键，与 HTTP 的 B 信封同词，避免 `msg`/`message` 再分裂。
- 不再向客户端输出异常类名；`Internal error: <ClassName>` 只进服务端日志。
- `done` 帧语义不变；error 后仍发 done，前端已有的「error→done 抑制」逻辑不动。

## 5. D-2 迁移方案

> 命名刻意用数字，避免与 P2 的 `D-2=A`、旧审计的「A 方案」再次同名异义。

| 选项 | 做法 | 破坏面 | 结论 |
|---|---|---|---|
| **D-2-1 现状冻结** | 保留 A/B 分裂，只补文档 | 零 | 不接受为「已对齐」；只能作为回退位 |
| **D-2-2 全量切换** | 一次性把所有 HTTP 错误改成纯 B，删除 `detail` | 高：C/D/E 消费者、外部客户端 | 不推荐 |
| **D-2-3 双写过渡（推荐）** | 内核统一加 B 键；旧 `detail`/`error` 原样保留一个窗口；状态码与成功体不动 | 低 | 推荐 |

### 5.1 D-2-3 的落地顺序

1. **kernel 能力**：在 `packages/agent-core/agent_core/guardrails/errors.py` 增加 `StarletteHTTPException` 与 `RequestValidationError` 处理器，受 `normalize_http_errors` 开关控制，默认关；保留现有 `Exception → 500` 行为。
2. **agent_server 试点**：`build_api_app(..., normalize_http_errors=True)`，覆盖 401/409/422/429/500/503 与 SSE；用 `web/src/api/errors.ts` 的行为件验证 B 分支。
3. **其余工厂 app**：`agent_federation`、`kefu-service`、`nl2sql-service`、`exhibition-agent` 两个入口逐个打开；`knowledge-service` 仍用自有 handler（D-3），只加一致性测试。
4. **特殊形状适配**：
   - C：把 `detail.code` 提升为 B `code`，`detail.message` 提升为 B `msg`，`detail` 原样保留；
   - D：把 `error` 字符串作为 `msg`，`code` 按状态码映射，`error` 原样保留；
   - E：在业务 body 上**追加** `code/msg/request_id`，不替换 `error_code` 与其他字段；
   - H：健康检查保留专用 body，不强行改成 B；若要参与错误展示，另开适配项。
5. **翻默认**：所有 in-repo 消费者迁移完成后再把 `normalize_http_errors` 默认设为 True；窗口结束删除旧键。
6. **schema**：新增 `ErrorEnvelope`（`code,msg,request_id,errors?`）到 `shared-schemas`；`ErrorResponse` 保留但修正示例（不要塞进 `HTTPException.detail`），标注 deprecated。

### 5.2 兼容窗口

- 窗口内响应同时含 B 键与旧键；旧客户端读旧键，新客户端读 B。
- 窗口长度由「外部消费者清点完成」决定，不按日历拍；没有清点结果就不删旧键。
- 回退开关按 app 粒度（环境变量或装配参数），回退只影响新增 B 键，不影响成功响应。

## 6. D-4 迁移方案

| 选项 | 做法 | 破坏面 | 结论 |
|---|---|---|---|
| **D-4-1 现状** | 各出口各自为政 | 零 | 前端已兼容，但信息量不同 |
| **D-4-2 纯新帧** | 只发 `code/msg/request_id` | 中：旧前端/WS 客户端 | 不推荐 |
| **D-4-3 双写（推荐）** | `error` 别名 + 新键；生产者统一走一个 helper | 低 | 推荐 |

### 6.1 D-4-3 的落地顺序

1. 在 `agent-core` 增加纯函数 `stream_error_frame(code, msg, request_id, legacy_error=True)`，不依赖 starlette/SSE。
2. `agent_server` SSE、`knowledge-service` SSE、`agent_federation` WS、`serialize_stream_event` 的 error 分支统一调用该函数。
3. `web/src/api/sse.ts` 无需改动即可显示（`error` 别名）；可选增强：优先读 `msg`，并把帧内 `request_id` 用于日志提示。
4. 窗口结束后删除 `error` 别名；`describeStreamError` 的 `STREAM_TEXT_KEYS` 保留 `msg`/`message` 兼容。

## 7. 测试与验收

**kernel 单测**（`packages/agent-core/tests/test_guardrails_errors.py` 扩展）

- 4xx 字符串 / 422 数组 / 显式 5xx / 未捕获 500 四种路径都断言 B 键 + `request_id` + 旧键保留；
- C/D/E 三种特殊形状映射后 `code`/`msg` 正确，旧键原样；
- 422 输出不含 `input`，5xx 不含堆栈/路径/密钥；
- `normalize_http_errors=False` 时行为与现状逐字一致（防回归）。

**app smoke**

- 每个 app 至少覆盖 401、403、422、429、500、503 的代表性端点；
- `agent_server` SSE + `knowledge-service` SSE + federation WS 各一条错误帧断言；
- `knowledge-service` 保持 400 + B，不被 kernel 默认 handler 改写。

**web 行为**

- `describeError` 对 A/B/C/D/E 五种 body 都不抛异常；C/D/E 可显示业务文案或明确兜底；
- 422 永不渲染 `input`；
- `describeStreamError` 对 `error`/`msg`/`message` 三种键都能显示，且优先 `msg`（如实现增强）。

**验收判据**

1. 6 个应用的所有非 2xx HTTP 响应都含 `code`、`msg`、`request_id`；窗口内旧键同时存在。
2. 同一语义（401/403/422/429/500/503）跨应用 `code` 一致，鉴权 401 文案不再分叉。
3. 流式错误帧统一含 `code`/`msg`/`request_id`，旧前端零改动可显示。
4. 成功响应体与状态码零变化；`knowledge-service` 的 D-3 对外形状不被破坏。
5. 无堆栈、内部路径、密钥、PII（尤其 422 的 `input`）上屏。
6. `ruff`、`check_doc_sync.py`、受影响 pytest session、`make ci-web`（若改 web）全绿。

## 8. 风险与回退

| 风险 | 处置 |
|---|---|
| 外部客户端只认 `detail`/`error` | 双写窗口 + 按 app 开关；先清点再删旧键 |
| C 的 dict detail 被扁平化后丢失结构 | `detail` 原样保留，B 键只做增量 |
| E 的业务 body 被误改成错误信封 | 只追加 B 键，不替换 `error_code`/业务字段 |
| 422 从数组变字符串导致前端字段级展示退化 | 保留可选 `errors` 数组（已脱敏） |
| KS 400 与其它 422 不一致 | 窗口内保留状态码，只统一 `code`；状态码统一另案 |
| 流式帧双写导致前端显示重复 | `error` 与 `msg` 同值，前端只取一个；测试断言 |
| 开关默认值切换导致全量行为变化 | 先默认关、逐 app 开、最后翻默认；每步可回退 |

## 9. 待拍板清单

- **D-2**：选 D-2-1 / D-2-2 / **D-2-3（推荐）**。
- **D-4**：选 D-4-1 / D-4-2 / **D-4-3（推荐）**。
- **D-2.1 校验状态码**：`knowledge-service` 的 400 是否在窗口内保留（推荐保留，只统一 `code`）。
- **D-2.2 校验结构**：是否增加可选 `errors` 数组（推荐增加，且不含 `input`）。
- **D-2.3 兼容窗口**：以「外部消费者清点完成」为退出条件，还是固定一个发布周期（推荐前者）。
- **D-3 边界**：`knowledge-service` 继续使用 `install_handlers=False` + 自有 B handler，不改对外形状（推荐）。
- **shared schema**：新增 `ErrorEnvelope`、`ErrorResponse` 标注 deprecated（推荐），还是直接改 `ErrorResponse`（影响面更大）。

拍板前不写代码；拍板后按 §5.1 / §6.1 分阶段落地，每阶段独立可回退。

## 10. 复跑命令

```bash
# 1. 当前只兜未捕获异常，显式 HTTPException 仍是 A
git grep -n "def install_error_handlers" -- packages/agent-core
git grep -n "app.add_exception_handler" -- packages/agent-core
git grep -n "HTTPException" -- applications

# 2. 显式 5xx 与 dict detail
git grep -n "status_code=5" -- applications
git grep -n "detail={" -- applications

# 3. C / D / E 特殊形状
git grep -n 'detail={"code"' -- applications/exhibition-agent
git grep -n '"error"' -- applications/exhibition-agent/exhibition_agent/skill_loader/app.py
git grep -n "error_code" -- applications/exhibition-agent/exhibition_agent/server.py

# 4. B 信封与知识库校验 400
git grep -n "error_body\|error_response" -- packages/agent-core applications/knowledge-service
git grep -n "VALIDATION_ERROR" -- applications/knowledge-service

# 5. 流式错误帧
git grep -n "serialize_stream_event" -- packages/agent-runtime applications/agent_federation
git grep -n "type.*error\|Internal error" -- applications/agent_server/api/query_router.py applications/knowledge-service/knowledge_service/api/query_router.py applications/agent_federation/api/server.py

# 6. 前端收敛点
git grep -n "describeError\|describeStreamError\|X-Trace-Id" -- web/src/api
```

## 11. 证据边界

- 本文没有运行端到端请求；矩阵来自代码路径与异常处理器注册关系，不是线上抓包。
- 外部消费者行为未知；所有「零破坏」结论仅指仓内消费者与双写窗口内的旧键兼容。
- 行号会漂移；引用时优先用函数名/路径，复跑用 §10 命令。
- 本文不替代 `docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md` 的历史拍板记录；它只更新其 D-2/D-4 的**当前事实基础**与迁移选项。
