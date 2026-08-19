"""联邦网关配置：子服务地址、模式、健康探活。

模式切换：
  AGENT_MODE=local   → 纯本地子 Agent（现有行为，默认）
  AGENT_MODE=remote  → 远程 AsyncSubAgent + 本地 fallback（Phase 2 目标）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from agent_core.logging import get_logger
from dotenv import find_dotenv, load_dotenv

logger = get_logger(__name__)

load_dotenv(find_dotenv())


@dataclass(frozen=True)
class SubserviceConfig:
    """单个子服务配置。"""

    name: str
    graph_id: str
    url: str
    # 远程回退（httpx）调用该子服务的 HTTP 端点路径。
    # 各子服务协议不同：kefu-service 走 /invoke（Agent Protocol，返回 QueryResponse），
    # wenda-data-agent 走 /api/query（返回 SqlQueryResponse），zhiku 走 /api/query 等。
    endpoint: str = "/api/messages"
    local_agent: dict | None = field(default=None, repr=False)
    healthy: bool = True


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


AGENT_MODE = _env("AGENT_MODE", "local")

_subservices: dict[str, SubserviceConfig] = {
    "text_to_sql": SubserviceConfig(
        name="业务数据查询助手",
        graph_id="text_to_sql",
        # wenda-adapter 已退役，Text-to-SQL 能力由 wenda-data-agent 直连提供
        # wenda-data-agent 实际监听 :8000（见其 README 启动命令）
        url=_env("WENDA_DATA_AGENT_URL", "http://localhost:8000"),
        endpoint="/api/query",
    ),
    "rag_query": SubserviceConfig(
        name="知识库检索助手",
        graph_id="rag_query",
        url=_env("ZHIKU_API_URL", "http://localhost:8900"),
    ),
    "customer_service": SubserviceConfig(
        name="智能客服助手",
        graph_id="customer_service",
        # kefu 迁移开关（Phase 7 收尾已修复）：
        #   KEFU_USE_ADAPTER=false → 直连 kefu-service(:8003) 的 /invoke（Agent Protocol 兼容，
        #   返回 QueryResponse），kefu-adapter 转换层可废弃；
        #   KEFU_USE_ADAPTER=true  → 仍经 kefu-adapter(:8002)（外部 legacy 未退役前的过渡）。
        url=(
            _env("KEFU_SERVICE_URL", "http://localhost:8003")
            if _env("KEFU_USE_ADAPTER", "false").lower() != "true"
            else _env("KEFU_ADAPTER_URL", "http://localhost:8002")
        ),
        endpoint="/invoke",
    ),
}


def use_kefu_adapter() -> bool:
    """是否经 kefu-adapter 中转（默认 false，直连 kefu-service）。"""
    return _env("KEFU_USE_ADAPTER", "false").lower() == "true"


def get_subservice(key: str) -> SubserviceConfig:
    return _subservices[key]


# P3：本地 fallback 装配（lazy，避免 import 期引入 subagents -> tools 链）。
# key -> 本地 subagent 模块路径（与 remote 子服务一一对应）。
_LOCAL_FALLBACK_MODULES: dict[str, str] = {
    "text_to_sql": "agent.subagents.database_query_agent",
    "rag_query": "agent.subagents.knowledge_base_agent",
    "customer_service": "agent.subagents.network_search_agent",
}
_local_fallbacks_wired = False


def _wire_local_fallbacks() -> None:
    """P3：将本地 subagent dict 挂到对应远程子服务的 local_agent 字段。

    仅在 AGENT_MODE=remote 时生效（本地模式下 remote 子服务本就不参与委派，
    无需装配 fallback）。首次 get_all_subservices 调用时 lazy import，避免
    import 期把 tools.* 链拉进来造成循环依赖。
    """
    global _local_fallbacks_wired
    if _local_fallbacks_wired:
        return
    _local_fallbacks_wired = True
    if not is_remote_mode():
        return
    import importlib

    for key, mod_path in _LOCAL_FALLBACK_MODULES.items():
        if key not in _subservices:
            continue
        try:
            mod = importlib.import_module(mod_path)
            local_agent = getattr(mod, f"{key.split('_')[0]}_agent", None)
            if local_agent is None:
                # 取模块内名为 *_agent 的第一个变量
                local_agent = next(
                    (v for v in vars(mod).values()
                     if isinstance(v, dict) and v.get("name") and v.get("tools") is not None),
                    None,
                )
            if local_agent:
                old = _subservices[key]
                _subservices[key] = SubserviceConfig(
                    name=old.name, graph_id=old.graph_id, url=old.url,
                    endpoint=old.endpoint, local_agent=local_agent, healthy=old.healthy,
                )
                logger.info("[config] %s 本地 fallback 已装配（%s）", key, mod_path)
        except Exception as exc:  # pragma: no cover - 装配失败不阻断启动
            logger.warning("[config] %s 本地 fallback 装配失败: %s", key, exc)


def get_all_subservices() -> dict[str, SubserviceConfig]:
    _wire_local_fallbacks()
    return dict(_subservices)


def is_remote_mode() -> bool:
    return AGENT_MODE == "remote"


def mark_unhealthy(key: str) -> None:
    """标记子服务不可用（健康探活失败时调用）。"""
    old = _subservices[key]
    _subservices[key] = SubserviceConfig(
        name=old.name, graph_id=old.graph_id, url=old.url,
        endpoint=old.endpoint, local_agent=old.local_agent, healthy=False,
    )


def mark_healthy(key: str) -> None:
    """标记子服务可用。"""
    old = _subservices[key]
    _subservices[key] = SubserviceConfig(
        name=old.name, graph_id=old.graph_id, url=old.url,
        endpoint=old.endpoint, local_agent=old.local_agent, healthy=True,
    )
