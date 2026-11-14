# -*- coding: utf-8 -*-
"""node_pdf_to_md.step_1_validate_paths 单元测试（M8：导入节点缺单测）。

只覆盖不依赖外部 MinerU API 的纯路径校验逻辑（step_1）；
step_2+（上传 / 轮询 / 解压）需真实 MinerU，归 integration 套件。
"""

import pytest

from knowledge_service.import_process.agent.nodes.node_pdf_to_md import step_1_validate_paths


def test_step1_missing_pdf_path_raises():
    with pytest.raises(ValueError):
        step_1_validate_paths({"pdf_path": "   ", "local_dir": "/tmp/out"})


def test_step1_missing_local_dir_raises():
    with pytest.raises(ValueError):
        step_1_validate_paths({"pdf_path": "/tmp/a.pdf", "local_dir": ""})


def test_step1_pdf_not_exist_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        step_1_validate_paths(
            {"pdf_path": str(tmp_path / "nope.pdf"), "local_dir": str(tmp_path / "out")}
        )


def test_step1_pdf_is_directory_raises(tmp_path):
    d = tmp_path / "sub"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        step_1_validate_paths({"pdf_path": str(d), "local_dir": str(tmp_path / "out")})


def test_step1_creates_output_dir(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("dummy")
    out = tmp_path / "nested" / "out"
    pdf_obj, out_obj = step_1_validate_paths(
        {"pdf_path": str(pdf), "local_dir": str(out)}
    )
    assert pdf_obj.exists() and pdf_obj.is_file()
    assert out_obj.exists() and out_obj.is_dir()
