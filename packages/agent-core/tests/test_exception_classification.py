"""M1.1 异常分类单测（agent-core 内核，轻量、无 DB）。

覆盖 classify_exception 的三类规则与标记异常；不触碰既有 test_resilience.py
（其 validate_config 导入已先于本方案损坏，单独报告）。
"""

import pytest

from agent_core.resilience import (
    ErrorClass,
    FatalError,
    RetryableError,
    classify_exception,
)


def test_classify_retryable_builtins():
    assert classify_exception(ConnectionError("x")).value == "retryable"
    assert classify_exception(TimeoutError("x")).value == "retryable"


def test_classify_retryable_status_code():
    class _HttpErr(Exception):
        status_code = 503

    assert classify_exception(_HttpErr()).value == "retryable"

    class _Http200(Exception):
        status_code = 200

    # 200 非瞬态，且无其它信号 → 默认 recoverable
    assert classify_exception(_Http200()).value == "recoverable"


def test_classify_retryable_name_heuristic():
    class _FooRateLimitError(Exception):
        pass

    assert classify_exception(_FooRateLimitError()).value == "retryable"


def test_classify_fatal_types():
    for exc in (
        TypeError(),
        ValueError(),
        KeyError("k"),
        AttributeError(),
        AssertionError(),
    ):
        assert classify_exception(exc).value == "fatal"


def test_classify_marker_exceptions():
    assert classify_exception(RetryableError()).value == "retryable"
    assert classify_exception(FatalError()).value == "fatal"


def test_classify_unknown_defaults_recoverable():
    # 未知第三方异常默认降级继续（保守可用性），不盲目重试也不冒泡
    assert classify_exception(RuntimeError("opaque")).value == "recoverable"
    assert classify_exception(Exception("plain")).value == "recoverable"


def test_classify_baseexception_is_fatal():
    # 不应被静默降级
    assert classify_exception(KeyboardInterrupt()).value == "fatal"
