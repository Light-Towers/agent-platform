"""LLM 可观测后端抽象（C 方案：接口先行，实现渐进）。

Protocol 定义 trace + eval + dataset + prompt management + score 全部能力接口。
当前只实现 get_callbacks()（trace 接入），其余方法留 NotImplementedError（未来渐进实现）。

后端：
    - LangfuseBackend：开源（MIT），默认，自托管
    - NoOpBackend：SDK 未安装 / 未配置时降级

切换：config.llm_obs_backend = "langfuse" | "noop"
（"langsmith" 不再内置：LangSmith 的 callback 需 langchain bridge，与本项目
"不引入 LangChain 全家桶"红线冲突；如需 LangSmith，经 langsmith 独立 SDK 自行接入）
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_core.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class LLMObsBackend(Protocol):
    """LLM 可观测后端协议（接口先行，实现渐进）。

    当前实现：get_callbacks（trace 接入 LangGraph）。
    未来实现：eval / log_prompt / create_dataset / score。
    """

    name: str

    def get_callbacks(self) -> list[Any]:
        """返回 LangGraph/LangChain callback handler 列表（trace 接入）。"""
        ...

    def eval(
        self,
        name: str,
        data: list[dict[str, Any]],
        scores: dict[str, float] | None = None,
    ) -> str:
        """创建 eval run，返回 run_id。"""
        ...

    def log_prompt(
        self,
        name: str,
        template: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """记录/管理 prompt 版本，返回 prompt_id。"""
        ...

    def create_dataset(
        self,
        name: str,
        items: list[dict[str, Any]] | None = None,
    ) -> str:
        """创建 dataset，返回 dataset_id。"""
        ...

    def score(
        self,
        run_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """对某次 run 打分。"""
        ...


class NoOpBackend:
    """no-op 后端（SDK 未安装 / 未配置时降级，绝不抛异常）。"""

    name = "noop"

    def get_callbacks(self) -> list[Any]:
        return []

    def eval(self, name: str, data: list[dict[str, Any]], scores: dict[str, float] | None = None) -> str:
        raise NotImplementedError("eval 待引入 LLM 可观测后端")

    def log_prompt(self, name: str, template: str, config: dict[str, Any] | None = None) -> str:
        raise NotImplementedError("prompt management 待引入")

    def create_dataset(self, name: str, items: list[dict[str, Any]] | None = None) -> str:
        raise NotImplementedError("dataset 待引入")

    def score(self, run_id: str, name: str, value: float, comment: str | None = None) -> None:
        raise NotImplementedError("score 待引入")


class LangfuseBackend:
    """Langfuse 后端（开源 MIT，默认）。SDK 未安装时 get_callbacks 返回空列表。"""

    name = "langfuse"

    def __init__(self) -> None:
        self._handler: Any = None
        try:
            from langfuse.callback import CallbackHandler  # noqa: PLC0415

            self._handler = CallbackHandler()
            logger.info("Langfuse callback handler 已加载")
        except ImportError:
            logger.info("langfuse SDK 未安装，LangfuseBackend 降级为 no-op（uv pip install langfuse 启用）")

    def get_callbacks(self) -> list[Any]:
        return [self._handler] if self._handler is not None else []

    def eval(self, name: str, data: list[dict[str, Any]], scores: dict[str, float] | None = None) -> str:
        raise NotImplementedError("Langfuse eval 待实现")

    def log_prompt(self, name: str, template: str, config: dict[str, Any] | None = None) -> str:
        raise NotImplementedError("Langfuse prompt management 待实现")

    def create_dataset(self, name: str, items: list[dict[str, Any]] | None = None) -> str:
        raise NotImplementedError("Langfuse dataset 待实现")

    def score(self, run_id: str, name: str, value: float, comment: str | None = None) -> None:
        raise NotImplementedError("Langfuse score 待实现")


class LangSmithBackend:
    """已移除：LangSmith callback 需 langchain bridge，与"不引入 LangChain 全家桶"红线冲突。

    保留类名仅为向后兼容 import（实际降级为 NoOpBackend 行为）。
    如需 LangSmith，经 langsmith 独立 SDK 自行实现 LLMObsBackend Protocol。
    """

    name = "langsmith"

    def get_callbacks(self) -> list[Any]:
        return []

    def eval(self, name: str, data: list[dict[str, Any]], scores: dict[str, float] | None = None) -> str:
        raise NotImplementedError("LangSmith 后端已移除（langchain 红线），经 langsmith SDK 自行接入")

    def log_prompt(self, name: str, template: str, config: dict[str, Any] | None = None) -> str:
        raise NotImplementedError("LangSmith 后端已移除（langchain 红线），经 langsmith SDK 自行接入")

    def create_dataset(self, name: str, items: list[dict[str, Any]] | None = None) -> str:
        raise NotImplementedError("LangSmith 后端已移除（langchain 红线），经 langsmith SDK 自行接入")

    def score(self, run_id: str, name: str, value: float, comment: str | None = None) -> None:
        raise NotImplementedError("LangSmith 后端已移除（langchain 红线），经 langsmith SDK 自行接入")


_backend_cache: LLMObsBackend | None = None


def get_llm_obs_backend(backend_name: str = "langfuse") -> LLMObsBackend:
    """factory：按配置名返回 LLM 可观测后端（单例缓存）。"""
    global _backend_cache
    if _backend_cache is not None and _backend_cache.name == backend_name:
        return _backend_cache

    if backend_name == "langsmith":
        _backend_cache = LangSmithBackend()
    elif backend_name == "langfuse":
        _backend_cache = LangfuseBackend()
    elif backend_name == "noop":
        _backend_cache = NoOpBackend()
    else:
        logger.warning("未知 llm_obs_backend=%s，降级为 noop", backend_name)
        _backend_cache = NoOpBackend()
    return _backend_cache


def reset_backend_cache() -> None:
    """重置后端缓存（测试隔离用）。"""
    global _backend_cache
    _backend_cache = None


__all__ = [
    "LLMObsBackend",
    "NoOpBackend",
    "LangfuseBackend",
    "LangSmithBackend",
    "get_llm_obs_backend",
    "reset_backend_cache",
]
