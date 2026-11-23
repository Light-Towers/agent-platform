# -*- coding: utf-8 -*-
"""刀 2 切分策略单测（零外部依赖，直接调纯函数）。

钉四件事：
1. resolve_split_config 从 state 读策略/overlap，非法回落 title；
2. _split_long_section 的 overlap 生效且收敛到 < available_len；
3. line 策略表格整块保留（表头随块、no_split 标记）；
4. _merge_short_sections 的 max 上限截断（F-2：499+499 不合并）。
"""
from __future__ import annotations

from knowledge_service.import_process.agent.nodes import node_document_split as nds


def test_resolve_split_config_defaults_and_override() -> None:
    # M-2：缺省回落到 DEFAULT_CHUNK_CONFIG 单一真相源（title / 2000×10%=200）
    assert nds.resolve_split_config({}) == {"split_strategy": "title", "chunk_overlap": 200}
    assert nds.resolve_split_config({
        "split_strategy": "char", "chunk_overlap": 200,
    }) == {"split_strategy": "char", "chunk_overlap": 200}
    # 非法策略回落
    assert nds.resolve_split_config({"split_strategy": "bogus"})["split_strategy"] == "title"
    # overlap 非数值回落到默认 200
    assert nds.resolve_split_config({"chunk_overlap": "x"})["chunk_overlap"] == 200


def test_split_long_section_overlap_applied() -> None:
    # 构造一个超长章节，验证二次切分器用了 overlap（相邻块有重叠字符）
    body = ("这是第一段内容。" * 60) + "\n\n" + ("这是第二段内容。" * 60)
    section = {"title": "章", "content": body, "file_title": "f"}
    parts = nds._split_long_section(section, max_length=200, chunk_overlap=50)
    assert len(parts) >= 2
    # 相邻块应共享部分内容：取第一块尾部片段是否出现在第二块
    head = parts[0]["content"]
    nxt = parts[1]["content"]
    assert head[-20:] in nxt or any(
        head[-20:] in p["content"] for p in parts[1:]
    ), "重叠字符未出现在后续块"
    # 标题前缀保留
    assert all(p["content"].startswith("章") for p in parts)


def test_line_strategy_keeps_table_intact() -> None:
    md = (
        "# 标题\n\n正文段落一。\n\n"
        "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
        "正文段落二。\n"
    )
    sections, _, _ = nds.step_2_split_by_lines(md, "f")
    table_sections = [s for s in sections if s.get("no_split")]
    assert len(table_sections) == 1
    tbl = table_sections[0]["content"]
    assert "| 列A | 列B |" in tbl       # 表头
    assert "| 1 | 2 |" in tbl and "| 3 | 4 |" in tbl  # 所有数据行同块
    assert "正文段落" not in tbl        # 表格块不含正文


def test_merge_short_sections_respects_max_cap() -> None:
    # F-2 的钉子用例：两块各 499、min=500、max=800 → 不合并（合并后 ~1000 > 800）
    a = {"content": "甲" * 499, "parent_title": "章", "part": 1}
    b = {"content": "乙" * 499, "parent_title": "章", "part": 2}
    merged = nds._merge_short_sections([a, b], min_length=500, max_length=800, overlap=0)
    assert len(merged) == 2  # 未合并
    # 对照：不设 max 上限（max_length=0）时会合并成 1 块（旧行为）
    merged_old = nds._merge_short_sections(
        [dict(a), dict(b)], min_length=500, max_length=0, overlap=0
    )
    assert len(merged_old) == 1


def test_char_strategy_is_single_section() -> None:
    sections, title_count, _ = nds.step_2_split_by_chars("# 标题\n正文", "f")
    assert len(sections) == 1
    assert title_count == 0
    assert sections[0]["content"] == "# 标题\n正文"


def test_merge_cap_accounts_for_overlap() -> None:
    """L-3：合并上限判断把 overlap 计入——399+399+overlap(4)+2 略超 800 时不合并。"""
    a = {"content": "甲" * 399, "parent_title": "章", "part": 1}
    b = {"content": "乙" * 399, "parent_title": "章", "part": 2}
    # 399+399+2 = 800 恰好不超；overlap=4 后 804>800 ⇒ 不合并
    merged = nds._merge_short_sections([dict(a), dict(b)], min_length=500, max_length=800, overlap=4)
    assert len(merged) == 2


def test_summary_reports_effective_config_and_warnings() -> None:
    """上传后读数增强：summary 带本次生效配置 + 切分告警（用户所见即所发生）。"""
    summary = nds.step_5b_collect_summary(
        "# 标题\n正文", 3,
        [{"title": "标题", "content": "正文", "part": 1}],
        effective_config={"split_strategy": "char", "max_content_length": 1000, "chunk_overlap": 100},
        warnings=["表格块 XX 超过上限，按字符切"],
    )
    assert summary["effective_config"]["strategy_label"] == "按字符数切分"
    assert summary["effective_config"]["max_content_length"] == 1000
    assert summary["effective_config"]["chunk_overlap"] == 100
    assert "表格块" in summary["warnings"][0]


def test_summary_requires_effective_config_and_warnings() -> None:
    """effective_config/warnings 是必填参数——漏传由 TypeError 直接暴露，不静默给空。"""
    import pytest
    with pytest.raises(TypeError):
        nds.step_5b_collect_summary("# 标题\n正文", 3, [{"content": "正文"}])  # type: ignore[call-arg]


def test_line_split_collects_oversized_table_warning() -> None:
    """超长表格降级时把告警写入 warnings 列表（供 summary 回显）。"""
    big_row = "| " + "数据" * 10 + " |\n"
    table = "| 列A |\n| --- |\n" + big_row * 4000
    warnings: list = []
    nds.step_2_split_by_lines(table, "f", warnings)
    assert any("超过上限" in w for w in warnings)


def test_oversized_table_drops_no_split() -> None:
    """M-3/L-3：超长表格不设 no_split（落到字符切分），避免黑洞块。"""
    big_row = "| " + "数据" * 10 + " |\n"
    table = "| 列A |\n| --- |\n" + big_row * 4000  # 远超 MAX_TABLE_BLOCK_CHARS
    sections, _, _ = nds.step_2_split_by_lines(table, "f")
    assert sections
    assert not any(s.get("no_split") for s in sections), "超长表格不应标记 no_split"
