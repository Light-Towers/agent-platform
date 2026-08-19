"""联网搜索子能力：Tavily；未配置密钥时返回明确提示而非静默空结果。"""

import httpx
from agent_runtime.circuit_breaker import CircuitBreaker

from agent_server.config import get_settings

_breaker: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        settings = get_settings()
        _breaker = CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold,
            recovery_seconds=settings.breaker_recovery_seconds,
        )
    return _breaker


async def _tavily_search(query: str) -> list[str]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": settings.search_api_key, "query": query, "max_results": 5},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    return [f"{r.get('title', '')} | {r.get('content', '')} | {r.get('url', '')}" for r in results]


async def search_web(query: str) -> list[str]:
    settings = get_settings()
    if not settings.search_api_key:
        return ["联网搜索未配置（SEARCH_API_KEY 为空）"]
    breaker = get_breaker()
    results = await breaker.call(lambda: _tavily_search(query), fallback=None)
    if results is None:
        return ["联网搜索暂时不可用（熔断或请求失败）"]
    if not results:
        return ["联网搜索无结果"]
    return results
