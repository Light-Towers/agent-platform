from app.rag.chunker import split_markdown


def test_heading_preserved():
    text = "# 概述\n\n这是第一段。\n\n## 细节\n\n这是第二段。"
    chunks = split_markdown(text, max_chars=400)
    assert chunks[0].heading == "概述"
    assert chunks[1].heading == "细节"
    assert "第一段" in chunks[0].text


def test_paragraphs_merged_within_limit():
    text = "## 节\n\n短段落一。\n\n短段落二。"
    chunks = split_markdown(text, max_chars=400)
    assert len(chunks) == 1
    assert "短段落一" in chunks[0].text and "短段落二" in chunks[0].text


def test_long_paragraph_window_split():
    text = "## 长文\n\n" + "字" * 1000
    chunks = split_markdown(text, max_chars=300, overlap=50)
    assert len(chunks) >= 4
    assert all(len(c.text) <= 300 for c in chunks)


def test_empty_text():
    assert split_markdown("") == []
    assert split_markdown("   \n\n  ") == []
