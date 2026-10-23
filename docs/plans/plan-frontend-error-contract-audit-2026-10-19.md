# 前端 ↔ 后端错误契约对齐审计（#94）

- 日期：2026-10-19
- 来源：GitHub issue #94 / TODO §1 前端待办第 2 条
- 性质：**只读审计**（零代码改动）；产出 = P2 统一异常处理器 D-2/D-4 拍板的输入 + 将来前端工程的对接基线

## 1. 现状契约清单（2026-10-19 实取，命令可复跑）

### 1.1 HTTP 错误信封（按出口分层）

| 层 | 形状 | 覆盖面 | 位置（证据） |
|---|---|---|---|
| **kernel 统一 5xx** | `{"code", "msg", "request_id"}` + `x-trace-id` header；异常消息/堆栈脱敏 | **全部 6 app**（P2 工厂强制） | `agent_core/guardrails/errors.py:76` `error_body()`；装配 `install_error_handlers` |
| **FastAPI 默认 4xx** | `{"detail": "<字符串>"}` | agent_server（约 50 处 `HTTPException`）、federation、ks | `FastAPI` 原生 `HTTPException` 行为 |
| **exhibition C1 专用** | `{"detail": {"code", "message"}}`（**dict detail**） | exhibition-agent 的 401/403/400 | `server.py:144-151` 四个 except 分支显式包 dict |
| **nl2sql /ready** | `{"status": "unhealthy", "pools": [...]}`（自定义 dict detail，503） | nl2sql-service（feat 分支） | `api/server.py:61` |

### 1.2 流式错误帧（SSE / WS）

| 出口 | 形状 | 证据 |
|---|---|---|
| agent_server SSE | `{"type": "error", "error": <mask_exception_for_client 脱敏串>}` | `api/query_router.py:330` |
| knowledge-service SSE | `{"type": "error", "error": <脱敏串>}`（经 `push_to_session(session_id, SSEEvent.ERROR, ...)`） | `api/query_router.py:169` |
| federation WS | `{"type": "error", "error": "Internal error: <异常类名>", "thread_id": ...}`——**只给类名不给消息**（比 SSE 两处更保守） | `api/server.py:395-399` |
| runtime StreamEvent | `{"type": "error", **event.payload}`——payload 形状随事件变 | `planner/protocol.py:772` |

### 1.3 状态码语义（exhibition C1 契约，唯一有成文语义的）

`contract/error_codes.py` 的 `ErrorCode` 枚举与 HTTP 状态码一一对应：`AUTH_CONTEXT_MISSING`/`AUTH_CONTEXT_INVALID`→401、`SCOPE_DENIED`→403、`REQUEST_CONTEXT_BROKEN`→400、`EGRESS_DENIED`/`KNOWLEDGE_NOT_PUBLISHED`/`METRIC_NOT_VERIFIED` 等。其余 app **无等价枚举**（4xx 用裸 `detail` 字符串）。

## 2. 发现的不一致（D-2/D-4 拍板要面对的面）

1. **同语义三形状**：服务器内部错误一处（5xx）有统一信封 `{code,msg,request_id}`；客户端错误（4xx）却有三种形状——裸字符串 `{detail}`（三家）/ dict `{detail:{code,message}}`（exhibition）/ 自定义 dict（nl2sql /ready）。
2. **`code` 字段缺位**：4xx 路径多数无机器可读错误码（exhibition 是唯一有 `ErrorCode` 枚举的）⇒ 前端要按**字符串匹配 message** 或按状态码猜，i18n/重构都脆弱。
3. **流式错误帧两种信息量**：SSE 两处给脱敏消息、federation WS 只给异常类名 ⇒ 前端"错误提示"文案质量取决于连哪个 app。
4. **`msg` vs `message` 用词分裂**：kernel 信封用 `msg`、exhibition dict detail 用 `message` ⇒ 统一时必改其一，**这是会打破前端的点**（TODO §1 原文的担忧正落在此）。
5. **未文档化**：ks / kefu / federation 的 4xx 契约无任何文档承诺（仅代码行为）；exhibition 的 C1 语义有 docstring 但无独立契约文档。

## 3. 对 D-2/D-4 拍板的输入建议（不预结论）

| 选项 | 影响面 | 备注 |
|---|---|---|
| **A：4xx 也统一到 `{code,msg,request_id}`** | 打破 exhibition 的 `{detail:{code,message}}`（dict detail 是 FastAPI 非标准用法）与三家的裸字符串 detail；**但当前无前端消费者**（仓内无前端工程，`chat.html` 用新字段名且只解析成功响应）⇒ **打破成本 ≈ 0，是收敛窗口期** | kernel 已有 `ErrorCode` 体系可复用为 `code` 值域 |
| **B：维持三形状，仅补文档** | 零打破；但把不一致留给未来前端 | 与 P2「统一异常处理」的初衷相悖 |
| **C：分层收敛**（5xx 已统一；4xx 统一为 `{code,msg}` 但保留 `detail` 键一段窗口） | 过渡期双键并存，前端可渐进 | 需要兼容层与弃用窗口（U-1 刚演示过兼容层的维护成本） |

**审计倾向（非拍板）**：**A**——「无前端消费者」是本次审计最关键的事实（6 个 app 全部无在仓前端；README CORS 里的 5173 是预留），现在不收敛，将来有前端时再改就是真打破。**`msg`/`message` 用词以 kernel 信封为准**（exhibition 的 dict detail 本就是非标准形态，随 D-2 一并换）。

## 4. 边界与不在本审计内的面

- nl2sql-service 的错误契约取自 feat 分支（`api/server.py`），合入 main 时需按本清单复核（其 `/ready` 的 dict detail 属自定义 503 语义，建议随 D-2 评估）；
- SSE/WS 帧的收敛属 D-4（流式面），本审计只给形状清单不给方案；
- 状态码语义表（哪些操作对应哪些码）超出错误形状范畴，属 API 设计评审。

## 5. 复跑命令

```bash
# kernel 信封
rg -n "def error_body" packages/agent-core/agent_core/guardrails/errors.py
# 4xx 三种形状
rg -c "HTTPException" applications/agent_server applications/agent_federation applications/knowledge-service --glob '*.py' -g '!tests/**'
rg -n 'detail=\{"code"' applications/exhibition-agent/exhibition_agent/server.py
# 流式帧
rg -n '"type": "error"' applications/agent_server/api/query_router.py applications/knowledge-service/knowledge_service/api/query_router.py applications/agent_federation/api/server.py packages/agent-runtime/agent_runtime/planner/protocol.py
```
