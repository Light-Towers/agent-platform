# -*- coding: utf-8 -*-
"""语义缓存准入判据单测（纯函数，零 HTTP/planner 依赖）。

回归 2026-11-19：RAG 零证据的否定答案不能入缓存，否则知识库补文档后
仍命中旧的"找不到"答案；direct 闲聊无 evidence 属正常，应照常缓存。
"""
from __future__ import annotations

from agent_server.api.query_router import should_cache_answer


def test_rag_without_evidence_not_cached():
    """RAG 路由 + 零证据（否定答案）→ 不缓存。这是本次 bug 的核心。"""
    assert should_cache_answer("现有证据为无，无法回答", True, True, False) is False


def test_rag_with_evidence_cached():
    """RAG 路由 + 有证据 → 正常缓存。"""
    assert should_cache_answer("根据证据，答案是…", True, True, True) is True


def test_direct_chitchat_cached():
    """direct 闲聊无 evidence → 照常缓存（不被规则误伤）。"""
    assert should_cache_answer("你好，我是助手", True, False, False) is True


def test_empty_answer_not_cached():
    """空答案一律不缓存。"""
    assert should_cache_answer("", True, False, False) is False


def test_disabled_cache_never_writes():
    assert should_cache_answer("答案", False, True, True) is False
