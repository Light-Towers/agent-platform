# -*- coding: utf-8 -*-
"""
test_make_adjudication_ui.py —— 裁决集标注页生成器（Phase C2 录入辅助）的纯函数 + 薄壳单测。

覆盖：
- embed_json：内联进 <script> 时转义 < >，内容里的 "</script>" 被中和、且能 json.loads 回原值；
- render_html：注入条数正确、包含全部 qid、真实闭合 </script> 恰好 1 个（防内容提前破页）；
- main：从 tmp 模板产 HTML（返回 0）；模板缺失 / 行缺 qid → 返回 1（不产半成品）。

不连服务、不调 LLM，纯本地字符串/文件操作。
"""

import json
import re
from pathlib import Path

from eval.make_adjudication_ui import embed_json, load_rows, main, render_html


def _row(qid="g001", **over):
    rec = {
        "qid": qid,
        "query": "什么是观众人数？",
        "context": "## 532 观众人数 说明书正文……",
        "answer": "答案正文：观众人数指……",
        "reference": "参考回答：进入展览场所的观众数量。",
        "human": {"faithfulness": None, "correctness": None},
    }
    rec.update(over)
    return rec


def _write_template(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ---------------------------------------------------------------------------
# embed_json
# ---------------------------------------------------------------------------
def test_embed_json_escapes_angle_brackets():
    out = embed_json({"x": "</script><script>alert(1)</script>"})
    assert "<" not in out and ">" not in out
    # 转义为 \u003c/\u003e 仍是合法 JSON，可原样解回。
    assert json.loads(out)["x"] == "</script><script>alert(1)</script>"


def test_embed_json_roundtrip_nonascii():
    payload = [{"qid": "g001", "context": "观众人数"}]
    assert json.loads(embed_json(payload)) == payload


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------
def test_render_html_contains_all_qids_and_count():
    rows = [_row("g001"), _row("g002"), _row("g003")]
    html = render_html(rows)
    for r in rows:
        assert r["qid"] in html
    assert "0/3" in html  # 进度条初始 total


def test_render_html_neutralizes_injected_script_tag():
    # 正文塞入 </script> 试图提前闭合脚本块 → 转义后全文只剩我们模板自身那 1 个闭合标签。
    rows = [_row("g001", context="恶意 </script><script>alert(1)</script> 正文")]
    html = render_html(rows)
    assert html.count("</" + "script>") == 1


def test_render_html_embedded_data_is_parseable():
    rows = [_row("g001"), _row("g002")]
    html = render_html(rows)
    m = re.search(r"const DATA = (\[.*?\]);", html, re.S)
    assert m is not None
    parsed = json.loads(m.group(1))
    assert [r["qid"] for r in parsed] == ["g001", "g002"]
    # 保留 mode2 需要的字段（回填前 human 为 null）。
    assert parsed[0]["human"] == {"faithfulness": None, "correctness": None}


# ---------------------------------------------------------------------------
# load_rows
# ---------------------------------------------------------------------------
def test_load_rows_skips_blank_lines(tmp_path: Path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(_row("g001"), ensure_ascii=False) + "\n\n", encoding="utf-8")
    assert [r["qid"] for r in load_rows(p)] == ["g001"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def test_main_produces_html(tmp_path: Path):
    tpl = tmp_path / "adjudication_template.jsonl"
    _write_template(tpl, [_row("g001"), _row("g002")])
    out = tmp_path / "adjudication_ui.html"
    rc = main(["--template", str(tpl), "--out", str(out)])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "g001" in html and "g002" in html


def test_main_missing_template_returns_1(tmp_path: Path):
    rc = main(["--template", str(tmp_path / "nope.jsonl"), "--out", str(tmp_path / "ui.html")])
    assert rc == 1
    assert not (tmp_path / "ui.html").exists()


def test_main_empty_template_returns_1(tmp_path: Path):
    tpl = tmp_path / "t.jsonl"
    tpl.write_text("", encoding="utf-8")
    assert main(["--template", str(tpl), "--out", str(tmp_path / "ui.html")]) == 1


def test_main_rejects_row_without_qid(tmp_path: Path):
    tpl = tmp_path / "t.jsonl"
    _write_template(tpl, [_row("g001"), _row(qid=None)])
    out = tmp_path / "ui.html"
    assert main(["--template", str(tpl), "--out", str(out)]) == 1
    assert not out.exists()  # 不产出无法按条对齐的半成品
