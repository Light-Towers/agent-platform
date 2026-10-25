"""DDL 文本 → 元知识形状（A 方案 Stage ② 迁移入口的解析层）。

把 agent_server/sql 的 `sql_ddl.content`（Vanna 式训练的 DDL 文本）解析成
`MetaKnowledgeService.build_from_tables` 的嵌套结构；把 `sql_docs.content`
（业务文档自由文本）best-effort 关联到表的 `table_comment`。

设计纪律：
1. **宁缺勿错**：解析不了的语句跳过并记账（skipped），不编表/列/注释——
   错一条列定义 = 该列召回带错误类型提示；错挂一条文档 = 该表口径被主动误导。
2. 表/列注释只认 `COMMENT ON TABLE/COLUMN ... IS '...'`（PG 官方机制，机器可写）；
   行内 `--` 注释不抽——不可靠且 sqlglot 会丢弃，抽了反而是猜。
3. 文档→表关联是**关键词匹配**（词边界、大小写不敏感），不是语义理解：
   文档不提表名就没有可靠落点，未命中的文档原样返回给调用方记账。
4. 纯函数、零 IO：便于单测与将来被构建入口/漂移检测复用。
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

#: 表名匹配的词边界正则模板：表名含正则元字符时 re.escape；前后邻界必须是
#: 非标识符字符——防 "order" 命中 "orders" 前缀、"user" 命中 "user_log"。
_BOUNDARY = r"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])"


def _column_type(column_def: exp.ColumnDef) -> str:
    """列类型文本（kind 参数化类型，如 DECIMAL(10, 2)）。"""
    kind = column_def.args.get("kind")
    return kind.sql() if kind is not None else ""


def parse_ddl(ddl: str, dialect: str = "postgres") -> tuple[list[dict[str, Any]], list[str]]:
    """解析 DDL 文本 → (tables, skipped)。

    tables: `build_from_tables` 形状——
        `[{"table_name": str, "table_comment": str,
           "columns": [{"column_name": str, "data_type": str, "column_comment": str}]}]`
    skipped: 解析失败/不支持的语句原文截断（每条 ≤120 字符），供调用方记账——
        静默丢 = 迁移缺列且无任何报错。

    语义：
    - 多语句文本整体 parse；单条失败只跳过该条（其余照常）。
    - `COMMENT ON TABLE/COLUMN` 可出现在 CREATE 前后，最后统一应用（后写覆盖）。
    - 同名表重复 CREATE：保留首见，后续记 skipped（源数据重复，不静默合并）。
    - **sqlglot 解析不了的语句 fallback 成 `exp.Command`（error_level=RAISE 也不抛）**——
      一律记 skipped：坏 DDL 静默消失是迁移最坏故障（缺列且无痕）。
    - CREATE INDEX/VIEW 等良构无关语句静默跳过；ALTER/DROP 良构但不处理，记 skipped。
    - 无注释给空串——与 MetricConfig 缺注释同构，不编。
    """
    if not ddl or not ddl.strip():
        return [], []

    tables: dict[str, dict[str, Any]] = {}
    comments: dict[tuple[str, str], str] = {}  # ("table", name) / ("column", "t.c") -> text
    skipped: list[str] = []

    try:
        statements = sqlglot.parse(ddl, read=dialect)
    except Exception as exc:  # noqa: BLE001 - 方言解析整体失败：整条 DDL 记账，不静默
        return [], [f"parse failed ({exc}): {ddl[:120]}"]

    for stmt in statements:
        if stmt is None:
            continue
        try:
            if isinstance(stmt, exp.Create):
                kind = str(stmt.args.get("kind") or "").upper()
                if kind in ("", "TABLE"):
                    _collect_create(stmt, tables, skipped)
                # 其他 kind（INDEX/VIEW/SCHEMA…）良构且与元知识无关：静默跳过（噪声≠异常）
            elif isinstance(stmt, exp.Comment):
                _collect_comment(stmt, comments)
            elif isinstance(stmt, exp.Command):
                # sqlglot 对解析不了的语句 WARN 后 fallback 成 Command（实测
                # error_level=RAISE 也不抛）——静默丢 = 坏 DDL 无痕消失，必须记账。
                skipped.append(f"unparsed statement: {stmt.sql(dialect)[:120]}")
            elif isinstance(stmt, exp.Alter | exp.Drop):
                # 良构但不处理的 DDL：同样记账（迁移缺了它要看得见）
                skipped.append(f"unsupported DDL: {stmt.sql(dialect)[:120]}")
        except Exception as exc:  # noqa: BLE001 - 单条结构异常只跳过该条
            skipped.append(f"{type(exc).__name__}: {stmt.sql(dialect)[:120]}")

    result: list[dict[str, Any]] = []
    for table_name, table in tables.items():
        columns = [
            {
                "column_name": column_name,
                "data_type": data_type,
                "column_comment": comments.get(("column", f"{table_name}.{column_name}"), ""),
            }
            for column_name, data_type in table["columns"]
        ]
        result.append(
            {
                "table_name": table_name,
                "table_comment": comments.get(("table", table_name), ""),
                "columns": columns,
            }
        )
    return result, skipped


def _collect_create(stmt: exp.Create, tables: dict[str, dict[str, Any]], skipped: list[str]) -> None:
    """CREATE TABLE → tables 登记（同名保留首见）。"""
    schema = stmt.this  # exp.Schema；schema.this 是 exp.Table
    if not isinstance(schema, exp.Schema):
        skipped.append(f"unexpected CREATE target: {stmt.sql()[:120]}")
        return
    table_node = schema.this
    table_name = table_node.name if isinstance(table_node, exp.Table) else ""
    if not table_name:
        skipped.append(f"CREATE without table name: {stmt.sql()[:120]}")
        return
    if table_name in tables:
        skipped.append(f"duplicate CREATE TABLE {table_name}（保留首见）")
        return
    columns: list[tuple[str, str]] = []
    for item in schema.expressions:
        if isinstance(item, exp.ColumnDef):
            columns.append((item.name, _column_type(item)))
        # 表级约束（PRIMARY KEY/UNIQUE/FOREIGN KEY/CHECK）不产列行——列名只在
        # ColumnDef 里；FK→relation_info 的声明化是后续工作，Stage ② 不猜 JOIN。
    tables[table_name] = {"columns": columns}


def _collect_comment(stmt: exp.Comment, comments: dict[tuple[str, str], str]) -> None:
    """COMMENT ON TABLE/COLUMN ... IS '...' → comments 登记（后写覆盖）。"""
    kind = str(stmt.args.get("kind") or "").upper()
    target = stmt.this
    expression = stmt.args.get("expression")
    text = expression.this if isinstance(expression, exp.Literal) else ""
    if kind == "TABLE" and isinstance(target, exp.Table) and target.name:
        comments[("table", target.name)] = text
    elif kind == "COLUMN" and isinstance(target, exp.Column):
        table = target.table
        if table:
            comments[("column", f"{table}.{target.name}")] = text
    # 其余 COMMENT ON（SCHEMA/INDEX/CONSTRAINT…）与列元知识无关，忽略


def associate_docs_with_tables(
    docs: list[str], table_names: list[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """业务文档 → 表注释候选（best-effort 关键词匹配）。

    Returns:
        `({table_name: [doc, ...]}, unmapped)`——按输入序保序；
        unmapped = 未命中任何表名的文档（调用方必须记账：静默丢文档 =
        丢业务口径且无报错）。

    匹配规则：表名的词边界、大小写不敏感匹配。同一文档命中多张表时**同时**
    挂给这些表（一篇《订单与客户联查说明》本就服务两处）；宁多挂不错挂的
    边界由调用方的 review 流程把握——本函数只做确定性匹配。
    """
    patterns = {name: re.compile(_BOUNDARY.format(name=re.escape(name)), re.IGNORECASE) for name in table_names if name}
    by_table: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for doc in docs:
        text = doc or ""
        hits = [name for name, pattern in patterns.items() if pattern.search(text)]
        if not hits:
            unmapped.append(text)
            continue
        for name in hits:
            by_table.setdefault(name, []).append(text)
    return by_table, unmapped
