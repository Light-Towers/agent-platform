"""LLM 客户端：复用 agent_core.llm.fallback.FallbackChatModel + app 配置。"""

from agent_core.llm.fallback import FallbackChatModel

from app.config import get_settings


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
