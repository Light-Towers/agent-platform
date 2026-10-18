"""golden loader（run_golden 的纯函数部分）：解析 + 校验形状。"""

from __future__ import annotations

import json

import pytest
from nl2sql_service.scripts.run_golden import _load_golden


def test_load_golden_parses_and_skips_comments(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text(
        "\n".join(
            [
                "# 注释行",
                "",
                json.dumps({"id": "g01", "question": "q1", "expect_tables": ["orders"]}),
                json.dumps({"id": "g02", "question": "q2"}),
            ]
        ),
        encoding="utf-8",
    )
    cases = _load_golden(str(p))
    assert [c["id"] for c in cases] == ["g01", "g02"]
    assert cases[0]["expect_tables"] == ["orders"]


def test_load_golden_rejects_bad_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _load_golden(str(p))


def test_load_golden_requires_question(tmp_path):
    p = tmp_path / "noq.jsonl"
    p.write_text(json.dumps({"id": "g01"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _load_golden(str(p))
