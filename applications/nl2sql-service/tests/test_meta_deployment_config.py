# -*- coding: utf-8 -*-
"""部署侧元知识配置（deploy/data/nl2sql_meta_config.yaml）的静态对账。

为什么单独一个文件、而且不连库：批次 2 的数据面有**两份镜像声明**——dw 的
`COMMENT ON`（进库，schema 真相）与元知识配置（进 nl2sql_meta，召回真相）。
它们一旦分叉，表现不是报错而是"答案口径漂移"：模型从 prompt 里拿到两套列口径，
而 /ready、/health、SQL 生成全都正常。所以这里只查**两份文本之间**的关系，
纯本地、进常规门禁（G1）；需要库侧真值的三条（类型拼写、值是否真存在、指标能否跑）
在 test_golden_seed_real_pg.py（需 DW_DB_DSN，上线前在 126 的 ap-iso-pg 上跑）。

加载用 scripts.build_meta_knowledge.load_metric_config —— 与 36 Job 同一个入口、
同一份 MetricConfig schema：不让测试自造一套"看起来一样"的校验（本仓踩过
entities/ 双契约的雷，见 metric_config_schema.py 头注）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from nl2sql_service.scripts.build_meta_knowledge import load_metric_config

_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = _ROOT / "deploy" / "data"
_CONFIG = _DATA_DIR / "nl2sql_meta_config.yaml"
_FIXTURE = _DATA_DIR / "nl2sql_dw_fixture.sql"

# 注释串里的 '' 是 SQL 转义后的单引号，故值段允许 (?:''[^']*)* 这种延续形式
_TABLE_COMMENT_RE = re.compile(r"^COMMENT ON TABLE (\w+) IS '([^']*(?:''[^']*)*)';", re.M)
_COLUMN_COMMENT_RE = re.compile(
    r"^COMMENT ON COLUMN (\w+)\.(\w+) IS '([^']*(?:''[^']*)*)';", re.M
)


@pytest.fixture(scope="module")
def config() -> object:
    assert _CONFIG.is_file(), f"元知识配置不存在：{_CONFIG}"
    return load_metric_config(str(_CONFIG))


@pytest.fixture(scope="module")
def fixture_comments() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """dw fixture 里的表/列注释（SQL 单引号串内 '' 视为转义后的 '）。"""
    assert _FIXTURE.is_file(), f"dw fixture 不存在：{_FIXTURE}"
    text = _FIXTURE.read_text(encoding="utf-8")
    tables = {t: c.replace("''", "'") for t, c in _TABLE_COMMENT_RE.findall(text)}
    columns = {
        (t, col): c.replace("''", "'")
        for t, col, c in _COLUMN_COMMENT_RE.findall(text)
    }
    # fixture 自己得先有话可说：两处都为空说明注释段被删了，比对会"全绿地空转"
    assert tables and columns, f"fixture 注释读数为空（tables={len(tables)} columns={len(columns)}）"
    return tables, columns


def test_config_declares_every_section(config) -> None:
    """六段都不许为空。

    空段不是"没配"而是"该轴没有元知识"：values 段空 ⇒ validate_literals 无字典可比，
    aliases 段空 ⇒ 口语变体召不回来，relations 段空 ⇒ 模型自己猜 JOIN。
    三种都只会让答案变差，不会让任何探针变红，所以在这里钉死。
    """
    for section in ("tables", "columns", "metrics", "values", "relations", "aliases"):
        assert getattr(config, section), f"{section} 段为空：元知识缺一整轴，召回静默降级"


def test_table_and_column_comments_match_fixture_verbatim(config, fixture_comments) -> None:
    """注释逐字对齐（对齐纪律 0）：元知识与 dw 库注释必须是同一句话。

    比"包含"更严是刻意的：口径差一个限定词（"已支付"vs"已支付不含退款"）
    正是生成期两套答案的来源，宽松比较恰好放过最危险的那类分叉。
    """
    tables, columns = fixture_comments

    assert {t.table_name: t.table_comment for t in config.tables} == tables, (
        "表注释与 dw fixture 的 COMMENT ON TABLE 分叉"
    )
    declared = {(c.table_name, c.column_name): c.column_comment for c in config.columns}
    assert declared == columns, (
        f"列注释与 fixture 分叉：\n  仅配置有={sorted(set(declared) - set(columns))}"
        f"\n  仅 fixture 有={sorted(set(columns) - set(declared))}"
        f"\n  同列不同词={[k for k in set(declared) & set(columns) if declared[k] != columns[k]]}"
    )


def test_column_types_are_not_text(config) -> None:
    """枚举/城市列不许声明成 text（services/value_resolver.py 的 LinkablePolicy）。

    `_DENY_TYPES` 含 "text" 且按**子串**匹配，所以写 text 的列即使进了
    linkable_columns 白名单也会被永久判 denied ⇒ 取值只读探针（validate_literals
    的唯一源侧判据）对这一列再也不给 exists/missing，只给 unknown。
    真实类型的逐字拼写对账在库侧用例里做，这里只钉这一个会静默致盲的取值。
    """
    offenders = [
        f"{c.table_name}.{c.column_name}={c.data_type}"
        for c in config.columns
        if c.data_type.strip().lower() == "text"
    ]
    assert not offenders, f"这些列类型为 text，linkable 探针会永久降级 unknown：{offenders}"


def test_values_reference_declared_columns(config) -> None:
    """values 段每条都要挂到本配置自己声明过的列上，且 table_name 非空。

    table_name 是 #117 加的：空 = 旧配置兼容形状，同名列跨表时回溯不到出处。
    新部署留空就等于把"值属于哪张表"这个信息丢掉，而召回侧按 (table, column) 过滤。
    """
    declared = {(c.table_name, c.column_name) for c in config.columns}
    bad_missing_table = [v.column_name for v in config.values if not v.table_name]
    assert not bad_missing_table, f"values 段缺 table_name（#117）：{bad_missing_table}"
    orphans = [
        f"{v.table_name}.{v.column_name}={v.value}"
        for v in config.values
        if (v.table_name, v.column_name) not in declared
    ]
    assert not orphans, f"values 引用了 columns 段没有的列：{orphans}"


def test_relations_reference_declared_columns(config) -> None:
    declared = {(c.table_name, c.column_name) for c in config.columns}
    for rel in config.relations:
        assert (rel.left_table, rel.left_column) in declared, (
            f"relation 左端 {rel.left_table}.{rel.left_column} 未在 columns 段声明"
        )
        assert (rel.right_table, rel.right_column) in declared, (
            f"relation 右端 {rel.right_table}.{rel.right_column} 未在 columns 段声明"
        )


def test_alias_targets_exist_and_columns_use_qualified_name(config) -> None:
    """别名指向必须可解析；列级别名必须写 `table.column` 全名（对齐纪律 4）。

    meta_repository.find_columns_by_names 按 (table_name, column_name) **行值比较**，
    裸列名取不到行 ⇒ 别名登记了但永远召不回来（写得像配好了，其实是死数据）。
    """
    metric_names = {m.metric_name for m in config.metrics}
    table_names = {t.table_name for t in config.tables}
    column_keys = {(c.table_name, c.column_name) for c in config.columns}

    for alias in config.aliases:
        kind = alias.target_kind
        if kind == "column":
            assert "." in alias.target_name, (
                f"列级别名必须用 table.column 全名，裸列名召不回：{alias.target_name}"
            )
            key = tuple(alias.target_name.split(".", 1))
            assert key in column_keys, f"列别名指向不存在的列：{alias.target_name}"
        elif kind == "metric":
            assert alias.target_name in metric_names, f"指标别名指向不存在的指标：{alias.target_name}"
        elif kind == "table":
            assert alias.target_name in table_names, f"表别名指向不存在的表：{alias.target_name}"
        else:
            pytest.fail(f"target_kind 只允许 table|column|metric，得到 {kind!r}")


def test_sensitive_alias_is_deliberately_kept(config) -> None:
    """users.phone 的别名是**故意留的**，不是漏删。

    删掉它确实能让"手机号"召不到列，但那是用"召回不到"冒充"已防护"：
    L2 投影黑名单与 L3 结果掩码就没机会被门禁演到。这条用例把该决定钉住，
    谁哪天"顺手清理一下敏感列别名"，这里会红并指回理由。
    """
    phone_alias = next(
        (a for a in config.aliases if a.target_kind == "column" and a.target_name == "users.phone"),
        None,
    )
    assert phone_alias is not None, (
        "users.phone 别名被删：L2/L3 脱敏就失去了可演练的入口（见本配置头部说明）"
    )
