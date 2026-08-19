"""LLM 客户端基类协议（运行时协议）。

协议关系（TB-1）：本 ``BaseChatClient`` 是「运行时客户端」协议（ainvoke /
with_structured_output）；agent_core 的 ``BaseLLMProvider`` 是「工厂」协议
（build -> client）。两者抽象层级不同，不合并、互补。桥接见
``dialogue_framework.shared.llm.core_adapter.LLMCoreClient``：把内核 provider
build() 产出的 client 适配为本协议。
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseChatClient(Protocol):
    """LLM 对话客户端运行时协议。"""

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any: ...

    def with_structured_output(self, schema: Any) -> Any: ...
