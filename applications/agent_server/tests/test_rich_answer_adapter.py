# -*- coding: utf-8 -*-
"""富回答 adapter 测试：三路归一 + 图片白名单 + scheme 兜底 + 去重。"""

from agent_server.evidence_sink import EvidenceSink
from agent_server.rich_answer_adapter import to_rich_answer

_HOSTS = ["minio"]


def _chunks():
    return [
        {"id": "c-1", "source": "安全规范.md", "heading": "玻璃材料",
         "content": "钢化玻璃 8mm 见 ![展台结构](http://minio:9000/kb/a.png)", "score": 0.9},
        {"id": "c-2", "source": "安全规范.md", "heading": None,
         "content": "外域 ![evil](https://evil.example/x.png)", "score": 0.8},
        {"id": "c-3", "source": "搭建手册.md", "heading": "吊点",
         "content": "见 ![吊点](http://minio:9000/kb/b.webp)", "score": 0.7},
    ]


def test_rag_chunks_to_rich_answer():
    rich = to_rich_answer("答案", EvidenceSink(rag_chunks=_chunks()), hosts=_HOSTS)
    assert rich is not None
    assert rich.answer == "答案"
    assert len(rich.citations) == 3
    assert rich.citations[0].chunk_id == "c-1"
    assert rich.citations[0].source.name == "安全规范.md"
    assert rich.citations[0].snippet is not None
    # 图片：2 张白名单内，外域 evil 被拒
    assert [i.url for i in rich.images] == [
        "http://minio:9000/kb/a.png", "http://minio:9000/kb/b.webp",
    ]
    assert rich.images[0].caption == "展台结构"
    assert rich.images[0].source_doc == "安全规范.md"
    # sources 按文档名去重
    assert [s.name for s in rich.sources] == ["安全规范.md", "搭建手册.md"]


def test_empty_sink_returns_none():
    assert to_rich_answer("答案", EvidenceSink(), hosts=_HOSTS) is None
    assert to_rich_answer("答案", None, hosts=_HOSTS) is None


def test_empty_hosts_denies_all_images_but_keeps_citations():
    rich = to_rich_answer("x", EvidenceSink(rag_chunks=_chunks()), hosts=[])
    assert rich is not None
    assert rich.images == []
    assert len(rich.citations) == 3


def test_image_dedup_and_scheme_guard():
    chunks = [{"id": "1", "source": "d", "heading": None,
               "content": "![a](http://minio/a.png) ![b](http://minio/a.png) "
                          "![c](javascript:alert(1)) ![d](data:image/png;base64,AAA)"}]
    rich = to_rich_answer("x", EvidenceSink(rag_chunks=chunks), hosts=_HOSTS)
    assert len(rich.images) == 1  # 同 URL 去重；伪协议全拒


def test_exhibition_citations_and_sources_normalized():
    sink = EvidenceSink(
        exhibition_citations=[{"knowledge_id": "kb-1", "chunk_id": "ck-9", "scope": "展期"}],
        exhibition_sources=[{"type": "table", "name": "t_venue", "as_of": "2026-11"}],
    )
    rich = to_rich_answer("答案", sink, hosts=_HOSTS)
    assert rich.citations[0].source.name == "kb-1"
    assert rich.citations[0].chunk_id == "ck-9"
    assert rich.citations[0].snippet == "展期"
    assert rich.sources[0].type == "table"
    assert rich.sources[0].as_of == "2026-11"


def test_unknown_source_type_falls_back_to_api():
    sink = EvidenceSink(exhibition_sources=[{"type": "weird", "name": "x"}])
    rich = to_rich_answer("x", sink, hosts=_HOSTS)
    assert rich.sources[0].type == "api"
