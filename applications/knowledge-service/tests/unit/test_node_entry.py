# -*- coding: utf-8 -*-
"""
node_entry 节点单元测试 —— 文件格式判断与解析开关设置。

覆盖：
- PDF / MD 原有格式不破坏
- DOCX / DOC / PPTX / PPT / XLSX / XLS 新增格式走 MinerU 链路
- 不支持格式不设置任何开关
- 空路径安全处理
- file_title 正确提取（去后缀纯名称）
"""

import pytest

from knowledge_service.import_process.agent.nodes.node_entry import node_entry
from knowledge_service.import_process.agent.state import create_default_state


def _run_entry(file_path: str):
    """辅助：用给定文件路径跑 node_entry，返回处理后的 state。"""
    state = create_default_state(task_id="test_entry", local_file_path=file_path)
    return node_entry(state)


class TestPdfFormat:
    def test_pdf_sets_pdf_read_enabled(self):
        state = _run_entry("万用表RS-12的使用.pdf")
        assert state["is_pdf_read_enabled"] is True
        assert state["pdf_path"] == "万用表RS-12的使用.pdf"
        assert state["is_md_read_enabled"] is False

    def test_pdf_file_title_extracted(self):
        state = _run_entry("2024中国进口博览会搭建商手册.pdf")
        assert state["file_title"] == "2024中国进口博览会搭建商手册"


class TestMdFormat:
    def test_md_sets_md_read_enabled(self):
        state = _run_entry("知识手册.md")
        assert state["is_md_read_enabled"] is True
        assert state["md_path"] == "知识手册.md"
        assert state["is_pdf_read_enabled"] is False

    def test_md_file_title_extracted(self):
        state = _run_entry("知识手册.md")
        assert state["file_title"] == "知识手册"


class TestMineruSupportedFormats:
    """DOCX/DOC/PPTX/PPT/XLSX/XLS 走 MinerU 解析链路（is_pdf_read_enabled=True）。"""

    @pytest.mark.parametrize("filename", [
        "参展协议.docx",
        "参展协议.doc",
        "建设方案.pptx",
        "顶层设计.ppt",
        "展商名单.xlsx",
        "进度表.xls",
    ])
    def test_mineru_format_sets_pdf_read_enabled(self, filename):
        state = _run_entry(filename)
        assert state["is_pdf_read_enabled"] is True
        assert state["pdf_path"] == filename
        assert state["is_md_read_enabled"] is False

    def test_docx_file_title_extracted(self):
        state = _run_entry("0506第十一届博博会参展协议（博物馆）.docx")
        assert state["file_title"] == "0506第十一届博博会参展协议（博物馆）"

    def test_pptx_file_title_extracted(self):
        state = _run_entry("会展中心数字化提升规划方案-v7.1.pptx")
        assert state["file_title"] == "会展中心数字化提升规划方案-v7.1"


class TestUnsupportedFormat:
    def test_txt_does_not_set_any_switch(self):
        state = _run_entry("笔记.txt")
        assert state["is_pdf_read_enabled"] is False
        assert state["is_md_read_enabled"] is False
        assert state["pdf_path"] == ""
        assert state["md_path"] == ""

    def test_csv_does_not_set_any_switch(self):
        state = _run_entry("参展商数据.csv")
        assert state["is_pdf_read_enabled"] is False
        assert state["is_md_read_enabled"] is False

    def test_json_does_not_set_any_switch(self):
        state = _run_entry("config.json")
        assert state["is_pdf_read_enabled"] is False
        assert state["is_md_read_enabled"] is False


class TestEmptyPath:
    def test_empty_path_does_not_crash(self):
        state = create_default_state(task_id="test_empty", local_file_path="")
        result = node_entry(state)
        assert result is not None
        assert result["is_pdf_read_enabled"] is False
        assert result["is_md_read_enabled"] is False
