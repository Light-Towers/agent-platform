import os
from typing import Literal

import httpx
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tools._timeout import with_timeout

load_dotenv()

from api.monitor import monitor

try:
    from agent_core.tracing import start_span as _start_span
except ImportError:
    from contextlib import contextmanager as _contextmanager
    @_contextmanager
    def _start_span(*a, **kw):
        yield None


def _get_tavily_client():
    """延迟构造 Tavily 客户端，避免 import 期硬依赖 tavily SDK。"""
    from tavily import TavilyClient

    return TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# 可重试：网络超时 / 连接错误；不可重试：HTTP 4xx
_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError, requests.ConnectionError, requests.Timeout)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def _tavily_search(**kwargs):
    """带重试的 Tavily 调用（仅网络类错误重试，4xx/业务错误不重试）。"""
    return _get_tavily_client().search(**kwargs)


@tool
@with_timeout(timeout=20)
def internet_search(
        query: str,
        topic: Literal["news", "finance", "general"] = "general",
        max_results: int = 5,
        include_raw_content: bool = False
):
    """
    根据用户问题，进行网络信息搜索！
    注意：主要搜索公开的网络信息！如果指定查询数据库或者rag不能使用此工具！
    :param query: 用户的查询信息
    :param topic: 查询的类型
    :param max_results: 返回的最大条数
    :param include_raw_content: 是否返回原内容 False 精简 True 详细
    :return:
    """
    monitor.report_tool(tool_name="网络搜索工具",
                        args={"query": query, "topic": topic, "max_results": max_results,
                              "include_raw_content": include_raw_content})
    with _start_span("tool.tavily", attrs={"query": query, "topic": topic}):
        return _tavily_search(query=query, topic=topic,
                              max_results=max_results, include_raw_content=include_raw_content)














