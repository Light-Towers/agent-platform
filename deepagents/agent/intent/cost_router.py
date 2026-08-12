"""成本路由：简单意图走便宜模型，复杂意图走大模型。

扩展 agent/llm.py 已有模型 fallback，按意图分级选模型。
"""

from __future__ import annotations

import os
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_MODEL_TIERS: dict[str, str] = {
    "chitchat": "cheap",
    "web_search": "cheap",
    "rag_knowledge": "standard",
    "customer_service": "standard",
    "text_to_sql": "premium",
    "unknown": "standard",
}

_TIER_CONFIG: dict[str, dict[str, str]] = {
    "cheap": {
        "model": os.getenv("COST_ROUTER_CHEAP_MODEL", "qwen-plus"),
        "base_url": os.getenv("COST_ROUTER_CHEAP_URL", ""),
        "api_key": os.getenv("COST_ROUTER_CHEAP_KEY", ""),
    },
    "standard": {
        "model": os.getenv("COST_ROUTER_STANDARD_MODEL", "qwen-max"),
        "base_url": os.getenv("COST_ROUTER_STANDARD_URL", ""),
        "api_key": os.getenv("COST_ROUTER_STANDARD_KEY", ""),
    },
    "premium": {
        "model": os.getenv("COST_ROUTER_PREMIUM_MODEL", "qwen-max"),
        "base_url": os.getenv("COST_ROUTER_PREMIUM_URL", ""),
        "api_key": os.getenv("COST_ROUTER_PREMIUM_KEY", ""),
    },
}


def get_model_tier(intent: str) -> str:
    """根据意图返回模型层级。"""
    return _MODEL_TIERS.get(intent, "standard")


def get_model_for_intent(intent: str) -> dict[str, str]:
    """根据意图返回模型配置。

    Returns:
        {"tier": "cheap", "model": "qwen-plus", "base_url": "...", "api_key": "..."}
    """
    tier = get_model_tier(intent)
    config = _TIER_CONFIG.get(tier, _TIER_CONFIG["standard"])
    return {"tier": tier, **config}


def is_cost_router_enabled() -> bool:
    """成本路由是否启用。"""
    return os.getenv("COST_ROUTER_ENABLED", "false").lower() == "true"


def route_model(intent: str, default_model: Any = None) -> Any:
    """根据意图路由到对应模型。

    Args:
        intent: 意图标签
        default_model: 默认模型（成本路由未启用时返回）

    Returns:
        模型对象（成本路由未启用时返回 default_model）
    """
    if not is_cost_router_enabled():
        return default_model

    config = get_model_for_intent(intent)
    logger.info("成本路由: intent=%s → tier=%s, model=%s", intent, config["tier"], config["model"])

    try:
        if config["base_url"] and config["api_key"]:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=config["model"],
                base_url=config["base_url"],
                api_key=config["api_key"],
            )
    except Exception as e:
        logger.warning("成本路由模型创建失败: %s，回退默认模型", e)

    return default_model
