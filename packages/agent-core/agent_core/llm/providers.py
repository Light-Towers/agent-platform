# -*- coding: utf-8 -*-
"""
LLM 客户端抽象（框架无关内核，源自 zhiku app/lm/lm_utils）。

设计目标：
- 核心协议层 ``BaseLLMProvider`` **零第三方依赖**（仅 typing Protocol）；
- 具体适配器（如 ``OpenAICompatibleProvider`` 基于 langchain-openai）为**可选 extra**
  （``llm-openai``），懒导入，缺包不影响协议层 import；
- **去除 zhiku 硬编码**：``extra_body={"enable_thinking":False}`` 与默认模型 ``"qwen3-32b"``
  不再出现在内核；默认模型由 provider 实例属性（provider 级默认）或调用方传入决定，
  适配 DSH「新增一个适配器即可接入」的落地方式。

宿主应用（zhiku）应注册 provider 并注入 lm_config 的 api_key/base_url/默认模型。
"""

from typing import Any, Optional, Protocol, runtime_checkable

from agent_core.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class BaseLLMProvider(Protocol):
    """LLM 提供方协议：所有适配器实现 ``build`` 即可被 registry 使用。"""

    name: str
    default_model: str

    def build(self, model: Optional[str], json_mode: bool = False, **kwargs: Any) -> Any:
        """构造（或返回一个已缓存的）LLM 客户端实例。

        :param model: 目标模型名；None 时使用 provider 级默认（``default_model``）。
        :param json_mode: 是否开启 JSON 结构化输出。
        :param kwargs: 提供方相关配置（api_key / base_url / temperature / extra_body 等）。
        :return: 客户端实例（类型由具体适配器决定）。
        """
        ...


class OpenAICompatibleProvider:
    """OpenAI 兼容 API 适配器（langchain-openai 实现，可选 extra ``llm-openai``）。

    适配 OpenAI / 千问 / 即梦 等兼容 API。``enable_thinking`` 等厂商私有参数不再硬编码，
    改由调用方经 ``extra_body`` 传入；默认模型为 provider 实例属性，由集成方设置。
    """

    name = "openai"
    # provider 级默认模型：中性占位，集成方（如 DSH）应显式设置或调用时传入。
    default_model: str = "openai-compatible"

    def build(
        self,
        model: Optional[str] = None,
        json_mode: bool = False,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.1,
        extra_body: Optional[dict] = None,
        **kwargs: Any,
    ) -> Any:
        # langchain-openai 为可选依赖：懒导入，缺包时给出明确错误。
        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:  # pragma: no cover - 依赖缺失路径
            raise ImportError(
                "langchain-openai 未安装；请安装 agent-core[llm-openai]（uv sync --extra llm-openai）"
            ) from e

        target_model = model or self.default_model
        if not api_key:
            raise ValueError("LLM 客户端配置缺失：api_key 不能为空")
        if not base_url:
            raise ValueError("LLM 客户端配置缺失：base_url 不能为空")

        model_kwargs: dict = {}
        if json_mode:
            model_kwargs["response_format"] = {"type": "json_object"}

        logger.info("初始化 OpenAI 兼容 LLM 客户端：model=%s json_mode=%s", target_model, json_mode)
        return ChatOpenAI(
            model=target_model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            extra_body=extra_body or {},
            model_kwargs=model_kwargs,
            **kwargs,
        )


__all__ = ["BaseLLMProvider", "OpenAICompatibleProvider"]
