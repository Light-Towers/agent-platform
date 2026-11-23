"""富回答契约（图片 / 引用 / 来源）——全平台唯一真相源。

背景（plan-image-citation-e2e-2026-11-23）：此前富信息没有统一契约，KS 私有 SSE、
会展 SkillResult、平台 RAG 各造一套形状，跨边界转换时图片/引用被丢弃。本模块把
``Source / Citation / ImageRef / RichAnswer`` 定义在一处，全端（agent_server adapter、
前端 SSE、会展 skill）只认这一套。

安全纪律：``ImageRef.url`` 在契约层强制 http(s) scheme（杜绝 ``javascript:`` /
``data:`` 伪协议，零 v-html 的前提下这是 XSS 的第一道闸）；域名级白名单由服务端
adapter 用 :func:`is_allowed_image_url` 在构造前校验，前端渲染时二次校验（双保险）。
"""

from __future__ import annotations

from typing import Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

#: 图片 URL 只允许的 scheme。契约层硬约束，任何构造点都无法绕过。
_ALLOWED_IMAGE_SCHEMES = frozenset({"http", "https"})


def is_allowed_image_url(url: str, allowed_hosts: Sequence[str]) -> bool:
    """判断图片 URL 是否在可信域白名单内（服务端 adapter 构造前必调）。

    口径：
    - scheme 必须是 ``http`` / ``https``（与 ``ImageRef`` 的契约层校验同口径）；
    - host 必须精确命中白名单项，或是白名单项的子域（``a.example.com`` 命中 ``example.com``）；
    - ``allowed_hosts`` 为空 = 拒绝一切（fail-closed，部署必须显式配置可信域）；
    - 白名单项按 **hostname** 写（不含端口/协议），如 ``minio`` / ``kb.internal``。

    :param url: 待校验的图片 URL
    :param allowed_hosts: 可信主机名白名单（不含端口）
    :return: 是否允许
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in _ALLOWED_IMAGE_SCHEMES:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    for allowed in allowed_hosts:
        allowed_key = allowed.strip().lower()
        if not allowed_key:
            continue
        if host == allowed_key or host.endswith("." + allowed_key):
            return True
    return False


class Source(BaseModel):
    """回答引用的来源（归一：会展 Source + 平台 RAG source）。"""

    type: Literal["knowledge", "table", "api", "web"]
    name: str = Field(..., description="文档名 / 表名 / 端点名")
    source_doc: str | None = Field(None, description="知识库文档粒度（对应 source_doc）")
    as_of: str | None = Field(None, description="数据时点")


class Citation(BaseModel):
    """结构化引用（归一：会展 Citation + 平台 RAG 证据）。"""

    source: Source
    chunk_id: str | None = Field(None, description="命中的切片 ID")
    heading: str | None = Field(None, description="命中的章节标题")
    snippet: str | None = Field(None, description="命中证据片段（引用卡片悬浮用）")


class ImageRef(BaseModel):
    """回答回显的图片引用（归一：KS image_urls）。

    ``url`` 在契约层强制 http(s)；域名白名单由 adapter 构造前用
    :func:`is_allowed_image_url` 校验（双保险的另一道在前端渲染）。
    """

    url: str = Field(..., description="过白名单的 http(s) 图片 URL")
    source_doc: str | None = Field(None, description="图片所属文档")
    caption: str | None = Field(None, description="Markdown alt 文本（图片摘要）")

    @field_validator("url")
    @classmethod
    def _require_http_scheme(cls, value: str) -> str:
        try:
            scheme = urlparse(value).scheme
        except ValueError as exc:  # 畸形 URL（如非法括号）当场拒绝
            raise ValueError("图片 URL 非法") from exc
        if scheme not in _ALLOWED_IMAGE_SCHEMES:
            raise ValueError("图片 URL 只接受 http/https scheme")
        return value


class RichAnswer(BaseModel):
    """统一富回答，是既有 ``answer`` 字符串契约的超集（可选字段，向后兼容）。"""

    answer: str = Field(..., description="自然语言回答（与 QueryResponse.answer 同源）")
    sources: list[Source] = Field(default_factory=list, description="回答涉及的来源")
    citations: list[Citation] = Field(default_factory=list, description="结构化引用")
    images: list[ImageRef] = Field(default_factory=list, description="回显图片（已过白名单）")


__all__ = [
    "Citation",
    "ImageRef",
    "RichAnswer",
    "Source",
    "is_allowed_image_url",
]
