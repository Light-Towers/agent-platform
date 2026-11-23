"""富回答契约测试：字段形状 / 向后兼容 / 图片 URL 白名单（安全反证）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from shared_schemas import (
    Citation,
    ImageRef,
    QueryResponse,
    RichAnswer,
    Source,
    is_allowed_image_url,
)


class TestRichAnswerShape:
    def test_defaults_empty_collections(self):
        rich = RichAnswer(answer="答案")
        assert rich.answer == "答案"
        assert rich.sources == []
        assert rich.citations == []
        assert rich.images == []

    def test_round_trip(self):
        rich = RichAnswer(
            answer="见下图",
            sources=[Source(type="knowledge", name="安全规范.md", source_doc="安全规范.md")],
            citations=[Citation(
                source=Source(type="knowledge", name="安全规范.md"),
                chunk_id="c-1",
                heading="玻璃材料",
                snippet="钢化玻璃 8mm",
            )],
            images=[ImageRef(url="https://minio/kb/img_001.png", caption="展台结构")],
        )
        dumped = rich.model_dump()
        assert RichAnswer.model_validate(dumped) == rich

    def test_source_type_rejects_unknown(self):
        with pytest.raises(ValidationError):
            Source(type="unknown", name="x")


class TestQueryResponseCompat:
    def test_rich_is_optional_and_defaults_none(self):
        resp = QueryResponse(answer="答案")
        assert resp.rich is None

    def test_rich_round_trip(self):
        resp = QueryResponse(answer="答案", rich=RichAnswer(answer="答案", images=[
            ImageRef(url="http://minio/img.png")
        ]))
        assert QueryResponse.model_validate(resp.model_dump()).rich.images[0].url == "http://minio/img.png"


class TestImageRefSchemeGuard:
    """契约层硬约束：任何构造点都无法塞入伪协议（XSS 第一道闸）。"""

    @pytest.mark.parametrize("bad", [
        "javascript:alert(1)",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "//minio/img.png",  # 无 scheme
        "",
    ])
    def test_dangerous_schemes_rejected(self, bad):
        with pytest.raises(ValidationError):
            ImageRef(url=bad)

    @pytest.mark.parametrize("good", [
        "http://minio:9000/kb/img.png",
        "https://kb.internal/images/a.webp",
    ])
    def test_http_https_accepted(self, good):
        assert ImageRef(url=good).url == good


class TestImageUrlAllowlist:
    """``is_allowed_image_url`` 必须能咬：危险 shape 拒绝、可信 shape 放行、空表 fail-closed。"""

    def test_exact_host(self):
        assert is_allowed_image_url("http://minio:9000/kb/a.png", ["minio"])

    def test_subdomain(self):
        assert is_allowed_image_url("https://img.kb.internal/a.png", ["kb.internal"])

    def test_empty_allowlist_denies_all(self):
        assert is_allowed_image_url("http://minio/a.png", []) is False

    def test_untrusted_host_denied(self):
        assert is_allowed_image_url("https://evil.example/a.png", ["minio"]) is False

    def test_suffix_confusion_denied(self):
        # minio.evil.com / notminio.com 都不是白名单项 minio 的子域（防后缀混淆绕过）
        assert is_allowed_image_url("https://minio.evil.com/a.png", ["minio"]) is False
        assert is_allowed_image_url("https://notminio.com/a.png", ["minio"]) is False

    @pytest.mark.parametrize("bad", [
        "javascript:alert(1)",
        "data:image/png;base64,AAA",
        "file:///etc/passwd",
        "ftp://minio/a.png",
    ])
    def test_non_http_scheme_denied(self, bad):
        assert is_allowed_image_url(bad, ["minio"]) is False

    def test_missing_host_denied(self):
        assert is_allowed_image_url("http:///a.png", ["minio"]) is False

    def test_case_insensitive_host(self):
        assert is_allowed_image_url("http://MINIO:9000/a.png", ["minio"])
