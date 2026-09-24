# Plan：MCP SDK 真实接入

> 状态：2026-09-22 制定并实施
> 前置：`mcp_client.py` 外围逻辑（连接管理 / 熔断 / 白名单 / 审计 / 超时）已完整，仅 `_invoke_tool` / `_discover_tools` / `_connect_*` 为 MVP 桩。

## 目标

将 `packages/agent-runtime/agent_runtime/mcp_client.py` 的 MVP 桩替换为真实 MCP SDK 调用，使 MCP 工具可经 stdio / SSE transport 真正连接、发现、调用。

## SDK 选型

- **`mcp` 官方 Python SDK**（modelcontextprotocol/python-sdk）— 已安装，`import mcp as mcp_sdk` 探测已就绪
- 不用 `openai-agents` 的 `agents.mcp`（那是应用层框架封装，agent-runtime 是中间件层不应依赖）

## API 映射

| 桩方法 | 真实实现 |
|--------|---------|
| `_connect_stdio` | `StdioServerParameters` + `stdio_client()` async ctx → `(read, write)` |
| `_connect_sse` | `sse_client(url)` async ctx → `(read, write)` |
| —（新增） | `ClientSession(read, write)` async ctx → `session`；`await session.initialize()` |
| `_discover_tools` | `await session.list_tools()` → `result.tools` → `[t.name for t in tools]` |
| `_invoke_tool` | `await session.call_tool(name, arguments)` → `CallToolResult` → 解析 `.content` |
| `close_all` | `await stack.aclose()` 关闭 transport + session 上下文 |

## 上下文生命周期管理

MCP SDK 的 `stdio_client` / `sse_client` / `ClientSession` 均为 async context manager。用 `AsyncExitStack` 统一管理：

```python
stack = AsyncExitStack()
read, write = await stack.enter_async_context(stdio_client(params))
session = await stack.enter_async_context(ClientSession(read, write))
await session.initialize()
# _MCPConnection._exit_stack = stack, _MCPConnection.session = session
```

`close_all` 中 `await conn._exit_stack.aclose()` 按 LIFO 顺序关闭 session → transport。

## _invoke_tool 返回值处理

`CallToolResult` 结构：
- `.content: list[TextContent | ImageContent | ...]` — 内容列表
- `.isError: bool` — 是否错误

解析为 `list[str]`（evidence 格式）：遍历 content，提取 `.text` 属性（TextContent），非文本内容用 `str()` 兜底。

## _reduce_result 更新

当前 `_reduce_result` 接收 `dict | any`，更新为也处理 `CallToolResult`：
- 若有 `isError=True` → raise RuntimeError（让熔断器计故障）
- 提取 content 列表为 `list[str]`
- 超长截断逻辑保留

## _MCPConnection 结构变更

```python
class _MCPConnection:
    config: McpServerConfig
    breaker: CircuitBreaker
    session: ClientSession | None     # 已初始化的 MCP 会话
    tools: list[str]                  # 发现的工具名列表
    available: bool                   # 是否可用
    _exit_stack: AsyncExitStack | None  # 上下文栈（transport + session）
```

## 降级策略

- `mcp` SDK 未安装（`_MCP_AVAILABLE=False`）→ `connect_all` 跳过，`call_tool` 返回 `MCP_SERVER_UNAVAILABLE`（已有逻辑保留）
- 连接失败 → `connect_all` 中 try/except 降级（已有逻辑保留）
- `_invoke_tool` 可被子类覆写用于 mock 测试（已有设计保留）

## 测试策略

- 现有 `test_mcp_skill.py` 8 例：手动注入 `_MCPConnection`，不经 `connect_all`，**不受影响**
- 新增 `test_mcp_client_real.py`：
  - `test_invoke_tool_without_sdk_raises` — `_MCP_AVAILABLE=False` 时 `_invoke_tool` raise
  - `test_reduce_result_handles_call_tool_result` — `_reduce_result` 处理 `CallToolResult` 类型
  - `test_reduce_result_handles_is_error` — `isError=True` 时 raise RuntimeError
  - `test_reduce_result_truncates_long_content` — 超长截断
  - `test_close_all_closes_exit_stack` — `close_all` 调用 `stack.aclose()`

## 影响面

- `packages/agent-runtime/agent_runtime/mcp_client.py` — 核心改动
- `packages/agent-runtime/pyproject.toml` — 添加 `mcp` 依赖（optional extra `mcp`）
- `packages/agent-runtime/tests/test_mcp_client_real.py` — 新增测试
- 无 breaking change：`call_tool` / `connect_all` / `close_all` 签名不变，`McpToolResult` 契约不变

## 验收标准

- [x] `_invoke_tool` 调用 `session.call_tool()` 而非返回 mock
- [x] `_discover_tools` 调用 `session.list_tools()` 而非返回 `["list_tools"]`
- [x] `_connect_stdio` / `_connect_sse` 建立真实 `ClientSession`
- [x] `close_all` 关闭 `AsyncExitStack`
- [x] 现有 8 例 MCP Skill 测试全绿
- [x] 新增 5 例 MCP client 测试全绿
- [x] ruff 0 error
- [x] 全量测试不回归
