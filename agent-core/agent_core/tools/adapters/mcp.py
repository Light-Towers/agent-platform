# -*- coding: utf-8 -*-
"""
MCP 工具适配器（框架无关内核，源自 zhiku node_web_search_mcp）。

参数化 MCP（SSE）远程工具调用：``MCPServerSse`` 连接配置 / ``tool_name`` / ``arguments``
均由构造参数注入；去除 ``app.utils.task_utils`` 硬依赖（改为可选注入 ``on_start`` /
``on_done`` 回调），去除 ``bailian`` 硬编码（工具名 / 参数 / 解析由调用方决定）。

需要 openai-agents（``tools-mcp`` extra）；``agents.mcp.MCPServerSse`` 懒导入。
"""

import asyncio
import json
from typing import Any, Callable, Dict, Optional

from agent_core.logging import get_logger

logger = get_logger(__name__)

State = Dict[str, Any]


def _default_query_extractor(state: State) -> str:
    """默认 query 提取：rewritten_query 优先，回退 original_query。"""
    return state.get("rewritten_query") or state.get("original_query") or ""


def _default_arguments_builder(query: str, state: State) -> Dict[str, Any]:
    """默认参数构造：``{"query": query}``（宿主可覆盖以加 count 等）。"""
    return {"query": query}


class MCPToolAdapter:
    """MCP（SSE）远程工具适配器；实现 Tool 协议（``name`` + ``invoke(state)``）。"""

    def __init__(
        self,
        *,
        name: str,
        mcp_url: str,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout_s: float = 3.0,
        sse_read_timeout: Optional[float] = None,
        tool_name: str,
        arguments: Optional[Callable[[str, State], Dict[str, Any]]] = None,
        query_extractor: Optional[Callable[[State], str]] = None,
        result_parser: Optional[Callable[[str], Any]] = None,
        on_start: Optional[Callable[[State], None]] = None,
        on_done: Optional[Callable[[State], None]] = None,
    ) -> None:
        self.name = name
        self.mcp_url = mcp_url
        self.api_key = api_key
        self._headers = headers
        self.timeout_s = timeout_s
        self.sse_read_timeout = sse_read_timeout if sse_read_timeout is not None else timeout_s
        self.tool_name = tool_name
        self._arguments_builder = arguments or _default_arguments_builder
        self._query_extractor = query_extractor or _default_query_extractor
        self._result_parser = result_parser or json.loads
        self._on_start = on_start
        self._on_done = on_done

    def _build_headers(self) -> Dict[str, str]:
        headers = dict(self._headers or {})
        if self.api_key:
            # 调用方已含 Authorization 时用其；否则注入。
            if "Authorization" not in headers:
                headers["Authorization"] = self.api_key
        return headers

    def invoke(self, state: State) -> Dict[str, Any]:
        """
        执行 MCP 工具调用，返回解析后的状态更新 dict；失败返回 {}。

        :param state: 上游状态
        :return: 解析结果 dict；查询为空 / 调用失败 / 解析失败 → {}
        """
        if self._on_start is not None:
            try:
                self._on_start(state)
            except Exception as e:  # noqa: BLE001 - 记账失败不影响主流程
                logger.warning("MCP on_start 失败: %s", e)

        query = self._query_extractor(state)
        if not query:
            logger.warning("MCP 查询词为空，跳过 %s", self.name)
            if self._on_done is not None:
                self._on_done(state)
            return {}

        try:
            # _call 是 async 流程，在同步 invoke 体内用 asyncio.run 包裹（已在
            # guarded 线程池子线程执行，无 running loop）；用 wait_for 施加超时，
            # 与 guarded 的超时语义保持一致。
            result = asyncio.run(asyncio.wait_for(self._call(query, state), timeout=self.timeout_s))
        except Exception as e:  # noqa: BLE001
            logger.error("MCP 适配器调用异常 %s: %s", self.name, e)
            result = None

        if self._on_done is not None:
            try:
                self._on_done(state)
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP on_done 失败: %s", e)

        if result is None:
            return {}
        return result

    async def _call(self, query: str, state: State) -> Optional[Dict[str, Any]]:
        # agents.mcp 为可选依赖：懒导入。
        try:
            from agents.mcp import MCPServerSse
        except Exception as e:  # pragma: no cover - 依赖缺失路径
            raise ImportError(
                "openai-agents 未安装；请安装 agent-core[tools-mcp]（uv sync --extra tools-mcp）"
            ) from e

        args = self._arguments_builder(query, state)
        search_mcp = MCPServerSse(
            name=self.name,
            params={
                "url": self.mcp_url,
                "headers": self._build_headers(),
                "timeout": self.timeout_s,
                "sse_read_timeout": self.sse_read_timeout,
            },
        )
        try:
            await search_mcp.connect()
            raw_result = await search_mcp.call_tool(tool_name=self.tool_name, arguments=args)
            if raw_result is None or getattr(raw_result, "isError", False):
                logger.error("MCP 返回错误 %s: %s", self.name, raw_result)
                return None
            if not getattr(raw_result, "content", None):
                logger.warning("MCP 返回内容为空 %s", self.name)
                return None
            raw_text = raw_result.content[0].text
            try:
                return self._result_parser(raw_text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("MCP 结果解析失败 %s: %s", self.name, e)
                return None
        except Exception as e:  # noqa: BLE001
            logger.error("MCP 调用过程异常 %s: %s", self.name, e, exc_info=True)
            return None
        finally:
            try:
                await search_mcp.cleanup()
            except Exception:  # pragma: no cover - 防御：清理失败不影响返回
                pass


__all__ = ["MCPToolAdapter", "_default_query_extractor", "_default_arguments_builder"]
