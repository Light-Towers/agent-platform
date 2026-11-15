"""语义缓存工厂：唯一装配点，按 scope 返回单例。

只按配置选后端，不按故障自动切换；``CACHE_BACKEND=pg`` 在配置解析阶段即失败。
"""

from __future__ import annotations

from agent_core.cache import SemanticCacheBackend
from agent_core.logging import get_logger

from agent_runtime.cache.config import CacheConfigError, get_cache_config

logger = get_logger(__name__)

_BACKENDS: dict[str, SemanticCacheBackend] = {}


def get_cache(scope: str) -> SemanticCacheBackend:
    """返回某流水线分区的缓存后端单例（``scope`` 为代码常量）。"""
    if not scope:
        raise CacheConfigError("缓存 scope 不能为空")
    backend = _BACKENDS.get(scope)
    if backend is not None:
        return backend

    config = get_cache_config()
    if not config.enabled or config.backend == "disabled":
        from agent_runtime.cache.disabled_backend import DisabledSemanticCache

        backend = DisabledSemanticCache(scope)
    else:
        try:
            from agent_runtime.cache.valkey_backend import ValkeySemanticCache
        except ImportError as exc:  # pragma: no cover - 依赖缺失时启动期失败
            raise CacheConfigError(
                "CACHE_BACKEND=valkey 但未安装 valkey 客户端；请安装 agent-runtime 的主依赖"
            ) from exc
        backend = ValkeySemanticCache(config, scope)
    _BACKENDS[scope] = backend
    return backend


async def close_cache() -> None:
    """关闭全部已装配后端（应用退出时调用）。"""
    backends = list(_BACKENDS.values())
    _BACKENDS.clear()
    for backend in backends:
        try:
            await backend.aclose()
        except Exception:  # noqa: BLE001 - 退出路径：单个后端关闭失败不得阻断其余清理
            logger.warning("关闭语义缓存后端失败（backend=%s）", type(backend).__name__, exc_info=True)


def reset_cache_for_tests() -> None:
    """清空单例表（仅测试用；不关闭连接，调用方负责先 aclose）。"""
    _BACKENDS.clear()


__all__ = ["close_cache", "get_cache", "reset_cache_for_tests"]
