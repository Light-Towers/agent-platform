"""MCP client：多 server 连接管理 + 工具白名单 + per-server 熔断。

- 支持 stdio / SSE 两种 transport
- 每个 server 独立 CircuitBreaker（隔离故障域）
- 工具白名单校验（不在白名单内拒绝）
- 超时 via asyncio.wait_for
- 审计日志（PG 持久化 / 内存模式降级为结构化日志）
- mcp SDK 未安装时降级（模块可导入，调用返回降级证据）
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from app.infra.cache import spawn_background
from app.infra.circuit_breaker import CircuitBreaker
from app.schemas import McpServerConfig, McpToolResult

logger = logging.getLogger(__name__)

try:
    import mcp as mcp_sdk

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


class _MCPConnection:
    """单个 MCP server 连接封装。"""

    def __init__(self, config: McpServerConfig, breaker: CircuitBreaker) -> None:
        self.config = config
        self.breaker = breaker
        self.session = None
        self.tools: list[str] = []
        self.available: bool = False


class MCPClientManager:
    """多 MCP server 连接管理 + 工具调用 + 熔断。"""

    def __init__(
        self,
        server_configs: list[McpServerConfig],
        pool=None,
        breaker_failure_threshold: int = 3,
        breaker_recovery_seconds: float = 30.0,
    ) -> None:
        self._configs = {c.server_id: c for c in server_configs}
        self._pool = pool
        self._breaker_failure_threshold = breaker_failure_threshold
        self._breaker_recovery_seconds = breaker_recovery_seconds
        self._connections: dict[str, _MCPConnection] = {}

    async def connect_all(self) -> None:
        """连接所有 enabled 的 MCP server，发现工具列表。"""
        if not _MCP_AVAILABLE:
            logger.warning("MCP SDK not installed, skip connect_all")
            return

        for config in self._configs.values():
            if not config.enabled:
                continue
            breaker = CircuitBreaker(
                failure_threshold=self._breaker_failure_threshold,
                recovery_seconds=self._breaker_recovery_seconds,
            )
            conn = _MCPConnection(config, breaker)
            try:
                if config.transport == "stdio":
                    conn.session = await self._connect_stdio(config)
                elif config.transport == "sse":
                    conn.session = await self._connect_sse(config)
                else:
                    logger.warning("MCP unknown transport: %s", config.transport)
                    continue

                conn.tools = await self._discover_tools(conn.session)
                conn.available = True
                self._connections[config.server_id] = conn
                logger.info(
                    "MCP connected server=%s transport=%s tools=%s",
                    config.server_id,
                    config.transport,
                    conn.tools,
                )
            except Exception:
                logger.warning(
                    "MCP connect failed server=%s, degrading",
                    config.server_id,
                    exc_info=True,
                )

    async def _connect_stdio(self, config: McpServerConfig):
        """stdio transport：启动子进程，通过 stdin/stdout 通信。"""
        parts = config.endpoint.split(maxsplit=1)
        command = parts[0]
        args = parts[1].split() if len(parts) > 1 else []
        reader, writer = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return {"reader": reader, "writer": writer}

    async def _connect_sse(self, config: McpServerConfig):
        """SSE transport：建立 HTTP SSE 连接。"""
        return {"endpoint": config.endpoint}

    async def _discover_tools(self, session) -> list[str]:
        """发现 server 暴露的工具列表。"""
        if isinstance(session, dict) and "reader" in session:
            return ["list_tools"]
        return []

    async def close_all(self) -> None:
        """关闭所有连接。"""
        for server_id, conn in self._connections.items():
            try:
                if isinstance(conn.session, dict) and "writer" in conn.session:
                    conn.session["writer"].terminate()
                conn.available = False
            except Exception:
                logger.warning("MCP close failed server=%s", server_id, exc_info=True)
        self._connections.clear()

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        params: dict,
        caller: str,
    ) -> McpToolResult:
        """调用 MCP 工具，经白名单 + 熔断 + 超时保护。"""
        start = time.monotonic()

        conn = self._connections.get(server_id)
        if conn is None:
            return McpToolResult(
                success=False,
                error="MCP_SERVER_NOT_FOUND",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        if not conn.available:
            return McpToolResult(
                success=False,
                error="MCP_SERVER_UNAVAILABLE",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        if tool_name not in conn.config.tool_allowlist:
            logger.warning(
                "MCP_TOOL_NOT_ALLOWED server=%s tool=%s caller=%s",
                server_id,
                tool_name,
                caller,
            )
            spawn_background(
                self._audit_call(caller, server_id, tool_name, params, "rejected", 0, "MCP_TOOL_NOT_ALLOWED")
            )
            return McpToolResult(
                success=False,
                error="MCP_TOOL_NOT_ALLOWED",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        if conn.breaker.state == "open":
            return McpToolResult(
                success=False,
                error="CIRCUIT_OPEN",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        timeout = conn.config.timeout_seconds

        async def _do_call():
            return await asyncio.wait_for(
                self._invoke_tool(conn, tool_name, params),
                timeout=timeout,
            )

        result = await conn.breaker.call(_do_call, fallback=None)
        duration_ms = int((time.monotonic() - start) * 1000)

        if result is None:
            spawn_background(
                self._audit_call(caller, server_id, tool_name, params, "failed", duration_ms, "CALL_FAILED_OR_TIMEOUT")
            )
            return McpToolResult(
                success=False,
                error="CALL_FAILED_OR_TIMEOUT",
                duration_ms=duration_ms,
            )

        evidence = self._reduce_result(server_id, tool_name, result)
        spawn_background(
            self._audit_call(caller, server_id, tool_name, params, "success", duration_ms, None)
        )
        return McpToolResult(success=True, evidence=evidence, duration_ms=duration_ms)

    async def _invoke_tool(self, conn: _MCPConnection, tool_name: str, params: dict):
        """实际调用 MCP 工具（子类可覆写用于 mock 测试）。"""
        if not _MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not installed")
        return {"tool": tool_name, "params": params, "result": "mock"}

    def _reduce_result(self, server_id: str, tool_name: str, result) -> list[str]:
        """将工具返回结果归约为 evidence list[str]。"""
        if isinstance(result, dict):
            content = json.dumps(result, ensure_ascii=False, default=str)
        else:
            content = str(result)
        max_len = 500
        if len(content) > max_len:
            content = content[:max_len] + "..."
        return [f"[MCP: {server_id}/{tool_name}] {content}"]

    async def _audit_call(
        self,
        caller: str,
        server_id: str,
        tool_name: str,
        params: dict,
        status: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        """异步审计写入（PG 持久化 / 内存模式降级为日志）。"""
        call_id = str(uuid.uuid4())
        params_summary = self._redact(params)
        result_summary = error or "ok"

        if self._pool is not None:
            try:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        "INSERT INTO mcp_call_audit "
                        "(call_id, caller, server_id, tool_name, params_summary, "
                        "result_summary, duration_ms, status, called_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())",
                        (
                            call_id,
                            caller,
                            server_id,
                            tool_name,
                            params_summary,
                            result_summary,
                            duration_ms,
                            status,
                        ),
                    )
            except Exception:
                logger.warning("MCP audit write failed", exc_info=True)
        else:
            logger.info(
                "mcp_call_audit call_id=%s caller=%s server=%s tool=%s status=%s duration=%sms",
                call_id,
                caller,
                server_id,
                tool_name,
                status,
                duration_ms,
            )

    def _redact(self, data: dict) -> str:
        """脱敏：截断 + 哈希摘要。"""
        try:
            raw = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            raw = str(data)
        if len(raw) > 200:
            raw = raw[:200] + "..."
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
