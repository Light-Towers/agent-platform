# -*- coding: utf-8 -*-
"""
test_escape.py —— 验证 app/utils/escape_milvus_string_utils.py 的 Milvus 字符串转义。

【不依赖重型依赖，可在纯 pytest+numpy+python-dotenv 环境运行。】
该模块为纯 stdlib 函数，无外部依赖。

依据源码 docstring 的转义规则编写用例：
1. 反斜杠（\）-> 双反斜杠（\\）
2. 双引号（"）-> 转义双引号（\"）
3. 换行/回车/制表符 -> 空格
4. None -> 空字符串；非字符串输入会被 str() 转换
"""

import pytest

from app.utils.escape_milvus_string_utils import escape_milvus_string


def test_escape_backslash():
    # 输入含一个字面反斜杠，应变为两个
    assert escape_milvus_string("a\\b") == "a\\\\b"


def test_escape_double_quote():
    assert escape_milvus_string('he said "hi"') == 'he said \\"hi\\"'


def test_escape_single_quote_unchanged():
    # 单引号不在转义规则内，保持原样
    assert escape_milvus_string("it's ok") == "it's ok"


def test_escape_newline():
    assert escape_milvus_string("line1\nline2") == "line1 line2"


def test_escape_carriage_return():
    assert escape_milvus_string("a\rb") == "a b"


def test_escape_tab():
    assert escape_milvus_string("a\tb") == "a b"


def test_escape_mixed_whitespace():
    assert escape_milvus_string("a\nb\rc\td") == "a b c d"


def test_escape_combined_backslash_and_quote():
    # 输入 'line1\\n"quote"' 中 \\ 是字面反斜杠，需转义为 \\
    assert escape_milvus_string('line1\\n"quote"') == 'line1\\\\n\\"quote\\"'


def test_escape_none_returns_empty_string():
    assert escape_milvus_string(None) == ""


def test_escape_non_string_is_converted():
    # 非字符串会被 str() 处理
    assert escape_milvus_string(123) == "123"


def test_escape_empty_string():
    assert escape_milvus_string("") == ""


def test_escape_no_special_chars_unchanged():
    assert escape_milvus_string("普通商品名称") == "普通商品名称"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a\\b", "a\\\\b"),
        ('"x"', '\\"x\\"'),
        ("a\nb", "a b"),
        ("a\tb", "a b"),
        ("", ""),
        (None, ""),
    ],
)
def test_escape_parametrized(raw, expected):
    assert escape_milvus_string(raw) == expected
