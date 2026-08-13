"""LLM 客户端：对齐 langchain-openai>=0.3，复用 app/agent/llm.py 风格。

主备模型 + 可复位降级（连续失败计数 + 冷却窗口）。
"""

import logging
import time

from dialogue_framework.shared.config import get_settings

logger = logging.getLogger(__name__)


class FallbackChatModel:
    def __init__(self, primary, fallback, failure_threshold: int = 3, cooldown: float = 60.0):
        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._consecutive_failures = 0
        self._cooldown_until = 0.0

    @property
    def degraded(self) -> bool:
        return self._consecutive_failures >= self.failure_threshold

    async def ainvoke(self, *args, **kwargs):
        if self.degraded and time.monotonic() < self._cooldown_until:
            return await self.fallback.ainvoke(*args, **kwargs)
        try:
            result = await self.primary.ainvoke(*args, **kwargs)
        except Exception:  # noqa: BLE001 降级语义
            self._consecutive_failures += 1
            if self.degraded:
                self._cooldown_until = time.monotonic() + self.cooldown
            logger.warning("主模型调用失败（连续 %d 次），降级备模型", self._consecutive_failures)
            return await self.fallback.ainvoke(*args, **kwargs)
        self._consecutive_failures = 0
        return result

    def with_structured_output(self, schema):
        return self.primary.with_structured_output(schema)


def build_chat_model() -> FallbackChatModel | None:
    """LLM_API_KEY 未配置时返回 None（走启发式/模板模式）。"""
    settings = get_settings()
    if not settings.llm_enabled:
        return None
    from langchain_openai import ChatOpenAI

    common = {
        "api_key": settings.llm_api_key,
        "base_url": settings.llm_base_url,
        "temperature": 0,
        "timeout": settings.llm_timeout,
    }
    primary = ChatOpenAI(model=settings.llm_model, **common)
    fallback = ChatOpenAI(model=settings.llm_fallback_model, **common)
    return FallbackChatModel(primary, fallback)
