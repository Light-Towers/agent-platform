"""Langfuse 三态降级测试：凭据空/全/导入失败。

get_langfuse_callbacks 三态：空凭据→[] / 全凭据→[handler] / 导入失败→[]+warning。
主链路绝不因 tracing 失败中断。
"""

from __future__ import annotations

from agent_runtime.tracing import get_langfuse_callbacks


def test_empty_public_key_returns_empty():
    result = get_langfuse_callbacks(public_key="", secret_key="sk", host="h")
    assert result == []


def test_empty_secret_key_returns_empty():
    result = get_langfuse_callbacks(public_key="pk", secret_key="", host="h")
    assert result == []


def test_both_empty_returns_empty():
    result = get_langfuse_callbacks()
    assert result == []


def test_host_alone_does_not_enable():
    result = get_langfuse_callbacks(public_key="", secret_key="", host="h")
    assert result == []


def test_import_failure_returns_empty():
    """langfuse 未安装时降级返回空 list。"""
    import sys

    original = sys.modules.get("langfuse.callback")
    sys.modules["langfuse.callback"] = None
    try:
        result = get_langfuse_callbacks(public_key="pk", secret_key="sk", host="h")
    finally:
        if original is not None:
            sys.modules["langfuse.callback"] = original
        else:
            sys.modules.pop("langfuse.callback", None)
    assert result == []


def test_import_failure_logs_warning(caplog):
    """导入失败时记录 warning 日志。"""
    import sys

    original = sys.modules.get("langfuse.callback")
    sys.modules["langfuse.callback"] = None
    try:
        with caplog.at_level("WARNING", logger="agent_runtime.tracing"):
            result = get_langfuse_callbacks(public_key="pk", secret_key="sk", host="h")
    finally:
        if original is not None:
            sys.modules["langfuse.callback"] = original
        else:
            sys.modules.pop("langfuse.callback", None)
    assert result == []
    assert any("Langfuse" in r.message or "trace" in r.message for r in caplog.records)


def test_return_type_is_always_list():
    """三态都返回 list，绝不返回 None。"""
    assert isinstance(get_langfuse_callbacks(), list)
    assert isinstance(get_langfuse_callbacks("pk", "sk"), list)
