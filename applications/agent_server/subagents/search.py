"""联网搜索子能力：Tavily；未配置密钥时返回明确提示而非静默空结果。

熔断边界已上提至 SkillRegistry 中间件链（CircuitBreakerMiddleware，
见 capabilities.build_registry）——本实现只负责"搜索"，Runtime 边界不再内嵌。
"""

import httpx

from agent_server.config import get_settings


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
    results = await _tavily_search(query)
    if not results:
        return ["联网搜索无结果"]
    return results
