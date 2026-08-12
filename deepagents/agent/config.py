"""联邦网关配置：子服务地址、模式、健康探活。

模式切换：
  AGENT_MODE=local   → 纯本地子 Agent（现有行为，默认）
  AGENT_MODE=remote  → 远程 AsyncSubAgent + 本地 fallback（Phase 2 目标）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())


@dataclass(frozen=True)
class SubserviceConfig:
    """单个子服务配置。"""

    name: str
    graph_id: str
    url: str
    local_agent: dict | None = field(default=None, repr=False)
    healthy: bool = True


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


AGENT_MODE = _env("AGENT_MODE", "local")

_subservices: dict[str, SubserviceConfig] = {
    "text_to_sql": SubserviceConfig(
        name="业务数据查询助手",
        graph_id="text_to_sql",
        url=_env("WENDA_ADAPTER_URL", "http://localhost:8001"),
    ),
    "rag_query": SubserviceConfig(
        name="知识库检索助手",
        graph_id="rag_query",
        url=_env("ZHIKU_API_URL", "http://localhost:8900"),
    ),
    "customer_service": SubserviceConfig(
        name="智能客服助手",
        graph_id="customer_service",
        url=_env("KEFU_ADAPTER_URL", "http://localhost:8002"),
    ),
}


def get_subservice(key: str) -> SubserviceConfig:
    return _subservices[key]


def get_all_subservices() -> dict[str, SubserviceConfig]:
    return dict(_subservices)


def is_remote_mode() -> bool:
    return AGENT_MODE == "remote"


def mark_unhealthy(key: str) -> None:
    """标记子服务不可用（健康探活失败时调用）。"""
    old = _subservices[key]
    _subservices[key] = SubserviceConfig(
        name=old.name, graph_id=old.graph_id, url=old.url,
        local_agent=old.local_agent, healthy=False,
    )


def mark_healthy(key: str) -> None:
    """标记子服务可用。"""
    old = _subservices[key]
    _subservices[key] = SubserviceConfig(
        name=old.name, graph_id=old.graph_id, url=old.url,
        local_agent=old.local_agent, healthy=True,
    )
