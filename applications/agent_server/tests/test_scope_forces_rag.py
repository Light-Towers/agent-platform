# -*- coding: utf-8 -*-
"""选库只压 direct、不压 sql/search/mcp（ADR 00XX）。纯函数测试，零 LLM/IO。"""
from __future__ import annotations

from agent_server.planners.deterministic import apply_kb_scope


def test_selected_kb_turns_direct_into_rag():
    assert apply_kb_scope("direct", "通用常识", "kb_test") == (
        "rag", "通用常识；已选知识库，direct 改判 rag"
    )


def test_selected_kb_preserves_explicit_capabilities():
    """明确能力（sql/search/mcp/code_execution）即使选了库也不覆盖。"""
    for route in ("sql", "search", "mcp", "code_execution"):
        assert apply_kb_scope(route, "r", "kb_test") == (route, "r")


def test_no_kb_keeps_direct():
    assert apply_kb_scope("direct", "r", "") == ("direct", "r")
