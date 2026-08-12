"""LLM 客户端：主备模型 + 可复位降级标志。

修复 deepagents 评审中发现的缺陷模式：降级标志只置位不复位会导致
主模型恢复后仍永久走备模型。这里改为"连续失败计数 + 冷却窗口"：
- 主模型连续失败达阈值 -> 切备模型并记录冷却截止时间；
- 冷却到期 -> 下一次请求先试探主模型，成功则复位计数；
- 任何一次主模型成功都会复位失败计数（可复位）。
"""

import logging
import time

from app.config import get_settings

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
        self._consecutive_failures = 0  # 成功即复位
        return result

    def with_structured_output(self, schema):
        """路由等结构化场景直接用主模型；失败由调用方回退启发式。"""
        return self.primary.with_structured_output(schema)


def build_chat_model() -> FallbackChatModel | None:
    """LLM_API_KEY 未配置时返回 None（全链路走启发式/模板模式）。"""
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
