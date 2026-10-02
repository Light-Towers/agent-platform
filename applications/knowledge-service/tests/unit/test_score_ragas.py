# -*- coding: utf-8 -*-
"""
test_score_ragas.py —— RAGAS adapter（eval/score_ragas.py）单测，**不连 ragas/LLM**。

生产环境未装 ragas，故仅测不依赖真实 ragas 的纯逻辑：
- _extract_value：MetricResult.value → float / None / 非法值降级；
- _gateway_config：env 解析与缺 key 抛错；
- _stub_vertexai：sys.modules 注入占位；
- _score_one：以假打分对象驱动（faithfulness/correctness 的 ascore 桩），
  覆盖正常/缺 reference→correctness None/缺 context→faithfulness None/单维异常隔离；
- make_score_fn：本地无 ragas → (False, None)（诚实不可用，不伪造）。
真实 ragas 打分链在 126 spike 容器端到端验证（见 plan-c2-cross-agreement-pivot 文档）。
"""

import asyncio
import sys

import pytest

from eval.score_ragas import (
    _extract_value,
    _gateway_config,
    _score_one,
    _stub_vertexai,
    make_score_fn,
)


class _Result:
    """模拟 ragas MetricResult（仅 .value）。"""

    def __init__(self, value):
        self.value = value


class _FakeMetric:
    """可编程返回值的 ascore 桩。"""

    def __init__(self, value=None, raises=False):
        self._value = value
        self._raises = raises
        self.calls = 0

    async def ascore(self, **kwargs):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return _Result(self._value)


# ---------------------------------------------------------------------------
# _extract_value
# ---------------------------------------------------------------------------
def test_extract_value_float():
    assert _extract_value(_Result(1.0)) == 1.0
    assert _extract_value(_Result(0.666)) == pytest.approx(0.666)


def test_extract_value_string_number():
    assert _extract_value(_Result("0.5")) == 0.5


def test_extract_value_none_and_bad():
    assert _extract_value(_Result(None)) is None
    assert _extract_value(_Result("abc")) is None
    assert _extract_value(object()) is None  # 无 .value 属性


# ---------------------------------------------------------------------------
# _gateway_config
# ---------------------------------------------------------------------------
def test_gateway_config_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("RAG_EVAL_MODEL", "Some/Model")
    model, base_url, api_key = _gateway_config()
    assert model == "Some/Model"
    assert base_url == "https://example.test/v1"
    assert api_key == "sk-test"


def test_gateway_config_default_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("RAG_EVAL_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    model, base_url, _ = _gateway_config()
    assert model == "Qwen/Qwen2.5-7B-Instruct"
    assert base_url == "https://api.openai.com/v1"


def test_gateway_config_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _gateway_config()


# ---------------------------------------------------------------------------
# _stub_vertexai
# ---------------------------------------------------------------------------
def test_stub_vertexai_injects_module():
    sys.modules.pop("langchain_community.chat_models.vertexai", None)
    _stub_vertexai()
    mod = sys.modules.get("langchain_community.chat_models.vertexai")
    assert mod is not None
    assert hasattr(mod, "ChatVertexAI")
    # 幂等：再次调用不报错
    _stub_vertexai()


# ---------------------------------------------------------------------------
# _score_one
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.run(coro)


def test_score_one_both_dims():
    faith = _FakeMetric(value=1.0)
    acc = _FakeMetric(value=0.75)
    rec = {"query": "q", "context": "ctx", "answer": "a", "reference": "ref"}
    out = _run(_score_one(faith, acc, rec))
    assert out == {"faithfulness": 1.0, "correctness": 0.75}
    assert faith.calls == 1 and acc.calls == 1


def test_score_one_missing_reference():
    faith = _FakeMetric(value=0.5)
    acc = _FakeMetric(value=0.9)
    rec = {"query": "q", "context": "ctx", "answer": "a", "reference": None}
    out = _run(_score_one(faith, acc, rec))
    assert out["faithfulness"] == 0.5
    assert out["correctness"] is None
    assert acc.calls == 0  # 缺 reference 不应调用 correctness


def test_score_one_missing_context():
    faith = _FakeMetric(value=0.5)
    acc = _FakeMetric(value=0.8)
    rec = {"query": "q", "context": "", "answer": "a", "reference": "ref"}
    out = _run(_score_one(faith, acc, rec))
    assert out["faithfulness"] is None
    assert faith.calls == 0
    assert out["correctness"] == 0.8


def test_score_one_faith_raises_isolated():
    faith = _FakeMetric(raises=True)
    acc = _FakeMetric(value=0.6)
    rec = {"query": "q", "context": "ctx", "answer": "a", "reference": "ref"}
    out = _run(_score_one(faith, acc, rec))
    assert out["faithfulness"] is None
    assert out["correctness"] == 0.6  # 单维异常不影响另一维


# ---------------------------------------------------------------------------
# make_score_fn —— 本地无 ragas → 诚实不可用
# ---------------------------------------------------------------------------
def test_make_score_fn_no_ragas_returns_unavailable():
    # 生产/本地环境未安装 ragas：importlib.metadata.version("ragas") 抛错 → (False, None)
    try:
        import importlib.metadata

        importlib.metadata.version("ragas")
        pytest.skip("本环境装了 ragas，跳过'未装'分支断言")
    except importlib.metadata.PackageNotFoundError:
        pass
    available, fn = make_score_fn()
    assert available is False
    assert fn is None
