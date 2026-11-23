# -*- coding: utf-8 -*-
"""富回答 adapter（单一实现）——请求证据池 + answer → ``RichAnswer``。

plan-image-citation-e2e-2026-11-23 §2.3：三路输入（RAG chunks / 会展 citations+sources /
图片链接）只在本模块归一成 shared-schemas 的 ``RichAnswer``，query_router 不再自己拼
图片/引用逻辑。这是「单一真相源 + 单一转换点」的落地，新增富信息类型也只改这里。

安全：图片 URL 在构造 ``ImageRef`` 前经 :func:`is_allowed_image_url` 域名白名单校验，
``ImageRef`` 自身再做 scheme 硬校验（契约层双保险）；白名单为空 = 拒一切（fail-closed）。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError
from shared_schemas import Citation, ImageRef, RichAnswer, Source, is_allowed_image_url

from agent_server.config import get_settings
from agent_server.evidence_sink import EvidenceSink

#: Markdown 图片语法 ``![alt](url)``（导入时 node_md_img 写回的形状）。
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def allowed_image_hosts() -> list[str]:
    """读部署配置的图片可信主机名列表（逗号分隔；空 = 拒一切，fail-closed）。"""
    raw = get_settings().rich_image_allowed_hosts or ""
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _rag_citations(chunks: list[dict[str, Any]]) -> list[Citation]:
    """RAG 检索结构 → 统一 Citation（以 chunk 的 ``id`` 作 chunk_id，实取无 doc_id）。"""
    out: list[Citation] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        source_doc = str(chunk.get("source") or "未知文档")
        snippet = str(chunk.get("content") or "")[:200] or None
        out.append(Citation(
            source=Source(type="knowledge", name=source_doc, source_doc=source_doc),
            chunk_id=str(chunk["id"]) if chunk.get("id") is not None else None,
            heading=chunk.get("heading") or None,
            snippet=snippet,
        ))
    return out


def _rag_sources(chunks: list[dict[str, Any]]) -> list[Source]:
    """RAG 命中的文档名去重后作为 knowledge 型 Source（回答涉及的文档清单）。"""
    seen: set[str] = set()
    out: list[Source] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        name = str(chunk.get("source") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(Source(type="knowledge", name=name, source_doc=name))
    return out


def _extract_images(chunks: list[dict[str, Any]], hosts: list[str]) -> list[ImageRef]:
    """从 chunk 正文的 Markdown 图片链接提取图片，逐条过域名白名单 + 契约层 scheme 校验。"""
    out: list[ImageRef] = []
    seen: set[str] = set()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        content = chunk.get("content") or ""
        source_doc = chunk.get("source") or None
        if not isinstance(content, str):
            continue
        for match in _IMAGE_RE.finditer(content):
            caption, url = match.group(1).strip(), match.group(2).strip()
            if url in seen:
                continue
            seen.add(url)
            if not is_allowed_image_url(url, hosts):
                continue  # 外域/伪协议 URL 直接丢弃，绝不回显
            try:
                out.append(ImageRef(url=url, source_doc=source_doc, caption=caption or None))
            except ValidationError:
                continue  # scheme 校验兜底（is_allowed 已挡，双保险）
    return out


def _exhibition_citations(raw: list[Any]) -> list[Citation]:
    """会展 ``Citation{knowledge_id,chunk_id,scope}`` → 统一 Citation。"""
    out: list[Citation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("knowledge_id") or "未知来源")
        out.append(Citation(
            source=Source(type="knowledge", name=name, source_doc=name),
            chunk_id=item.get("chunk_id"),
            snippet=item.get("scope") or None,
        ))
    return out


def _exhibition_sources(raw: list[Any]) -> list[Source]:
    """会展 ``Source{type,name,as_of}`` → 统一 Source（type 收窄到契约允许的 4 类）。"""
    out: list[Source] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "api")
        if typ not in ("knowledge", "table", "api", "web"):
            typ = "api"
        out.append(Source(
            type=typ,  # type: ignore[arg-type] — 上方已收窄
            name=str(item.get("name") or "未知来源"),
            as_of=item.get("as_of"),
        ))
    return out


def to_rich_answer(answer: str, sink: EvidenceSink | None, *, hosts: list[str] | None = None) -> RichAnswer | None:
    """把请求证据池归一成富回答；无任何富信息时返回 None（不发多余事件）。

    :param answer: 本轮最终回答文本（富回答与 answer 同源）
    :param sink: 请求级证据池；None/空池 → 返回 None
    :param hosts: 图片白名单（测试可注入）；None = 从配置读取
    """
    if sink is None or sink.is_empty():
        return None
    allowed = hosts if hosts is not None else allowed_image_hosts()
    citations = _rag_citations(sink.rag_chunks) + _exhibition_citations(sink.exhibition_citations)
    sources = _rag_sources(sink.rag_chunks) + _exhibition_sources(sink.exhibition_sources)
    images = _extract_images(sink.rag_chunks, allowed)
    if not (citations or sources or images):
        return None
    return RichAnswer(answer=answer, sources=sources, citations=citations, images=images)


__all__ = ["allowed_image_hosts", "to_rich_answer"]
