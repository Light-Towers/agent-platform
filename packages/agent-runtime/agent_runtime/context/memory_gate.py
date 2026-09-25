"""记忆召回门控（Plan-F Context Pipeline P2）：修「查到就塞」。

在 ``recall_memories`` 之上包一层在线轻量过滤：

- 召回 top-k（默认 10）→ 去重（内容归一化哈希）→ 冲突消解（同类取最新）
  → 按相关分排序 → 只取满足 memory 层预算的前 N 条（默认 5）。

``consolidate()`` 保持离线整合定位不变，Gate 只做在线轻量过滤，两者职责分离。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from agent_core.tokenizer import count_tokens

# 内容归一化：去空白 / 去标点 / 小写，用于去重哈希与冲突判定
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]")


def _normalize(content: str) -> str:
    return _PUNCT_RE.sub("", _WS_RE.sub("", content)).lower()


@dataclass
class MemoryItem:
    """单条记忆：内容 + 元信息（供去重/冲突消解/排序）。"""

    content: str
    score: float = 0.0
    kind: str = ""  # 语义类别（question/answer/fact/...），冲突消解按同类取最新
    timestamp: float = 0.0  # 越大越新
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryGate:
    """在线记忆门控：去重 → 冲突消解 → 排序 → 预算内取 top-N。

    用法::

        gate = MemoryGate(top_k=5, max_tokens=1024)
        items = gate.gate([MemoryItem(content=..., score=...), ...])
    """

    def __init__(
        self,
        top_k: int = 5,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> None:
        self.top_k = top_k
        self.max_tokens = max_tokens
        self.model = model

    @staticmethod
    def _dedupe_key(content: str) -> str:
        return _normalize(content)

    def gate(self, items: Sequence[MemoryItem]) -> list[MemoryItem]:
        """过滤 + 排序记忆：返回满足预算的 Top-N 条（顺序=相关分降序）。"""
        if not items:
            return []

        # 1. 去重（内容归一化哈希；同内容保留 score 最高者，score 相同取最新）
        best_by_key: dict[str, MemoryItem] = {}
        for item in items:
            key = self._dedupe_key(item.content)
            prev = best_by_key.get(key)
            if prev is None or item.score > prev.score or (
                item.score == prev.score and item.timestamp >= prev.timestamp
            ):
                best_by_key[key] = item

        # 2. 冲突消解：同类（kind 相同）取最新（timestamp 大者）
        by_kind: dict[tuple[str, str], MemoryItem] = {}
        for item in best_by_key.values():
            k = (item.kind, self._dedupe_key(item.content)[:8])
            prev = by_kind.get(k)
            if prev is None or item.timestamp >= prev.timestamp:
                by_kind[k] = item

        # 3. 排序（相关分降序）+ top_k
        ranked = sorted(by_kind.values(), key=lambda i: (-i.score, i.timestamp))
        selected = ranked[: self.top_k]

        # 4. 预算内再截断（max_tokens 不为 None 时）
        if self.max_tokens is not None:
            acc = 0
            within: list[MemoryItem] = []
            for item in selected:
                tok = count_tokens(item.content, self.model)
                if acc + tok > self.max_tokens and within:
                    break
                acc += tok
                within.append(item)
            selected = within

        return selected

    @staticmethod
    def to_items(
        contents: Sequence[str],
        *,
        scores: Sequence[float] | None = None,
        kind: str = "",
        timestamps: Sequence[float] | None = None,
    ) -> list[MemoryItem]:
        """把裸字符串列表快速构造为 ``MemoryItem`` 列表（score 缺省 0）。"""
        items: list[MemoryItem] = []
        for i, content in enumerate(contents):
            items.append(
                MemoryItem(
                    content=content,
                    score=scores[i] if scores else 0.0,
                    kind=kind,
                    timestamp=timestamps[i] if timestamps else 0.0,
                )
            )
        return items


async def gate_recall(
    recall_fn: Callable[..., Any],
    *args: Any,
    gate: MemoryGate | None = None,
    **kwargs: Any,
) -> list[str]:
    """异步包装：调用 ``recall_fn`` 后经 Gate 过滤，返回过滤后的内容列表。

    兼容 ``agent_core.memory.recall_memories``（返回 str 列表）与
    federation ``semantic_memory.recall``（返回 dict 列表，含 content 键）。
    """
    gate = gate or MemoryGate()
    raw = await recall_fn(*args, **kwargs)
    if not raw:
        return []

    # 统一成 MemoryItem
    if isinstance(raw[0], dict):
        items = [
            MemoryItem(
                content=str(r.get("content", "")),
                score=float(r.get("score", 0.0)),
                kind=str(r.get("kind", "")),
                timestamp=float(r.get("timestamp", 0.0)),
            )
            for r in raw
        ]
    else:
        items = MemoryGate.to_items([str(r) for r in raw])

    filtered = gate.gate(items)
    return [item.content for item in filtered]