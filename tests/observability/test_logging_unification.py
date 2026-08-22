"""M3：日志框架统一单测（agent_core.logging + 入口接入）。

覆盖 docs/plan-m3-m5-logging-pool.md §2.4 验收项：
- 身份保留：get_logger(__name__) 不重写命名空间。
- 无重复日志：agent_core 子树 propagate=False，单条日志仅输出一次。
- 配置幂等：重复 configure_logging() 不增长 handler 数量。
- 无静默丢弃：agent_runtime.* 在 INFO 级别下可见。
- 第三方噪声不爆炸：configure_logging() 默认不把 httpx/uvicorn 等拉到 DEBUG。

不依赖真实应用启动，直接驱动 agent_core.logging。
"""

import logging

import agent_core.logging as L
import pytest
from agent_core.logging import configure_logging, get_logger


@pytest.fixture
def logging_reset():
    """隔离 logging 全局状态：测试前后重置 root / agent_core 子树。"""
    saved_configured = L._CONFIGURED
    root = logging.getLogger()
    saved_root_handlers = list(root.handlers)
    ac = logging.getLogger("agent_core")
    saved_ac_handlers = list(ac.handlers)
    saved_prop = ac.propagate

    L._CONFIGURED = False
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in list(ac.handlers):
        ac.removeHandler(h)
    ac.propagate = True

    yield

    L._CONFIGURED = saved_configured
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_root_handlers:
        root.addHandler(h)
    for h in list(ac.handlers):
        ac.removeHandler(h)
    for h in saved_ac_handlers:
        ac.addHandler(h)
    ac.propagate = saved_prop


def test_identity_preserved(logging_reset):
    # get_logger 不做命名空间改写，保持 __name__ 原样
    assert get_logger("agent_runtime.admission").name == "agent_runtime.admission"
    assert get_logger("foo").name == "foo"
    assert get_logger("agent_core.x").name == "agent_core.x"
    assert get_logger("").name == "root"  # 空名返回 root logger，name 为 "root"


def test_no_double_logging(capsys, logging_reset):
    configure_logging()
    marker = "M3_MARKER_NO_DOUBLE"
    get_logger("agent_core.m3").info(marker)
    err = capsys.readouterr().err
    # agent_core 子树 propagate=False：单条日志仅经 agent_core handler 输出一次
    assert err.count(marker) == 1


def test_configure_logging_idempotent_handler_count(logging_reset):
    configure_logging()
    root = logging.getLogger()
    ac = logging.getLogger("agent_core")
    # agent_core 子树恰好一个自有 handler（pytest 自带 root handler 不影响此断言）
    n_ac = len(ac.handlers)
    assert n_ac == 1
    n_root = len(root.handlers)
    # 重复调用或改变级别，不应增长 handler 数量（避免重复日志）
    configure_logging()
    configure_logging(level="DEBUG")
    assert len(root.handlers) == n_root
    assert len(ac.handlers) == n_ac


def test_no_silent_drop_agent_runtime_info(logging_reset):
    configure_logging(level="INFO")
    recs = []

    class Rec(logging.Handler):
        def emit(self, record):
            recs.append(record.getMessage())

    h = Rec()
    root = logging.getLogger()
    root.addHandler(h)
    try:
        logging.getLogger("agent_runtime.admission").info("VISIBLE_MSG")
        assert any("VISIBLE_MSG" in m for m in recs)
    finally:
        root.removeHandler(h)


def test_third_party_not_blasted_to_debug(logging_reset):
    configure_logging()  # 默认 INFO，非 DEBUG
    # 第三方库不被显式拉低级别（默认 NOTSET，继承 root；不应被设到 DEBUG）
    assert logging.getLogger("httpx").level == logging.NOTSET
    assert logging.getLogger("uvicorn").level == logging.NOTSET
    # 默认 root 级别为 INFO（非 DEBUG），不会引发第三方 DEBUG 噪声爆炸
    assert logging.getLogger().level == logging.INFO
