import logging
import os

from agent_core.llm import LangChainFallbackModel
from dotenv import find_dotenv, load_dotenv
from langchain.chat_models import init_chat_model

# 加载配置文件
load_dotenv(find_dotenv())

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模型配置（支持主备路由 + 重试）
# ---------------------------------------------------------------------------
# 主模型：qwen-max（DashScope）
_PRIMARY_MODEL = os.getenv("LLM_QWEN_MAX", "qwen-max")
_PRIMARY_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
_PRIMARY_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 备用模型：qwen-plus（成本更低，主模型不可用时降级）
_FALLBACK_MODEL = os.getenv("LLM_QWEN_FALLBACK", "")
_FALLBACK_BASE_URL = os.getenv("OPENAI_FALLBACK_BASE_URL", _PRIMARY_BASE_URL)
_FALLBACK_API_KEY = os.getenv("OPENAI_FALLBACK_API_KEY", _PRIMARY_API_KEY)


def _build_model(model_name: str, base_url: str, api_key: str, label: str):
    """构建单个模型实例。

    直接通过 init_chat_model 的参数传入凭据，避免临时覆写全局环境变量
    （不再依赖 os.environ 读写，消除潜在的并发/可读性问题）。
    """
    if not api_key or not base_url:
        _logger.warning("%s 模型缺少 API_KEY 或 BASE_URL，跳过", label)
        return None

    return init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=api_key,
        base_url=base_url,
    )


def create_fallback_model():
    """创建带主备路由的模型实例。

    返回 ``LangChainFallbackModel``（BaseChatModel 子类，降级状态机由内核
    ``FallbackChatModel`` 统一实现），或仅主模型时返回主模型实例本身。

    每次调用重新读取环境变量（支持测试 monkeypatch）。
    """
    primary_model = os.getenv("LLM_QWEN_MAX", "qwen-max")
    primary_base = os.getenv("OPENAI_BASE_URL", "")
    primary_key = os.getenv("OPENAI_API_KEY", "")
    fallback_model = os.getenv("LLM_QWEN_FALLBACK", "")
    fallback_base = os.getenv("OPENAI_FALLBACK_BASE_URL", primary_base)
    fallback_key = os.getenv("OPENAI_FALLBACK_API_KEY", primary_key)

    primary = _build_model(primary_model, primary_base, primary_key, "主模型")
    if primary is None:
        raise RuntimeError("主模型配置缺失：请设置 OPENAI_API_KEY / OPENAI_BASE_URL")

    fallback = None
    if fallback_model:
        fallback = _build_model(fallback_model, fallback_base, fallback_key, "备用模型")

    if fallback is not None:
        _logger.info("模型路由: 主=%s, 备=%s", primary_model, fallback_model)
        return LangChainFallbackModel(primary=primary, fallback=fallback)

    _logger.info("模型: %s（无备用）", primary_model)
    return primary


# 模块级单例
model = create_fallback_model()
