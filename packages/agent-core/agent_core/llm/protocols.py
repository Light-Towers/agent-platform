# -*- coding: utf-8 -*-
"""ChatModel 协议（WS-8）：LLM 客户端的框架无关类型契约。

此前 ``FallbackChatModel`` 对主备模型是纯鸭子类型，降级组合无类型契约。
本协议定义内核认可的最小 ChatModel 接口（与 LangChain BaseChatModel 的
常用方法集结构兼容），供降级/重试/缓存等组合层做类型标注。

框架无关：仅 stdlib + typing。
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class ChatModel(Protocol):
    """最小 ChatModel 契约：同步/异步 invoke + 同步/异步 stream。

    方法签名采用宽松 ``*args/**kwargs``（与 LangChain / OpenAI 兼容客户端
    结构兼容）；``with_structured_output`` 可选（结构化输出场景）。
    """

    def invoke(self, *args: Any, **kwargs: Any) -> Any: ...

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any: ...

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]: ...

    def astream(self, *args: Any, **kwargs: Any) -> Any: ...


__all__ = ["ChatModel"]
