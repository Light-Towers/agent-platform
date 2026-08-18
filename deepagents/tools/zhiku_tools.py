import os

import httpx
from langchain_core.tools import tool
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from api.monitor import monitor
from tools._timeout import with_timeout

try:
    from agent_core.logging import get_logger
    _zhiku_logger = get_logger(__name__)
except ImportError:
    import logging
    _zhiku_logger = logging.getLogger(__name__)

try:
    from agent_core.tracing import start_span as _start_span
except ImportError:
    from contextlib import contextmanager as _contextmanager
    @_contextmanager
    def _start_span(*a, **kw):
        yield None

ZHIKU_API_URL = os.getenv("ZHIKU_API_URL", "http://localhost:8900")
ZHIKU_API_KEY = os.getenv("ZHIKU_API_KEY", "")

_TIMEOUT_S = 10.0

# 可重试：网络超时 / 连接错误；不可重试：HTTP 4xx（含 429 限流）
_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError)


# ---------------------------------------------------------------------------
# 健康探活（在服务启动时调用，不阻塞请求路径）
# ---------------------------------------------------------------------------
_zhiku_healthy: bool | None = None  # None=未探测, True=健康, False=不健康


def check_zhiku_health() -> bool:
    """检查 zhiku 知识库服务是否可达。

    在 lifespan 中调用一次，后续通过 is_zhiku_healthy() 获取缓存结果。
    不抛异常，所有错误静默处理。
    """
    global _zhiku_healthy
    url = f"{ZHIKU_API_URL.rstrip('/')}/health"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            if resp.status_code < 500:
                _zhiku_healthy = True
                _zhiku_logger.info("zhiku 健康探活成功 (%s)", url)
                return True
            _zhiku_healthy = False
            _zhiku_logger.warning("zhiku 健康探活失败 HTTP %d (%s)", resp.status_code, url)
            return False
    except Exception as e:
        _zhiku_healthy = False
        _zhiku_logger.warning("zhiku 健康探活异常: %s", e)
        return False


def is_zhiku_healthy() -> bool:
    """返回 zhiku 当前健康状态（不触发探测，只读缓存）。

    如果尚未探测过（None），视为健康（乐观假设），避免首次调用时阻塞。
    """
    if _zhiku_healthy is None:
        return True  # 未探测时乐观假设健康
    return _zhiku_healthy


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def _zhiku_post(url: str, payload: dict, headers: dict) -> httpx.Response:
    """带重试的知识库 HTTP POST（仅网络超时/连接错误重试，4xx 不重试）。"""
    with httpx.Client(timeout=_TIMEOUT_S) as client:
        return client.post(url, json=payload, headers=headers)


@tool
@with_timeout(timeout=20)
def zhiku_retrieve(query: str, item_name: str = "") -> str:
    """
    从企业知识库检索与问题相关的专业知识。
    :param query: 检索问题（自然语言）
    :param item_name: 可选，按知识条目名称过滤（留空则全库检索）
    :return: 检索到的相关文档内容摘要
    """
    monitor.report_tool(tool_name="知识库检索工具：zhiku_retrieve", args={"query": query, "item_name": item_name})

    # 降级：zhiku 不健康时直接返回提示，避免无效等待
    if not is_zhiku_healthy():
        monitor.report_tool_outcome(tool_name="zhiku_retrieve", outcome="degraded", detail="服务不健康")
        return "知识库服务暂不可用（已探测到不健康），请使用其他工具获取信息。如为紧急问题，可尝试网络搜索。"

    with _start_span("tool.zhiku_retrieve", attrs={"query": query}):
        url = f"{ZHIKU_API_URL.rstrip('/')}/api/v1/retrieve"
        headers = {"Content-Type": "application/json"}
        if ZHIKU_API_KEY:
            headers["Authorization"] = f"Bearer {ZHIKU_API_KEY}"

        payload = {"query": query}
        if item_name:
            payload["item_name"] = item_name

        try:
            resp = _zhiku_post(url, payload, headers)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "unknown")
                monitor.report_tool_outcome(
                    tool_name="zhiku_retrieve", outcome="degraded", error_class="HTTP429",
                    detail=f"Retry-After: {retry_after}s")
                return f"知识库检索被限流（429），请稍后重试（Retry-After: {retry_after}s）"
            resp.raise_for_status()
            data = resp.json()

            docs = data.get("docs", [])
            hits = data.get("hits", 0)
            if not docs:
                monitor.report_tool_outcome(tool_name="zhiku_retrieve", outcome="empty", detail=f"query: {query}")
                return f"知识库未检索到相关内容（query: {query}）"

            parts = [f"检索到 {hits} 条相关结果："]
            for i, doc in enumerate(docs[:5], 1):
                content = doc.get("content", doc.get("text", str(doc)))
                score = doc.get("score", "")
                score_str = f" (相关度: {score:.3f})" if isinstance(score, (int, float)) else ""
                parts.append(f"[{i}]{score_str} {content[:500]}")
            return "\n".join(parts)

        except httpx.TimeoutException:
            monitor.report_tool_outcome(
                tool_name="zhiku_retrieve", outcome="timeout", error_class="httpx.TimeoutException")
            return f"知识库检索超时（{_TIMEOUT_S}s），服务可能暂时不可用"
        except httpx.HTTPStatusError as e:
            monitor.report_tool_outcome(
                tool_name="zhiku_retrieve", outcome="exception", error_class="HTTPStatusError",
                detail=f"HTTP {e.response.status_code}")
            return f"知识库检索失败（HTTP {e.response.status_code}）：{e.response.text[:200]}"
        except Exception as e:
            monitor.report_tool_outcome(
                tool_name="zhiku_retrieve", outcome="exception", error_class=type(e).__name__, detail=str(e))
            return f"知识库检索异常：{str(e)}"
