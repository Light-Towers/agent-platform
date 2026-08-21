# -*- coding: utf-8 -*-
"""FallbackChatModel 的 LangChain 兼容适配（可选）。

提供 `LangChainFallbackModel`：复用 `FallbackChatModel` 的降级语义
（连续失败计数 + 冷却窗口 + 成功复位），同时继承 `langchain_core` 的
`BaseChatModel`，以满足 `deepagents` 等框架对 `isinstance(BaseChatModel)`
的检查。

设计约束：
- 本模块只有在用户启用 `langchain` extra（已装 langchain-core）时才会被导入；
  其他 agent_core 内核模块绝不 import 本模块，故内核零依赖契约不受影响。
- `LangChainFallbackModel` 在类定义时即直接继承 `BaseChatModel`（非运行时
  `__class__` 篡改），避免 C 扩展 layout 冲突。
- 采用**组合**：持有一个 `FallbackChatModel` 实例 `_core` 作为降级状态机的
  单一真相源，所有 invocation 委托给它最活跃的模型。不复制/改写内核降级逻辑，
  避免与 `agent_core.llm.fallback` 版本产生语义漂移。
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_core.llm.fallback import FallbackChatModel


# 各模型上下文窗口（tokens），用于向 deepagents 的 SummarizationMiddleware 暴露
# max_input_tokens，使其按「模型窗口比例」自适应触发（而非硬编码 170K）。
# 留约 2K 余量给系统提示与工具调用开销。
_MODEL_MAX_INPUT_TOKENS: dict[str, int] = {
    "qwen-max": 30_000,        # 官方 32768，留余量
    "qwen-plus": 120_000,      # 官方 131072
    "qwen-turbo": 120_000,     # 官方 131072
    "qwen-long": 1_000_000,    # 官方 1000000（长文档）
    "qwen2.5-72b-instruct": 120_000,
    "deepseek-chat": 60_000,
    "deepseek-v3": 60_000,
    "gpt-4o": 120_000,
    "gpt-4o-mini": 120_000,
}


def _resolve_max_input_tokens(primary_model_name: str | None) -> int:
    """解析主模型的输入窗口上限（tokens）。

    优先级：``LLM_MAX_INPUT_TOKENS`` 环境变量 > 已知模型表 > 默认 30K 兜底。
    该值经 ``LangChainFallbackModel.profile`` 暴露给 deepagents，驱动
    SummarizationMiddleware 以「窗口比例（0.85 trigger / 0.10 keep）」触发，
    从而在小窗口模型（如 qwen-max 32K）上真正生效（见 P2.1）。
    """
    env_val = os.getenv("LLM_MAX_INPUT_TOKENS")
    if env_val and env_val.isdigit():
        return int(env_val)
    if primary_model_name:
        for key, val in _MODEL_MAX_INPUT_TOKENS.items():
            if primary_model_name.startswith(key):
                return val
    return 30_000


class LangChainFallbackModel(BaseChatModel):
    """``BaseChatModel`` 兼容外壳，内部委托 ``FallbackChatModel`` 做主备降级。

    降级策略（阈值/冷却/复位）全部来自内核 ``FallbackChatModel``，本类仅做
    LangChain 接口适配与任意模型对象的转发。
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any,
        failure_threshold: int = 3,
        cooldown: float = 60.0,
        on_usage: Any = None,
        **kwargs: Any,
    ) -> None:
        # pydantic BaseChatModel 初始化（无业务字段）。
        super().__init__(**kwargs)
        # 内核降级状态机：单一真相源。
        object.__setattr__(
            self,
            "_core",
            FallbackChatModel(
                primary=primary,
                fallback=fallback,
                failure_threshold=failure_threshold,
                cooldown=cooldown,
                on_usage=on_usage,
            ),
        )
        # P2.1：向 deepagents 暴露主模型上下文窗口（max_input_tokens）。
        # 注意：pydantic v2 的 @property 在 BaseChatModel 子类上会被拦截，
        # 故用 object.__setattr__ 直接挂实例属性，compute_summarization_defaults
        # 读取 model.profile["max_input_tokens"] 后按窗口比例自适应触发。
        primary_name = getattr(primary, "model_name", None) or getattr(primary, "model", None)
        object.__setattr__(
            self,
            "profile",
            {"max_input_tokens": _resolve_max_input_tokens(primary_name)},
        )

    # ---- 兼容属性（只读转发，供 _FallbackModel 复用） ----

    @property
    def primary(self) -> Any:
        return self._core.primary

    @property
    def fallback(self) -> Any:
        return self._core.fallback

    @property
    def failure_threshold(self) -> int:
        return self._core.failure_threshold

    @property
    def cooldown(self) -> float:
        return self._core.cooldown

    @property
    def degraded(self) -> bool:
        return self._core.degraded

    @property
    def consecutive_failures(self) -> int:
        return self._core._consecutive_failures

    @property
    def cooldown_until(self) -> float:
        return self._core._cooldown_until

    def set_on_usage(self, callback: Any) -> None:
        """P2-2：转发 usage 回调到内核 FallbackChatModel（单一真相源）。"""
        self._core.set_on_usage(callback)

    # ---- BaseChatModel 抽象接口适配（委托内核统一路由） ----

    @property
    def _llm_type(self) -> str:
        return "fallback_chat_model"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        # 委托内核 FallbackChatModel.invoke：内部完成主备路由、失败捕获、
        # 计数降级与成功复位，不在此复制降级逻辑。
        result = self._core.invoke(messages, stop=stop, **kwargs)
        if hasattr(result, "content"):
            return ChatResult(generations=[ChatGeneration(message=result)])
        return result

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        result = await self._core.ainvoke(messages, stop=stop, **kwargs)
        if hasattr(result, "content"):
            return ChatResult(generations=[ChatGeneration(message=result)])
        return result

    def bind_tools(self, *args: Any, **kwargs: Any):
        return self._core.primary.bind_tools(*args, **kwargs)

    def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        from langchain_core.outputs import ChatGenerationChunk

        for chunk in self._core.stream(messages, stop=stop, **kwargs):
            if isinstance(chunk, ChatGenerationChunk):
                yield chunk
            else:
                yield ChatGenerationChunk(message=chunk)

    async def _astream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        from langchain_core.outputs import ChatGenerationChunk

        async for chunk in self._core.astream(messages, stop=stop, **kwargs):
            if isinstance(chunk, ChatGenerationChunk):
                yield chunk
            else:
                yield ChatGenerationChunk(message=chunk)


__all__ = ["LangChainFallbackModel"]
