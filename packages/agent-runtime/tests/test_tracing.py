"""Langfuse 三态降级测试：凭据空/全/导入失败。

get_langfuse_callbacks 三态：空凭据→[] / 全凭据→[handler] / 导入失败→[]+warning。
主链路绝不因 tracing 失败中断。

（2026-09-30 门面退役：原同目录 test_otel.py 的 kernel 降级钉用例迁至
``packages/agent-core/tests/test_tracing_degradation.py``，真装组合钉用例收编至本文件末尾。）
"""

from __future__ import annotations

import pytest

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
    """langfuse 导入失败时降级返回空 list。

    S4 迁移后 import 面为 langfuse.langchain（v3+/v4 契约）；模拟点同步切换——
    旧 langfuse.callback 条目已不在真实 import 路径上，在真装 langfuse 的环境下
    置 None 无法触发降级（前提失效非断言放宽，三态契约不变）。
    """
    import sys

    original = sys.modules.get("langfuse.langchain")
    sys.modules["langfuse.langchain"] = None
    try:
        result = get_langfuse_callbacks(public_key="pk", secret_key="sk", host="h")
    finally:
        if original is not None:
            sys.modules["langfuse.langchain"] = original
        else:
            sys.modules.pop("langfuse.langchain", None)
    assert result == []


def test_import_failure_logs_warning(caplog):
    """导入失败时记录 warning 日志（模拟点随 S4 import 面切 langfuse.langchain）。"""
    import sys

    original = sys.modules.get("langfuse.langchain")
    sys.modules["langfuse.langchain"] = None
    try:
        with caplog.at_level("WARNING", logger="agent_runtime.tracing"):
            result = get_langfuse_callbacks(public_key="pk", secret_key="sk", host="h")
    finally:
        if original is not None:
            sys.modules["langfuse.langchain"] = original
        else:
            sys.modules.pop("langfuse.langchain", None)
    assert result == []
    assert any("Langfuse" in r.message or "trace" in r.message for r in caplog.records)


def test_return_type_is_always_list():
    """三态都返回 list，绝不返回 None。"""
    assert isinstance(get_langfuse_callbacks(), list)
    assert isinstance(get_langfuse_callbacks(public_key="pk", secret_key="sk", host="h"), list)


def test_get_langfuse_callbacks_real_import_path():
    """S4 代际契约真 import 路径钉用例（方案 §6-6，2026-09-30 自 test_otel.py 收编）：
    langfuse v3+/v4 下 callbacks 非空。

    旧 v2 写法（langfuse.callback.CallbackHandler(secret_key=, host=)）在真装 v3+ 时
    必 TypeError → 恒降级空列表，该组合从未被任何 session 覆盖（R1）。本用例钉住
    迁移后的真实构造路径（离线，不发网络）。未装 langfuse 的默认 session
    自动 skip（设计意图）；实测命令：``uv run --extra otel --with langfuse
    pytest packages/agent-runtime/tests -q``。
    """
    pytest.importorskip("langfuse", reason="langfuse extras 未安装（默认 session 设计内 skip）")

    cbs = get_langfuse_callbacks(
        public_key="pk-lf-test", secret_key="sk-lf-test", host="http://localhost:3000"
    )
    assert len(cbs) == 1
    assert type(cbs[0]).__name__ == "LangchainCallbackHandler"
    # 凭据缺失 → 空列表（未启用语义不变，opt-in 铁律）
    assert get_langfuse_callbacks() == []
    assert isinstance(get_langfuse_callbacks("pk", "sk"), list)
