"""LLM 客户端：复用 agent_core.llm.fallback.FallbackChatModel + app 配置。"""

from agent_core.llm.fallback import FallbackChatModel

from agent_server.config import get_settings


def build_chat_model() -> FallbackChatModel | None:
    """LLM_API_KEY 未配置时返回 None（全链路走启发式/模板模式）。

    Langfuse LLM 观测在此单点装配（全局装配原则，2026-09-25 修复断线）：
    CallbackHandler 以构造参数挂到 primary/fallback 两个 ChatOpenAI 上——
    LangChain runnable 的构造期 callbacks 对该实例的所有调用路径生效
    （FallbackChatModel.invoke 直调 / LangChainFallbackModel.bind_tools 返回的
    primary runnable / BaseChatModel 回调机制），无需各调用点透传 config。
    凭据未配置时 get_langfuse_callbacks 返回空列表，行为与之前完全一致（opt-in）。
    """
    settings = get_settings()
    if not settings.llm_enabled:
        return None
    from agent_runtime.tracing import get_langfuse_callbacks
    from langchain_openai import ChatOpenAI

    common: dict = {
        "api_key": settings.llm_api_key,
        "base_url": settings.llm_base_url,
        "temperature": 0,
        "timeout": settings.llm_timeout,
    }
    langfuse_callbacks = get_langfuse_callbacks(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    if langfuse_callbacks:
        common["callbacks"] = langfuse_callbacks
    primary = ChatOpenAI(model=settings.llm_model, **common)
    fallback = ChatOpenAI(model=settings.llm_fallback_model, **common)
    return FallbackChatModel(primary, fallback)


def build_vl_model():
    """多模态 LLM 客户端（会话传图提问，plan-image-qa-fullstack §刀1）。

    **独立端点 VL_BASE_URL/VL_API_KEY**：硅基流动提供 Qwen3-VL-8B，agent_server 的
    LLM_BASE_URL(modelscope) 不提供该模型（实测 400 has no provider supported）。
    vl_model/vl_api_key 为空或 image_qa_enabled=false 时返回 None —— 调用方走文本降级。
    只在带图请求时使用；路由/压缩/记忆抽取仍走 build_chat_model 的文本 client。
    """
    settings = get_settings()
    if (
        not settings.image_qa_enabled
        or not settings.vl_model
        or not settings.vl_api_key
    ):
        return None
    from agent_runtime.tracing import get_langfuse_callbacks
    from langchain_openai import ChatOpenAI

    common: dict = {
        "api_key": settings.vl_api_key,
        "base_url": settings.vl_base_url,
        "model": settings.vl_model,
        "temperature": 0,
        "timeout": settings.llm_timeout,
    }
    callbacks = get_langfuse_callbacks(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    if callbacks:
        common["callbacks"] = callbacks
    return ChatOpenAI(**common)
