# -*- coding: utf-8 -*-
"""统一意图识别的数据模型（框架无关内核原语）。

双轨收敛（TB-9）：deepagents 成熟的 L1+L2 意图识别下沉到内核，
app 与 deepagents 共用同一套标签与结果类型，消除两套不兼容标签
（deepagents: text_to_sql/rag_knowledge/customer_service/web_search/chitchat；
app: search/rag/sql/direct/mcp）带来的映射漂移。

``IntentLabel`` 是统一标签枚举，合并双轨语义：
- ``TEXT_TO_SQL``   ↔ deepagents text_to_sql / app sql
- ``RAG_KNOWLEDGE`` ↔ deepagents rag_knowledge / app rag
- ``WEB_SEARCH``    ↔ deepagents web_search / app search
- ``CUSTOMER_SERVICE`` ↔ deepagents customer_service（app 无对应子链路）
- ``CHITCHAT``      ↔ deepagents chitchat（app 归并到 direct）
- ``DIRECT``        ↔ app direct / 通用直答（含 chitchat 兜底）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# L1 直出阈值：L1 置信度 >= 该值直接采用，跳过 L2。
L1_THRESHOLD = 0.8
# clarify 反问阈值：最终置信度 < 该值需要向用户反问澄清。
CLARIFY_THRESHOLD = 0.5


class IntentLabel(str, Enum):
    """统一意图标签（合并 deepagents 与 app 双轨语义）。"""

    TEXT_TO_SQL = "text_to_sql"
    RAG_KNOWLEDGE = "rag_knowledge"
    WEB_SEARCH = "web_search"
    CUSTOMER_SERVICE = "customer_service"
    CHITCHAT = "chitchat"
    DIRECT = "direct"

    @classmethod
    def from_str(cls, value: str) -> "IntentLabel":
        """从字符串解析；未知标签归并到 DIRECT（绝不让标签穿透为非法值）。"""
        try:
            return cls(value)
        except ValueError:
            return cls.DIRECT


@dataclass
class IntentCandidate:
    """单个意图候选。"""

    intent: IntentLabel
    confidence: float


@dataclass
class IntentResult:
    """意图识别结果（L1 + L2 合并后）。

    Attributes:
        primary: 最终判定的主意图。
        confidence: 主意图置信度（0-1）。
        candidates: L1 top-K 候选（含置信度）。
        source: 判定来源（``l1`` / ``l2`` / ``l1_keyword`` / ``l1_fallback``）。
        need_clarify: 是否需反问澄清（置信度过低）。
    """

    primary: IntentLabel
    confidence: float
    candidates: list[IntentCandidate] = field(default_factory=list)
    source: str = "l1"
    need_clarify: bool = False

    @property
    def primary_value(self) -> str:
        """主意图字符串值（便于与历史字符串型调用方兼容）。"""
        return self.primary.value

    def to_dict(self) -> dict[str, Any]:
        """转 dict（兼容 deepagents 旧 ``classify_with_fallback`` 返回结构）。"""
        return {
            "primary": {"intent": self.primary.value, "confidence": self.confidence},
            "candidates": [{"intent": c.intent.value, "confidence": c.confidence} for c in self.candidates],
            "source": self.source,
            "need_clarify": self.need_clarify,
        }
