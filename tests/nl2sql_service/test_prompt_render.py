"""prompt 渲染用例（#108）：字面花括号不抛、白名单槽位替换、未知槽位保留。

修复前 `render()` 用 `template.format_map(_SafeDict(...))`：`__missing__` 只救
"合法未知字段名"，`render('示例：{"sql": "SELECT 1"}')` 实测抛
`ValueError: Invalid format specifier`——JSON few-shot 一进 prompt 即每次请求
渲染失败、全量 fallback。改为白名单正则替换后本文件钉死四件事。

feat 线槽位（13 个，generate/correct/answer 三 prompt 并集）比 docs 线多
relations/examples/aggregation_hint/attempted_sql/result_view/empty_diagnosis。
"""

from __future__ import annotations

from nl2sql_service.agent.nodes._prompt import render


def test_literal_braces_are_preserved():
    """JSON 示例/字面花括号原样渲染——format_map 在此抛 ValueError（#108 核心）。"""
    template = '示例：{"sql": "SELECT 1", "note": "{x}"}'
    assert render(template, query="q") == template


def test_json_fewshot_block_with_slots_renders():
    template = '问题：{query}\nfew-shot：{"sql": "SELECT 1"}\n表：{table_infos}'
    out = render(template, query="上个月销售额", table_infos="orders(id, amount)")
    assert out == '问题：上个月销售额\nfew-shot：{"sql": "SELECT 1"}\n表：orders(id, amount)'


def test_all_feat_slots_substituted():
    slots = (
        "query", "table_infos", "metric_infos", "relations", "examples", "aggregation_hint",
        "date_info", "db_info", "sql", "attempted_sql", "error", "result_view", "empty_diagnosis",
    )
    out = render("|".join("{%s}" % s for s in slots), **{s: s for s in slots})
    assert out == "|".join(slots)


def test_unknown_slot_preserved_like_old_missing_behavior():
    """未知槽位原样保留——与旧 __missing__ 行为一致（不炸也不静默吞）。"""
    assert render("{unknown_slot} 保留", query="q") == "{unknown_slot} 保留"


def test_missing_value_renders_empty():
    """白名单槽位未传值 ⇒ 空串（旧 format_map 行为：__missing__ 返回 {} 由调用方兜）。"""
    assert render("[{sql}]") == "[]"
