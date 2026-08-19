# -*- coding: utf-8 -*-
"""
兼容 shim：桥接 agent_core.llm，保持旧 import 路径 ``from app.lm.lm_utils import ...`` 不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.llm import get_llm_client`` 并自行注入配置。

本 shim 维持与原 ``get_llm_client(model=None, json_mode=False)`` 一致的签名，
内部读取 ``app.conf.lm_config`` 注入 api_key / base_url / temperature，再委托
``agent_core.llm.get_llm_client`` —— 5 个调用点零改动。
"""

from typing import Any, Optional

from agent_core.llm import BaseLLMProvider, OpenAICompatibleProvider, clear_cache, register_provider
from app.conf.lm_config import lm_config


def get_llm_client(model: Optional[str] = None, json_mode: bool = False) -> Any:
    """
    兼容封装：读取 lm_config 后委托 agent_core.llm.get_llm_client。

    :param model: 模型名；None 时使用 lm_config.llm_model（不再硬编码 qwen3-32b）。
    :param json_mode: 是否开启 JSON 结构化输出。
    :return: LLM 客户端实例（带缓存）。
    """
    target_model = model or lm_config.llm_model
    # 还原 zhiku 原有行为：国产模型（千问等）关闭思考链，减少冗余输出。
    # 内核不再硬编码，改由宿主经 extra_body 透传；若改用非 qwen 模型可删此行或改值。
    return get_llm_client_core(
        model=target_model,
        json_mode=json_mode,
        api_key=lm_config.api_key,
        base_url=lm_config.base_url,
        temperature=lm_config.llm_temperature or 0.1,
        extra_body={"enable_thinking": False},
    )


# 重命名避免与上面兼容封装递归；供高级调用方直接使用。
from agent_core.llm import get_llm_client as get_llm_client_core  # noqa: E402

__all__ = [
    "get_llm_client",
    "register_provider",
    "clear_cache",
    "BaseLLMProvider",
    "OpenAICompatibleProvider",
]
