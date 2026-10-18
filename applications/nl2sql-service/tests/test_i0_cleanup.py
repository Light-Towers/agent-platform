# -*- coding: utf-8 -*-
"""I0 一行修清理 + S-5 LLM 超时用例（2026-10-18）。

钉三件事：
1. 5 个死 prompt 文件（3 extend + 2 filter，全服务 grep 零引用）已删，
   `prompts/` 只剩两个在用的模板——S-6 的"单请求最多 7 次 LLM 调用"口径
   以此为准（R14 已把 10 改为 7）；
2. `.env.example` 的 RERANK_* 死键整族删除（S-9：文档化了不存在的端点）；
3. `LLMClient.invoke` 消费 `llm_timeout`：超时返回空串（既有降级语义），
   不再无限期持有请求（S-5）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from nl2sql_service.agent.llm import LLMClient

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "nl2sql_service" / "prompts"
_DEAD_PROMPTS = (
    "extend_keywords_for_column_recall.prompt",
    "extend_keywords_for_metric_recall.prompt",
    "extend_keywords_for_value_recall.prompt",
    "filter_metric_info.prompt",
    "filter_table_info.prompt",
)


def test_dead_prompt_files_removed():
    for name in _DEAD_PROMPTS:
        assert not (_PROMPTS_DIR / name).exists(), f"死 prompt 未删: {name}"
    live = sorted(p.name for p in _PROMPTS_DIR.glob("*.prompt"))
    assert live == ["answer.prompt", "correct_sql.prompt", "generate_sql.prompt"], f"prompts 目录异常: {live}"


def test_env_template_rerank_keys_are_marked_as_not_consumed():
    """S-9 定性修正：键保留（继承字段 + 模板门禁要求可查），但必须注明本服务不消费。"""
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "RERANK_ENABLED=false" in text
    assert "nl2sql-service 自己不消费" in text, "RERANK 段必须注明归属，否则误导部署"


async def test_llm_invoke_times_out_instead_of_hanging():
    """S-5：llm_timeout 必须被 invoke 消费；超时走既有降级（空串），不抛异常。"""
    client = LLMClient(api_key="k", timeout=0.05)

    async def _slow(prompt: str) -> str:
        await asyncio.sleep(1.0)
        return "late"

    client._invoke = _slow  # type: ignore[method-assign]
    started = asyncio.get_running_loop().time()
    assert await client.invoke("x") == ""
    assert asyncio.get_running_loop().time() - started < 0.5, "超时未生效，请求被挂起"


async def test_llm_invoke_returns_content_within_timeout():
    client = LLMClient(api_key="k", timeout=1.0)

    async def _fast(prompt: str) -> str:
        return "SELECT 1"

    client._invoke = _fast  # type: ignore[method-assign]
    assert await client.invoke("x") == "SELECT 1"
