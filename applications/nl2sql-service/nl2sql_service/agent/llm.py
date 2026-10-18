"""LLM 客户端：经 agent_core.llm.OpenAICompatibleProvider 构造 ChatOpenAI 实例。

2026-10-18（S-5 修复）：`llm_timeout` 此前解析入 settings 但 invoke 不消费
——LLM 挂起会无限期持有 HTTP 请求。现 invoke 整体包 `asyncio.wait_for`，
超时按既有降级语义返回空串（不抛给图，由上层按 error 处理）。
"""

import asyncio
from typing import Any

from agent_core.llm.providers import OpenAICompatibleProvider
from agent_core.logging import get_logger

logger = get_logger(__name__)

_provider = OpenAICompatibleProvider()


class LLMClient:
    """LLM 客户端封装：薄壳复用 agent_core.llm.OpenAICompatibleProvider。"""

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = "", timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._llm = None

    def _ensure_llm(self) -> Any:
        if self._llm is None:
            self._llm = _provider.build(
                model=self._model,
                api_key=self._api_key,
                base_url=self._base_url or None,
            )
        return self._llm

    async def invoke(self, prompt: str) -> str:
        if not self._api_key:
            return ""
        try:
            return await asyncio.wait_for(self._invoke(prompt), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("LLM invoke timed out after %.1fs", self._timeout)
            return ""
        except Exception:
            logger.exception("LLM invoke failed")
            return ""

    async def _invoke(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        llm = self._ensure_llm()
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        return result.content.strip()

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)


def build_llm() -> LLMClient:
    from nl2sql_service.conf.settings import get_settings

    s = get_settings()
    return LLMClient(
        api_key=s.llm_api_key,
        model=s.llm_model,
        base_url=s.llm_base_url,
        timeout=s.llm_timeout,
    )
