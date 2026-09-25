"""分层 Token 预算（Plan-F Context Pipeline）：比例可配、动态伸缩。

预算不是静态切蛋糕：每层先按上限分配，未用完的余量按优先级回流给
``conversation`` 和 ``tool_results``（这两层最容易超）。这直接回应
external review「预算应该是动态的」的判断。

层定义（``Layer``）与默认占比：
- system 5% / tool_defs 8% / task 6% / conversation 20% / memory 8% /
  tool_results 35% / execution 18% —— 合计 100%。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Layer(StrEnum):
    """上下文分层：按角色/来源划分，各层独立预算上限。"""

    SYSTEM = "system"
    TOOL_DEFS = "tool_defs"
    TASK = "task"
    CONVERSATION = "conversation"
    MEMORY = "memory"
    TOOL_RESULTS = "tool_results"
    EXECUTION = "execution"


# 默认各层占比（合计 1.0）。修改需保证 sum == 1.0。
DEFAULT_LAYER_RATIOS: dict[Layer, float] = {
    Layer.SYSTEM: 0.05,
    Layer.TOOL_DEFS: 0.08,
    Layer.TASK: 0.06,
    Layer.CONVERSATION: 0.20,
    Layer.MEMORY: 0.08,
    Layer.TOOL_RESULTS: 0.35,
    Layer.EXECUTION: 0.18,
}

# 余量回流接收层（按优先级排序：conversation 优先，其次 tool_results）
REFLOW_RECEIVERS: tuple[Layer, ...] = (Layer.CONVERSATION, Layer.TOOL_RESULTS)

# 模型窗口需预留的响应空间（token），从窗口扣除后才是可用的输入预算。
_DEFAULT_RESPONSE_RESERVE = 4096


@dataclass
class ContextBudget:
    """分层预算：窗口扣除响应预留后按比例分给各层，未用余量回流。

    用法::

        budget = ContextBudget(model_window=128_000)
        caps = budget.effective_caps(used_tokens)  # 按当前用量算最终各层上限

    ``effective_caps`` 是动态的：某层未用满时，余量回流给 conversation / tool_results。
    """

    model_window: int
    response_reserve: int = _DEFAULT_RESPONSE_RESERVE
    layers: dict[Layer, float] = field(default_factory=lambda: dict(DEFAULT_LAYER_RATIOS))
    reflow_receivers: tuple[Layer, ...] = REFLOW_RECEIVERS

    def __post_init__(self) -> None:
        if self.model_window <= 0:
            raise ValueError(f"model_window 必须为正，实际 {self.model_window}")
        total = sum(self.layers.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"layers 占比之和必须为 1.0，实际 {total}")
        for layer in self.reflow_receivers:
            if layer not in self.layers:
                raise ValueError(f"回流接收层 {layer} 不在 layers 中")

    @property
    def input_budget(self) -> int:
        """可用输入预算（扣除响应预留后的窗口）。"""
        return max(self.model_window - self.response_reserve, 1)

    def static_caps(self) -> dict[Layer, int]:
        """静态各层上限（无回流）。"""
        return {
            layer: int(self.input_budget * ratio)
            for layer, ratio in self.layers.items()
        }

    def effective_caps(self, used: dict[Layer, int] | None = None) -> dict[Layer, int]:
        """最终各层上限：静态上限 + 未用余量回流（conversation 优先）。

        ``used`` 为各层当前实际 token 占用。未传或某层未用满时，把其余量
        按接收层顺序回流；接收层超过其静态上限的部分直接吞掉余量。
        """
        used = used or {}
        caps = self.static_caps()
        # 非接收层的未用余量
        surplus = sum(
            max(caps[layer] - used.get(layer, 0), 0)
            for layer in caps
            if layer not in self.reflow_receivers
        )
        if surplus <= 0:
            return caps
        # 回流：按接收层顺序依次吸收，先 conversation 后 tool_results
        for receiver in self.reflow_receivers:
            if surplus <= 0:
                break
            caps[receiver] += surplus
            # 剩余余量继续给下一个接收层（同层可继续吸收，不设上限）
        return caps

    def ratio_of(self, layer: Layer) -> float:
        return self.layers[layer]