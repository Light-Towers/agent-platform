import logging
import os

from dotenv import find_dotenv, load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk
from langchain_core.messages import BaseMessage
from typing import Any, Iterator

from pydantic import ConfigDict

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
    """构建单个模型实例（通过临时环境变量注入）。"""
    if not api_key or not base_url:
        _logger.warning("%s 模型缺少 API_KEY 或 BASE_URL，跳过", label)
        return None

    # 临时覆盖环境变量，确保 init_chat_model 读到正确值
    import os as _os
    prev_key = _os.environ.get("OPENAI_API_KEY")
    prev_url = _os.environ.get("OPENAI_BASE_URL")
    try:
        _os.environ["OPENAI_API_KEY"] = api_key
        _os.environ["OPENAI_BASE_URL"] = base_url
        return init_chat_model(
            model=model_name,
            model_provider="openai",
        )
    finally:
        if prev_key is not None:
            _os.environ["OPENAI_API_KEY"] = prev_key
        else:
            _os.environ.pop("OPENAI_API_KEY", None)
        if prev_url is not None:
            _os.environ["OPENAI_BASE_URL"] = prev_url
        else:
            _os.environ.pop("OPENAI_BASE_URL", None)


class _FallbackModel(BaseChatModel):
    """带 fallback 的模型代理：主模型异常时自动切到备用模型。

    继承 BaseChatModel 以满足 deepagents 的 isinstance 检查。

    用法：
        model = create_fallback_model()  # 返回 _FallbackModel 或直接返回主模型
        result = model.invoke(...)  # 透明代理
    """

    model_name: str = "fallback-model"
    primary_failed: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def __init__(self, primary, fallback, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_primary", primary)
        object.__setattr__(self, "_fallback", fallback)

    @property
    def _current(self):
        return self._fallback if self.primary_failed else self._primary

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = self._current.invoke(messages, stop=stop, **kwargs)
        if isinstance(result, BaseMessage):
            return ChatResult(generations=[ChatGeneration(message=result)])
        return result

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = await self._current.ainvoke(messages, stop=stop, **kwargs)
        if isinstance(result, BaseMessage):
            return ChatResult(generations=[ChatGeneration(message=result)])
        return result

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for chunk in self._current.stream(messages, stop=stop, **kwargs):
            yield chunk

    def invoke(self, *args, **kwargs):
        if self.primary_failed:
            return self._fallback.invoke(*args, **kwargs)
        try:
            return self._primary.invoke(*args, **kwargs)
        except Exception as e:
            if self._fallback is not None:
                _logger.warning("主模型 (%s) 调用失败，切换到备用模型: %s", _PRIMARY_MODEL, e)
                object.__setattr__(self, "primary_failed", True)
                return self._fallback.invoke(*args, **kwargs)
            raise

    async def ainvoke(self, *args, **kwargs):
        if self.primary_failed:
            return await self._fallback.ainvoke(*args, **kwargs)
        try:
            return await self._primary.ainvoke(*args, **kwargs)
        except Exception as e:
            if self._fallback is not None:
                _logger.warning("主模型 (%s) 调用失败，切换到备用模型: %s", _PRIMARY_MODEL, e)
                object.__setattr__(self, "primary_failed", True)
                return await self._fallback.ainvoke(*args, **kwargs)
            raise

    def stream(self, *args, **kwargs):
        """流式调用 — 如果主模型失败，fallback 用非流式（简化实现）。"""
        if not self.primary_failed:
            try:
                yield from self._primary.stream(*args, **kwargs)
                return
            except Exception as e:
                if self._fallback is not None:
                    _logger.warning("主模型 (%s) 流式调用失败，切换到备用模型: %s", _PRIMARY_MODEL, e)
                    object.__setattr__(self, "primary_failed", True)
                else:
                    raise
        result = self._fallback.invoke(*args, **kwargs)
        yield result

    async def astream(self, *args, **kwargs):
        """异步流式调用。"""
        if not self.primary_failed:
            try:
                async for chunk in self._primary.astream(*args, **kwargs):
                    yield chunk
                return
            except Exception as e:
                if self._fallback is not None:
                    _logger.warning("主模型 (%s) 异步流式调用失败，切换到备用模型: %s", _PRIMARY_MODEL, e)
                    object.__setattr__(self, "primary_failed", True)
                else:
                    raise
        result = await self._fallback.ainvoke(*args, **kwargs)
        yield result

    def bind_tools(self, *args, **kwargs):
        """代理 bind_tools 到当前活跃模型。"""
        return self._current.bind_tools(*args, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "fallback_model"

    @property
    def _identifying_params(self) -> dict:
        return {"primary": str(self._primary), "fallback": str(self._fallback)}

    def __repr__(self):
        current = self._fallback if self.primary_failed else self._primary
        return f"FallbackModel(active={current!r})"


def create_fallback_model():
    """创建带主备路由的模型实例。

    如果配置了备用模型（LLM_QWEN_FALLBACK），返回 _FallbackModel；
    否则直接返回主模型实例。

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
        return _FallbackModel(primary, fallback)

    _logger.info("模型: %s（无备用）", primary_model)
    return primary


# 模块级单例
model = create_fallback_model()
