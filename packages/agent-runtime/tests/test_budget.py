"""ContextBudget 单元测试：分层 token 预算 + 余量回流。"""

from __future__ import annotations

import pytest

from agent_runtime.context.budget import ContextBudget, Layer


def test_budget_input_budget():
    b = ContextBudget(model_window=128_000)
    assert b.input_budget == 128_000 - 4096


def test_budget_input_budget_floor():
    b = ContextBudget(model_window=100, response_reserve=200)
    assert b.input_budget == 1


def test_budget_invalid_window():
    with pytest.raises(ValueError, match="model_window"):
        ContextBudget(model_window=0)


def test_budget_invalid_ratio_sum():
    with pytest.raises(ValueError, match="占比之和"):
        ContextBudget(
            model_window=1000,
            layers={Layer.SYSTEM: 0.5, Layer.CONVERSATION: 0.3},
        )


def test_static_caps_sum_to_input_budget():
    b = ContextBudget(model_window=128_000)
    caps = b.static_caps()
    assert sum(caps.values()) <= b.input_budget
    assert all(v > 0 for v in caps.values())


def test_effective_caps_no_reflow_when_all_used():
    b = ContextBudget(model_window=128_000)
    caps = b.static_caps()
    used = dict(caps)
    eff = b.effective_caps(used)
    assert eff == caps


def test_effective_caps_reflow_to_receivers():
    b = ContextBudget(model_window=128_000)
    caps = b.static_caps()
    used = {layer: 0 for layer in caps}
    eff = b.effective_caps(used)
    surplus = sum(caps[layer] for layer in caps if layer not in b.reflow_receivers)
    assert eff[Layer.CONVERSATION] == caps[Layer.CONVERSATION] + surplus
    assert eff[Layer.TOOL_RESULTS] == caps[Layer.TOOL_RESULTS] + surplus


def test_effective_caps_partial_usage():
    b = ContextBudget(model_window=128_000)
    caps = b.static_caps()
    used = {Layer.SYSTEM: caps[Layer.SYSTEM] // 2, Layer.TASK: caps[Layer.TASK] // 2}
    eff = b.effective_caps(used)
    assert eff[Layer.CONVERSATION] >= caps[Layer.CONVERSATION]


def test_ratio_of():
    b = ContextBudget(model_window=128_000)
    assert b.ratio_of(Layer.SYSTEM) == 0.05
    assert b.ratio_of(Layer.TOOL_RESULTS) == 0.35
