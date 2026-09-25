"""意图识别结果 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IntentCandidate(BaseModel):
    """单个意图候选（L1 top-K 输出）。"""

    intent: str = Field(..., description="意图标签")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")


class IntentResult(BaseModel):
    """意图识别结果（L1+L2 合并输出）。"""

    primary: IntentCandidate = Field(..., description="最终选定的意图")
    candidates: list[IntentCandidate] = Field(default_factory=list, description="L1 top-K 候选")
    source: str = Field("l1", description="决策来源：l1（L1 直出）/ l2（L2 LLM 细判）/ fallback")
    rewritten_query: str | None = Field(None, description="改写后的 query（指代消解+子问题分解）")
