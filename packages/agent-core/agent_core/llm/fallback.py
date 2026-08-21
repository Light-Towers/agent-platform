# -*- coding: utf-8 -*-
"""FallbackChatModel：主备模型 + 可复位降级（框架无关内核，零依赖）。

修复缺陷模式：降级标志只置位不复位会导致主模型恢复后仍永久走备模型。
WS-3 起降级状态机不再内嵌实现，改为**组合** ``agent_core.resilience.CircuitBreaker``
（三套熔断/降级逻辑收敛为一套）：

- 主模型失败经 ``record_failure`` 累计，连续失败达阈值 → 熔断 OPEN 并进入冷却；
- OPEN 且冷却未到期 → 请求直接路由备模型（不试探主模型）；
- 冷却到期 → 熔断转 HALF_OPEN，下一次请求试探主模型，成功则 ``record_success``
  复位回 CLOSED（可复位）。

流式降级契约（WS-3 语义修正）：``stream`` / ``astream`` 仅在**尚未产出任何
chunk** 时才允许切备模型重放；已产出 chunk 后主模型失败 → 向上抛异常。
此前"yield 一半后切备模型"会产出混杂内容，属缺陷而非降级。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_core.llm.protocols import ChatModel
from agent_core.logging import get_logger
from agent_core.resilience import CircuitBreaker

logger = get_logger(__name__)


class FallbackChatModel:
    """主备模型降级：组合 CircuitBreaker（连续失败计数 + 冷却窗口，可复位）。

    P2-2 计量点：每次 LLM 调用后从响应抽取 ``usage``（token 数）并经 ``on_usage``
    回调外发，由消费方（agent-runtime PlannerRuntime）聚合进 ``ExecutionContext``。
    本类只做**计量源**（检测 + 外发），不做聚合/闸门（那是 ExecutionContext 职责），
    保持「计量源 / 聚合器 / 装配方」三层职责不重叠。
    """

    def __init__(
        self,
        primary: ChatModel,
        fallback: ChatModel,
        failure_threshold: int = 3,
        cooldown: float = 60.0,
        on_usage: Callable[[int, float], None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        # P2-2：usage 外发回调（tokens, cost）；cost 在本层无定价信息，恒为 0.0
        self.on_usage = on_usage
        # threshold→failure_threshold，cooldown→reset_timeout：语义一一对应
        self._breaker = CircuitBreaker(
            failure_threshold=failure_threshold, reset_timeout=cooldown
        )

    def set_on_usage(self, callback: Callable[[int, float], None] | None) -> None:
        """（重）设置 usage 外发回调（PlannerRuntime 装配期调用）。"""
        self.on_usage = callback

    @staticmethod
    def _extract_usage(resp: Any) -> int:
        """从 LangChain AIMessage / AIMessageChunk 抽取总 token 数（P2-2）。

        兼容 ``usage_metadata``（pydantic 或 dict）与 ``response_metadata.usage``；
        取 ``total_tokens``，缺失时回退 ``input+output``（含 OpenAI 旧字段名）。
        非 LLM 响应（无 usage 信息）返回 0。
        """
        um = getattr(resp, "usage_metadata", None)
        if not um:
            rm = getattr(resp, "response_metadata", None) or {}
            um = (rm.get("usage") or rm.get("token_usage")) if isinstance(rm, dict) else None
        if not um:
            return 0
        if hasattr(um, "model_dump"):
            try:
                um = um.model_dump()
            except Exception:  # noqa: BLE001 防御：非 pydantic 实体
                um = dict(um) if isinstance(um, dict) else {}
        if not isinstance(um, dict):
            return 0
        total = um.get("total_tokens")
        if total is None:
            inp = um.get("input_tokens") or um.get("prompt_tokens") or 0
            out = um.get("output_tokens") or um.get("completion_tokens") or 0
            total = int(inp) + int(out)
        return int(total)

    def _emit_usage(self, tokens: int) -> None:
        if tokens and self.on_usage is not None:
            self.on_usage(tokens, 0.0)

    @property
    def degraded(self) -> bool:
        """是否处于降级态（熔断 OPEN / HALF_OPEN 探测中）。"""
        return self._breaker.resolved_state() in (
            CircuitBreaker.OPEN,
            CircuitBreaker.HALF_OPEN,
        )

    # -- 兼容属性（WS-3 前的旧字段名，保留一个小版本供 fallback_lc 等读） --
    @property
    def _consecutive_failures(self) -> int:
        with self._breaker._lock:  # noqa: SLF001 兼容读取
            return self._breaker._failures  # noqa: SLF001

    @property
    def _cooldown_until(self) -> float:
        with self._breaker._lock:  # noqa: SLF001 兼容读取
            opened = self._breaker._opened_at  # noqa: SLF001
            if opened is None:
                return 0.0
            return opened + self._breaker._reset_timeout  # noqa: SLF001

    def _route(self) -> Any:
        """熔断允许 → 主模型；拒绝（OPEN 冷却期内）→ 备模型。"""
        if self._breaker.allow():
            return self.primary
        return self.fallback

    def _on_primary_failure(self) -> None:
        """主模型失败：经熔断器记录（达阈值进入 OPEN + 冷却窗口，可复位）。"""
        self._breaker.record_failure()
        logger.warning("主模型调用失败，熔断状态=%s，降级备模型", self._breaker.state)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        model = self._route()
        if model is self.fallback:
            result = model.invoke(*args, **kwargs)
            self._emit_usage(self._extract_usage(result))
            return result
        try:
            result = model.invoke(*args, **kwargs)
        except Exception:  # noqa: BLE001 降级语义
            self._on_primary_failure()
            result = self.fallback.invoke(*args, **kwargs)
            self._emit_usage(self._extract_usage(result))
            return result
        self._breaker.record_success()
        self._emit_usage(self._extract_usage(result))
        return result

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        model = self._route()
        if model is self.fallback:
            result = await model.ainvoke(*args, **kwargs)
            self._emit_usage(self._extract_usage(result))
            return result
        try:
            result = await model.ainvoke(*args, **kwargs)
        except Exception:  # noqa: BLE001 降级语义
            self._on_primary_failure()
            result = await self.fallback.ainvoke(*args, **kwargs)
            self._emit_usage(self._extract_usage(result))
            return result
        self._breaker.record_success()
        self._emit_usage(self._extract_usage(result))
        return result

    def _wrap_stream(self, gen):
        """包装同步流：抽取 usage 并在生成器耗尽时外发（P2-2）。"""
        total = 0
        try:
            for chunk in gen:
                u = self._extract_usage(chunk)
                if u:
                    total = u
                yield chunk
        finally:
            self._emit_usage(total)

    async def _wrap_astream(self, gen):
        """包装异步流：抽取 usage 并在生成器耗尽时外发（P2-2）。"""
        total = 0
        try:
            async for chunk in gen:
                u = self._extract_usage(chunk)
                if u:
                    total = u
                yield chunk
        finally:
            self._emit_usage(total)

    def stream(self, *args: Any, **kwargs: Any):
        model = self._route()
        if model is self.fallback:
            yield from self._wrap_stream(model.stream(*args, **kwargs))
            return
        emitted = False
        try:
            for chunk in self._wrap_stream(model.stream(*args, **kwargs)):
                emitted = True
                yield chunk
        except Exception:  # noqa: BLE001 降级语义
            if emitted:
                # 已有 chunk 产出：切换会产出混杂内容，向上抛（WS-3 契约）
                self._on_primary_failure()
                raise
            self._on_primary_failure()
            yield from self._wrap_stream(self.fallback.stream(*args, **kwargs))
        else:
            self._breaker.record_success()

    async def astream(self, *args: Any, **kwargs: Any):
        model = self._route()
        if model is self.fallback:
            async for chunk in self._wrap_astream(model.astream(*args, **kwargs)):
                yield chunk
            return
        emitted = False
        try:
            async for chunk in self._wrap_astream(model.astream(*args, **kwargs)):
                emitted = True
                yield chunk
        except Exception:  # noqa: BLE001 降级语义
            if emitted:
                # 已有 chunk 产出：切换会产出混杂内容，向上抛（WS-3 契约）
                self._on_primary_failure()
                raise
            self._on_primary_failure()
            async for chunk in self._wrap_astream(self.fallback.astream(*args, **kwargs)):
                yield chunk
        else:
            self._breaker.record_success()

    def with_structured_output(self, schema: Any) -> Any:
        """路由等结构化场景直接用主模型；失败由调用方回退启发式。"""
        return self.primary.with_structured_output(schema)


__all__ = ["FallbackChatModel"]
