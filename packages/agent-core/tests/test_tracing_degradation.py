# -*- coding: utf-8 -*-
"""kernel 观测状态机降级/幂等路径钉用例（门面退役后由 kernel 自持覆盖面）。

原 ``packages/agent-runtime/tests/test_otel.py`` 经 agent_runtime.otel 薄门面间接
钉这些语义；门面退役（观测方案 §3.1/§12，2026-09-30）后在此直调 kernel 钉住，
默认 CI（无 SDK）即跑——保证 DISABLED/DEGRADED/no-op 降级/幂等/脱敏四面对
任何宿主入口成立（三态语义 R5：运维可区分"显式关"与"启用但坏了"）。
真 SDK ACTIVE 路径钉用例见 tests/observability（--extra otel session，S3 补盲）。
"""

from __future__ import annotations

import pytest

from agent_core.tracing import (
    _NoOpTracer,
    _SDK_AVAILABLE,
    force_flush,
    get_tracer,
    get_tracing_status,
    init_tracing,
    is_initialized,
    is_tracing_enabled,
    shutdown_tracing,
    start_span,
    user_query_hash,
)
from agent_core.tracing_propagation import (
    extract_traceparent,
    get_current_traceparent,
    use_context,
)


@pytest.fixture(autouse=True)
def _isolate_kernel_state():
    """每用例前后重置 kernel 观测状态机（含 OTel API 全局 provider，防跨用例泄漏）。"""
    from agent_core.tracing import _reset_for_tests

    _reset_for_tests()
    yield
    _reset_for_tests()


def test_get_tracer_uninit_returns_noop():
    """未初始化时 get_tracer 返回 no-op tracer（opt-in 铁律：不 init 零副作用）。"""
    assert isinstance(get_tracer(), _NoOpTracer)


def test_init_disabled_explicit_false():
    """enabled=False 显式关闭 → DISABLED，tracer 为 no-op。"""
    init_tracing(enabled=False)
    assert is_tracing_enabled() is False
    assert get_tracing_status()["status"] == "DISABLED"
    assert isinstance(get_tracer(), _NoOpTracer)


def test_init_enabled_without_endpoint_degraded(monkeypatch):
    """启用但无端点/未注入 exporter → DEGRADED=no_export_endpoint（R5 可诊断）。

    前置条件显式化：内核 DEGRADED 原因判定是**依赖层优先于配置层**（tracing.py 的
    `if enabled and not _SDK_AVAILABLE` 在 `elif enabled and not can_export` 之前），
    故“仅缺端点”这条分支只有在 SDK 已装的宿主才自然 reachable。默认 CI 环境不装
    OTel SDK（`make test` 根 session 无 `--extra otel`），不钉住 `_SDK_AVAILABLE`
    就会因宿主差异而失败，故在此显式置位（早退分支不构造 provider，不需真 SDK）。
    """
    import agent_core.tracing as kernel_tracing

    monkeypatch.setattr(kernel_tracing, "_SDK_AVAILABLE", True)
    init_tracing(enabled=True, otel_endpoint="")
    assert is_tracing_enabled() is False
    status = get_tracing_status()
    assert status["status"] == "DEGRADED"
    assert status["reason"] == "no_export_endpoint"


@pytest.mark.skipif(_SDK_AVAILABLE, reason="已装真 SDK：依赖层前置条件不成立（上一条用例已钉配置层）")
def test_degraded_reason_priority_sdk_before_endpoint():
    """钉住优先级：同时缺 SDK + 缺端点时，先报依赖层 `sdk_not_installed`。

    两条降级用例合起来把 2×2（SDK 有无 × 端点有无）钉完整：有人调换 kernel 里两个
    分支顺序时，本用例在 CI（无 SDK）会红，而非静默改变运维看到的原因。
    """
    init_tracing(enabled=True, otel_endpoint="")
    status = get_tracing_status()
    assert status["status"] == "DEGRADED"
    assert status["reason"] == "sdk_not_installed"


@pytest.mark.skipif(_SDK_AVAILABLE, reason="已装真 SDK：ACTIVE 路径成立，降级前提不成立（见 tests/observability）")
def test_init_sdk_missing_degraded():
    """请求启用但 SDK 缺失 → DEGRADED=sdk_not_installed（文案与真因一致，R5）。"""
    init_tracing(enabled=True, otel_endpoint="http://localhost:4318")
    status = get_tracing_status()
    assert status["status"] == "DEGRADED"
    assert status["reason"] == "sdk_not_installed"
    assert isinstance(get_tracer(), _NoOpTracer)


def test_init_idempotent_short_circuit():
    """重复 init 幂等短路：首次定态，后次调用不改状态机、不抛异常。"""
    init_tracing(enabled=False)
    init_tracing(enabled=False)
    init_tracing(enabled=True, otel_endpoint="")
    assert is_initialized() is True
    assert isinstance(get_tracer(), _NoOpTracer)


@pytest.mark.skipif(_SDK_AVAILABLE, reason="已装真 SDK：非法采样率钳制发生在 ACTIVE 建 provider 路径，由 tests/observability 覆盖")
def test_invalid_sampling_rate_no_raise_without_sdk():
    """非法采样率不抛异常（入口钳制 1.0；无 SDK 环境统一降级不炸）。"""
    init_tracing(enabled=True, sampling_rate=-0.5, otel_endpoint="http://x:1")
    init_tracing(enabled=True, sampling_rate=2.0, otel_endpoint="http://x:1")


def test_flush_and_shutdown_safe_when_uninit():
    """未初始化时 force_flush / shutdown_tracing 均 no-op 不抛（lifespan 退出零风险）。"""
    force_flush()
    shutdown_tracing()


def test_start_span_uninit_usable():
    """未 init 时 start_span 可作 with 上下文且属性操作零副作用（no-op 降级铁律）。"""
    with start_span("noop.span", attrs={"k": "v"}) as span:
        assert span.is_recording() is False
        span.set_attribute("a", 1)


def test_user_query_hash_stable_and_redacted():
    """脱敏（原门面 redact_question 语义落 kernel user_query_hash）：16 位 hex、稳定、不含全文。"""
    q = "我的订单1001的物流状态如何？"
    h = user_query_hash(q)
    assert len(h) == 16
    assert int(h, 16) >= 0  # 合法 hex
    assert h == user_query_hash(q)
    assert h != user_query_hash("问题B")
    assert q not in h


def test_extract_traceparent_invalid_header_treated_as_noop():
    """畸形 traceparent 透传门：未启用态提取返回 None 或假 context，use_context 零副作用（R6 面）。"""
    assert get_current_traceparent() is None  # 未 init 无 current span
    ctx = extract_traceparent({"traceparent": "garbage"})
    with use_context(ctx):
        assert get_current_traceparent() is None
