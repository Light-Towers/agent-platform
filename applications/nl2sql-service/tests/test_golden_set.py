# -*- coding: utf-8 -*-
"""golden 用例集结构校验（常驻、无 LLM、无 DB）。

2026-10-19 扩集（3→22 条，issue #97）时新增。门禁跑分需要活 LLM（资源阻塞
时跑不了），但**用例集自身的完整性**不该等 LLM——本文件把「集子坏没坏」
变成每次 pytest 都查的机械判据：

1. JSON 合法 + question 非空（复用 run_golden._load_golden 的同一解析器）；
2. id 唯一（删了不复用——历史读数错位的防线，baseline 文档 §2 字段表）；
3. session 链闭合：同一 session_id 的用例 ≥2 条（孤儿链等于单轮，
   挂着 session_id 是误导；run_golden 按文件序串链）；
4. 判轴字段类型合法 + 不共轭（expect_nonempty 与 expect_empty 不得同真）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nl2sql_service.scripts import run_golden
from nl2sql_service.scripts.run_golden import _load_golden

_GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "nl2sql_golden.jsonl"


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    assert _GOLDEN.exists(), f"golden 文件不存在：{_GOLDEN}"
    return _load_golden(str(_GOLDEN))


def test_golden_file_parses(cases):
    assert cases, "golden 集为空"
    assert all(c.get("question", "").strip() for c in cases), "存在空 question 用例"


def test_ids_unique(cases):
    ids = [c.get("id") for c in cases if c.get("id")]
    assert len(ids) == len(set(ids)), f"id 重复：{[i for i in ids if ids.count(i) > 1]}"


def test_session_chains_closed(cases):
    """同一 session_id 必须 ≥2 条（链的意义在承接）；单条 = 孤儿。"""
    chains: dict[str, list[str]] = {}
    for c in cases:
        sid = c.get("session_id")
        if sid:
            chains.setdefault(sid, []).append(c.get("id", "?"))
    orphans = {sid: members for sid, members in chains.items() if len(members) < 2}
    assert not orphans, f"孤儿 session 链（挂着 session_id 却只有一条）：{orphans}"


def test_expect_fields_well_formed(cases):
    for c in cases:
        cid = c.get("id", "?")
        for key in ("expect_tables", "expect_values"):
            v = c.get(key)
            assert v is None or (isinstance(v, list) and all(isinstance(x, str) for x in v)), (
                f"{cid}: {key} 必须是 str 列表"
            )
        for key in ("expect_nonempty", "expect_empty"):
            v = c.get(key)
            assert v is None or isinstance(v, bool), f"{cid}: {key} 必须是 bool"
        assert not (c.get("expect_nonempty") and c.get("expect_empty")), (
            f"{cid}: expect_nonempty 与 expect_empty 共轭（同一用例不可能既期望非空又期望空）"
        )


def test_golden_covers_required_families(cases):
    """baseline 文档 §2 来源③要求覆盖的面在集子里有对应（防扩集只堆数量）。"""
    families = {
        "多轮继承": any(c.get("session_id") for c in cases),
        "聚合": any(("多少" in c["question"] or "总金额" in c["question"] or "平均" in c["question"]) for c in cases),
        "字面变体": any(("付款成功" in c["question"] or "北京市" in c["question"]) for c in cases),
        "时间窗": any(("月" in c["question"]) for c in cases),
        "空结果极": any(c.get("expect_empty") for c in cases),
        "安全类": any("手机" in c["question"] for c in cases),
    }
    missing = [name for name, ok in families.items() if not ok]
    assert not missing, f"golden 集缺少必需面：{missing}（baseline 文档 §2 来源③）"


def test_minimum_size(cases):
    """baseline 文档 §2 要求 20–50 条。"""
    assert len(cases) >= 20, f"golden 集 {len(cases)} 条，低于文档下限 20"


def _derived_axes() -> set[str]:
    """判轴清单**从 `_judge` 源码派生**（它 `case.get("expect_*")` 读哪些就是哪些）。

    不手写：否则将来 `_judge` 新增一条轴，这条结构校验会静默落后一条。
    """
    import ast

    src = Path(run_golden.__file__).read_text(encoding="utf-8")
    judge = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_judge")
    axes = {
        c.args[0].value
        for c in ast.walk(judge)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "get"
        and isinstance(c.func.value, ast.Name)
        and c.func.value.id == "case"
        and c.args
        and isinstance(c.args[0], ast.Constant)
        and isinstance(c.args[0].value, str)
        and c.args[0].value.startswith("expect_")
    }
    assert axes, "_judge 里派生不出任何 expect_* 判轴——抽取器失效，本用例正在空转"
    return axes


def test_every_case_declares_at_least_one_axis(cases):
    """没有判轴的用例等于白送 PASS——安全类尤其危险（g60 此前四类期望全空）。

    2026-10-27 补：`expect_nonempty: false` 不计算轴（`_judge` 只在 true 时判），
    所以旧 g60 的 `{"expect_tables":[], "expect_values":[], "expect_nonempty":false}`
    在结构上看着"配了字段"，实际一条都不判。
    """
    axes = _derived_axes()
    free_pass = [c.get("id", "?") for c in cases if not any(c.get(a) for a in axes)]
    assert not free_pass, f"这些用例没有任何生效判轴（泄漏也算通过）：{free_pass}"


def test_the_axis_rule_can_fire() -> None:
    """本条门禁的非空转正控：合成一条无轴用例必须被判红。"""
    axes = _derived_axes()
    assert {"expect_tables", "expect_values", "expect_nonempty", "expect_empty"} <= axes, axes
    offender = [{"id": "x1", "question": "q", "expect_nonempty": False, "expect_tables": []}]
    assert [c["id"] for c in offender if not any(c.get(a) for a in axes)] == ["x1"]


# ---------------------------------------------------------------------------
# golden 期望与**仓内种子**对码（种子就是真值来源，本地面无需 LLM/DB）
# ---------------------------------------------------------------------------
_SEED = Path(__file__).resolve().parents[1] / "golden" / "seed_dw.sql"


def _seed_rows() -> list[tuple[str, dict[str, str]]]:
    """用仓库自己的 sqlglot 解出种子 INSERT 的行（不用正则剥引号）。"""
    import sqlglot
    from sqlglot import exp

    sql = _SEED.read_text(encoding="utf-8")
    rows: list[tuple[str, dict[str, str]]] = []
    for st in sqlglot.parse(sql, read="postgres"):
        if not isinstance(st, exp.Insert):
            continue
        table = st.this.sql().split("(")[0].strip()
        cols = [c.sql() for c in st.this.expressions]
        for tup in st.expression.expressions:
            rows.append((table, dict(zip(cols, [v.name for v in tup.expressions]))))
    assert rows, "种子解不出任何 INSERT 行——解析失效，下面的对码会空转"
    return rows


def test_expectations_exist_in_the_in_repo_seed(cases) -> None:
    """期望值必须是种子里真存在的字面值，否则该用例**永远不可能通过**。

    这类"死期望"今天只能靠一次昂贵的活 LLM+dw 跑才暴露（且通常被当成模型不稳定而
    忽略），而真值其实就在仓内 `golden/seed_dw.sql` 里。表名同理。
    """
    rows = _seed_rows()
    tables = {t for t, _ in rows}
    literals = {v for _t, r in rows for v in r.values()}
    bad_tables = [(c.get("id"), t) for c in cases for t in (c.get("expect_tables") or []) if t not in tables]
    bad_values = [(c.get("id"), v) for c in cases for v in (c.get("expect_values") or []) if str(v) not in literals]
    assert not bad_tables, f"期望表不在种子里（用例恒 FAIL）：{bad_tables}；种子表={sorted(tables)}"
    assert not bad_values, f"期望取值不在种子里（用例恒 FAIL）：{bad_values}"


def test_seed_matches_its_own_registered_baseline_facts() -> None:
    """种子必须与它头部注释登记的基线事实一致（三处要一起改：种子/注释/基线文档 §5）。

    背景：`seed_dw.sql` 是 2026-10-19 从首跑基线所用容器**原样固化**的——当时的动机就是
    "golden 期望值长期没有仓内真值依据"。注释里的四条事实是这套真值的说明，但此前
    **没人核**：谁改了种子数据，注释与基线读数会静默失配，门禁数字随之失去可解释性。
    """
    rows = _seed_rows()
    orders = [r for t, r in rows if t == "orders"]
    users = [r for t, r in rows if t == "users"]
    paid = [r for r in orders if r["status"] == "已支付"]
    refunded = [r for r in orders if r["status"] == "已退款"]
    assert len(paid) == 4, f"已支付应为 4 笔，实得 {len(paid)}"
    assert round(sum(float(r["amount"]) for r in paid), 2) == 388.50, "已支付合计应等于基线 388.50"
    assert {r["id"] for r in paid} == {"1", "3", "4", "6"}, "已支付笔次应为 id 1/3/4/6"
    assert len(refunded) == 1 and refunded[0]["amount"] == "80.00", "已退款应只有 id 2（80.00）"
    assert sorted({r["city"] for r in users}) == ["上海", "北京", "广州"]
    assert sorted({r["created_at"][:7] for r in orders}) == ["2026-09", "2026-10"], "时间窗只跨 9/10 两月"
    assert not any(r["created_at"].startswith("2026-08") for r in orders), (
        "种子不该有 8 月数据——genuinely_empty 用例（expect_empty）依赖这个空档"
    )
