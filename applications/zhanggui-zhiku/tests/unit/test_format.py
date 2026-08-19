# -*- coding: utf-8 -*-
"""
test_format.py —— 验证 app/utils/format_utils.py 的 JSON 格式化工具。

【不依赖重型依赖，可在纯 pytest+numpy+python-dotenv 环境运行。】
仅依赖标准库 json / typing。

覆盖两个纯函数：
- format_state(state, indent=4)：工作流状态格式化，ensure_ascii=False
- format_json(data, indent=4, ensure_ascii=False)：通用 JSON 格式化
"""

import json

from app.utils.format_utils import format_json, format_state


def test_format_state_returns_parseable_json():
    state = {"task_id": "001", "pdf_path": "test.pdf"}
    out = format_state(state)
    assert isinstance(out, str)
    # 必须是合法 JSON 且内容等价
    assert json.loads(out) == state


def test_format_state_default_indent_is_4_spaces():
    state = {"a": 1, "b": 2}
    out = format_state(state)
    # 4 空格缩进会在第二层出现
    assert "\n    " in out


def test_format_state_keeps_chinese_ensure_ascii_false():
    state = {"name": "测试"}
    out = format_state(state)
    assert "测试" in out


def test_format_json_custom_indent():
    data = {"a": 1}
    out = format_json(data, indent=2)
    assert "\n  " in out


def test_format_json_ensure_ascii_true_escapes_chinese():
    data = {"name": "测试"}
    out = format_json(data, ensure_ascii=True)
    assert "测试" not in out  # 中文被转义
    assert "\\u6d4b" in out


def test_format_json_ensure_ascii_false_keeps_chinese():
    data = {"name": "测试"}
    out = format_json(data, ensure_ascii=False)
    assert "测试" in out


def test_format_state_empty_dict():
    assert format_state({}) == "{}"


def test_format_json_list():
    data = [1, 2, 3]
    out = format_json(data)
    assert json.loads(out) == [1, 2, 3]
