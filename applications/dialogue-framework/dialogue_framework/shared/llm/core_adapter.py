"""LLM 内核适配：把 agent_core 的 BaseLLMProvider 桥接为 DF 运行时协议 BaseChatClient。

TB-1 闭环：dialogue-framework 的 ``BaseChatClient`` 是「运行时客户端」协议
（ainvoke / with_structured_output），而 agent_core 的 ``BaseLLMProvider`` 是
「工厂」协议（build -> client）。两者抽象层级不同，不应合并，而是互补。

本模块提供 ``LLMCoreClient``：用内核 ``BaseLLMProvider.build()`` 产出的 client 作为后端，
对外暴露 DF ``BaseChatClient`` 协议，使 DF 上层可直接消费内核 provider 而无需各自为政。

红线：不删除 / 合并 dialogue-framework 自有的 BaseChatClient，仅做协议对齐桥接。
"""
from typing import Any

from agent_core.llm.providers import BaseLLMProvider

from dialogue_framework.shared.llm.base_client import BaseChatClient


class LLMCoreClient(BaseChatClient):
    """将内核 BaseLLMProvider 产出的 client 适配为 DF 运行时协议。

    内核 build() 返回的对象（如 FallbackChatModel / ChatOpenAI）通常已自带
    ainvoke / with_structured_output，本类直接转发，保持零包装开销。
    """

    def __init__(self, provider: BaseLLMProvider, model: str | None = None, **kwargs: Any) -> None:
        self._provider = provider
        self._model = model
        self._kwargs = kwargs
        self._client = provider.build(model=model, **kwargs)

    @property
    def backend(self) -> Any:
        return self._client

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self._client, "ainvoke"):
            raise NotImplementedError(
                f"内核 provider 产出的 client {type(self._client).__name__} 不支持 ainvoke"
            )
        return await self._client.ainvoke(*args, **kwargs)

    def with_structured_output(self, schema: Any) -> "LLMCoreClient":
        if not hasattr(self._client, "with_structured_output"):
            raise NotImplementedError(
                f"内核 provider 产出的 client {type(self._client).__name__} 不支持 with_structured_output"
            )
        self._client = self._client.with_structured_output(schema)
        return self
