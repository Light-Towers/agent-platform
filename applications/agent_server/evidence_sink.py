# -*- coding: utf-8 -*-
"""请求级结构化证据池（EvidenceSink）——让检索结构从源头旁路到 SSE 出口，不被拍平/压缩。

背景（plan-image-citation-e2e-2026-11-23 §2.2）：RAG 检索拿到的结构化 chunks
（``{id, source, heading, content, score}``）在 ``rag_query`` 里被拍平成 ``list[str]``，
会展 citations 在 ``deterministic._run_capability`` 里被丢弃。富信息要回显，必须
在「拍平/压缩之前」把这些结构旁路保存，供 SSE 出口的 adapter 消费。

跨 task 安全的关键（实取）：GraphPlanner 用 ``asyncio.gather`` 起子 task，Python 3.11
语义下子 task 的 ``ContextVar.set()`` **不回传**父 task。因此本模块的用法是：
**父 task（query_router._stream）先 ``bind_sink()`` 绑定一个可变池对象，子 task 只对该
对象 ``append``（改对象内部状态，不是重绑定 var）** —— 子 task 继承的是同一个对象引用，
父 task 读得到。``reset_sink(token)`` 必须放在 ``finally``，避免同 worker 上后续请求读到
上一轮的池。

依赖方向：app 层模块，rag.py / capabilities.py / query_router.py 都在 app 层互引，
不触及 ``agent-runtime → app`` 反向依赖红线。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceSink:
    """一次问答请求的结构化证据池（可变，仅供本请求 task 树写入）。"""

    rag_chunks: list[dict[str, Any]] = field(default_factory=list)
    exhibition_citations: list[dict[str, Any]] = field(default_factory=list)
    exhibition_sources: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.rag_chunks or self.exhibition_citations or self.exhibition_sources)


_current_sink: contextvars.ContextVar[EvidenceSink | None] = contextvars.ContextVar(
    "agent_server_evidence_sink", default=None
)


def bind_sink() -> tuple[EvidenceSink, contextvars.Token[EvidenceSink | None]]:
    """在请求 task 绑定一个新池，返回 ``(池, reset token)``。调用方须在 finally reset。"""
    sink = EvidenceSink()
    return sink, _current_sink.set(sink)


def reset_sink(token: contextvars.Token[EvidenceSink | None]) -> None:
    """复位到绑定前的 ContextVar 值（必须在 finally 调用）。"""
    _current_sink.reset(token)


def current_sink() -> EvidenceSink | None:
    """取当前请求的证据池；无绑定（后台任务 / 测试直调）时返回 None，写入方据此跳过。"""
    return _current_sink.get()


__all__ = ["EvidenceSink", "bind_sink", "current_sink", "reset_sink"]
