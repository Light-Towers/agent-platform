#!/usr/bin/env python3
"""迁移 SQL 静态门禁（零基建，`make lint` 覆盖）——补 "CI 无 PG 服务" 的观测盲区。

来历：分支审核 B-1/B-3 在本分支上全绿存活，根因不是缺 PG，是缺一条**不需要 PG
就能跑**的静态闭包检查。

  M-1 引用闭包：迁移 SQL 里被引用、但按版本顺序到该文件为止从未被 `CREATE
      TABLE` 创建的关系名 ⇒ 违规。B-1 就是 006 把 004 的**文件名**
      (`004_example_corpus.up.sql`) 抄成了**表名** (`nl2sql_example_info`)：真 PG
      上首个 `SELECT … FROM nl2sql_example_corpus` 抛 42P01，并因单连接非
      autocommit 连带回滚 001-005。
  M-2 冲突键命中：生产代码里的 `INSERT … ON CONFLICT (cols)` 目标键必须被迁移链
      最终态的某个 UNIQUE/PRIMARY KEY **覆盖**（PG 语义是 covered-by，允许子集）。
      B-3 的"先发代码后迁移 ⇒ 42P10"因此从运行期事故变成评审时可见的发布顺序约束。
  M-3 登记表活性：`_EXTERNAL` 条目从未被命中即失败（防白名单无声扩大，同
      `lint_architecture.py` 的对称差自检）。

判据口径（对齐 `docs/operations/evidence-format.md`）：
- 迁移目录枚举取 `git ls-files`（本机文件系统不作数）；取不到清单 fail-closed
  报退出码 2，不退回 `Path.exists()`，无旁路开关、无跳过环境变量。
- `--selftest` 用合成违规样本证明 M-1/M-2 非空转（门禁自带自检）；正常跑额外
  打印"校验过的冲突目标数"，为 0 即说明 M-2 没咬到东西。
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 系统目录：不由本仓迁移创建，也不属本包命名空间。
_SYSTEM_PREFIXES = ("pg_", "information_schema", "sys_", "dual", "tmp_", "temp_")

#: 确证为「外部持有」的关系登记表：{关系名: 可复取的理由}。
#: 条目从未被任何迁移引用 ⇒ M-3 失败（过期登记不许留在仓里）。初版实跑证实
#: langgraph 的 checkpoints 族并不被本仓迁移 SQL 引用（只在 Python 侧建），
#: 故此处为空——加条目必须同时附"本包迁移确实引用了它"的可复取证据。
_EXTERNAL: dict[str, str] = {}

#: 抽取盲区登记表：{文件: 为何本门禁暂时抽不出它的冲突目标}。条目现由 M-4 双向
#: 对称差看守——新盲区未登记即红，登记项一旦被抽到即红（逼着删条目、恢复覆盖）。
_COVERAGE_BLIND: dict[str, str] = {
    "applications/nl2sql-service/nl2sql_service/clients/pgvector_client_manager.py": (
        "`upsert_vector(table, …, conflict_col=\"id\")`（该文件 L190-206）表名与冲突列"
        "都是调用方传入的运行期字符串 ⇒ 静态无法定位到具体表/键。复核触发条件：一旦"
        "它的调用点收敛成固定表名，本条必须删除并恢复覆盖"
    ),
}

_IDENT = r"[a-zA-Z_][a-zA-Z0-9_]*"
_REF_PATTERNS = (
    re.compile(rf"\b(?:FROM|JOIN|REFERENCES)\s+({_IDENT})", re.I),
    re.compile(rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE(?:\s+IF\s+EXISTS)?)\s+({_IDENT})", re.I),
    re.compile(rf"\bCREATE\s+(?:UNIQUE\s+)?(?:INDEX\s+{_IDENT}\s+(?:IF\s+NOT\s+EXISTS\s+)?ON|VIEW\s+{_IDENT}\s+AS\s+SELECT[\s\S]*?\s+FROM)\s+({_IDENT})", re.I),
    re.compile(rf"\bCOMMENT\s+ON\s+(?:TABLE|COLUMN)\s+({_IDENT})", re.I),
    re.compile(rf"'({_IDENT})'\s*::\s*regclass", re.I),
)
# `DO UPDATE SET`、`ALTER COLUMN x SET DEFAULT` 这类位置上的关键字不是关系名。
_NOT_RELATIONS = {
    "set", "where", "values", "select", "from", "and", "or", "not", "null", "exists",
    "if", "only", "into", "table", "column", "distinct", "returning", "using", "when",
    "then", "else", "end", "case", "is", "in", "as", "on", "default", "constraint",
}
_CREATE_TABLE = re.compile(rf"\bCREATE\s+(?:TEMPORARY\s+|UNLOGGED\s+|FOREIGN\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_IDENT})", re.I)
_INLINE_UNIQUE = re.compile(rf"\bCONSTRAINT\s+({_IDENT})\s+UNIQUE\s*\(([^)]*)\)", re.I)
_ANON_UNIQUE = re.compile(r"\bUNIQUE\s*\(([^)]*)\)", re.I)
_TABLE_PK = re.compile(r"\bPRIMARY\s+KEY\s*\(([^)]*)\)", re.I)
_COL_DECL = re.compile(rf"^\s*({_IDENT})\s+\S", re.M)
# 迁移里的换键动作（006/010 形态）：ADD CONSTRAINT … UNIQUE (…) / ADD PRIMARY KEY (…) /
# DROP CONSTRAINT [IF EXISTS] name
_ALTER_ADD_UNIQUE = re.compile(
    rf"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?({_IDENT})\s*(?:\s|\n)*ADD\s+CONSTRAINT\s+({_IDENT})\s*(?:\s|\n)*UNIQUE\s*\(([^)]*)\)",
    re.I,
)
_ALTER_ADD_PK = re.compile(rf"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?({_IDENT})\s*(?:\s|\n)*ADD\s+PRIMARY\s+KEY\s*\(([^)]*)\)", re.I)
_ALTER_DROP = re.compile(rf"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?({_IDENT})\s*(?:\s|\n)*DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?({_IDENT})", re.I)
# 生产代码里的 upsert 目标（文本位置配对用）；`{...}` 占位由调用侧剔除
_INSERT_INTO = re.compile(r"\bINSERT\s+INTO\s+([^\s(,;]+)", re.I)
_ON_CONFLICT = re.compile(r"\bON\s+CONFLICT\s*\(([^)]*)\)", re.I)


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释与 `/* */` 块注释——注释里提表名是常态，不算引用。"""
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _join_adjacent_literals(sql: str) -> str:
    """合并 PL/pgSQL 里"相邻字符串常量续写"（`'ALTER … '` + `'UNIQUE (…)'`）。

    不合并被 `||` 分隔的（那是显式拼接，不是同一常量）。006 的换键语句就是这种
    跨行续写形态，不合并则 ADD CONSTRAINT 与 UNIQUE 子句落在两个片段里读不出键。
    """
    return re.sub(r"'\s+'", " ", sql)


def _norm_cols(raw: str) -> tuple[str, ...]:
    return tuple(sorted(c.strip().strip('"').lower() for c in raw.split(",") if c.strip()))


def _tracked(*patterns: str) -> list[Path]:
    """版本控制清单口径的文件枚举（本机 FS 不作数，且不扫 .venv 等未入库目录）。"""
    try:
        out = subprocess.run(
            ["git", "ls-files", *patterns],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:
        raise RuntimeError(f"git ls-files {patterns} 失败 [{type(exc).__name__}]: {exc}") from exc
    return [ROOT / ln.strip() for ln in out.splitlines() if ln.strip()]


def _discover_migration_dirs() -> list[Path]:
    """迁移目录枚举 = 版本控制清单，不是本机文件系统。"""
    files = _tracked("*migrations/*.up.sql")
    dirs = sorted({f.parent for f in files})
    if not dirs:
        raise RuntimeError("git ls-files 返回零个迁移 up.sql —— 枚举本身失效，不等于无需检查")
    missing = [str(d.relative_to(ROOT)) for d in dirs if not d.is_dir()]
    if missing:
        raise RuntimeError(f"清单里的迁移目录在本机缺失（工作区不完整）: {missing}")
    return dirs


def _migration_files(mig_dir: Path) -> list[Path]:
    return sorted(mig_dir.glob("*.up.sql"), key=lambda p: p.name)


def _table_body(sql: str, table: str) -> str:
    """取 `CREATE TABLE <table> ( ... )` 的括号体（平衡扫描，避开关不掉的嵌套）。"""
    m = re.search(rf"\bCREATE\s+(?:\w+\s+)*TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(table)}\s*\(", sql, re.I)
    if not m:
        return ""
    depth, start, i = 0, m.end() - 1, m.end() - 1
    while i < len(sql):
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return sql[start + 1 : i]
        i += 1
    return ""


def _slots_of_body(body: str) -> dict[str, tuple[str, ...]]:
    """一张新表的键槽位：命名 UNIQUE / 匿名 UNIQUE / 表级 PK / 列级裸 UNIQUE|PK。"""
    slots: dict[str, tuple[str, ...]] = {}
    rest = body
    for cons, cols in _INLINE_UNIQUE.findall(body):
        slots[cons.lower()] = _norm_cols(cols)
    for m in list(_INLINE_UNIQUE.finditer(body)):
        rest = rest.replace(m.group(0), " ")
    for i, cols in enumerate(_ANON_UNIQUE.findall(rest)):
        slots.setdefault(f"__anon_{i}", _norm_cols(cols))
    for cols in _TABLE_PK.findall(body):
        slots["__pk"] = _norm_cols(cols)
    for line in body.splitlines():
        col = _COL_DECL.match(line)
        if not col:
            continue
        if re.search(r"\bUNIQUE\b(?!\s*\()|\bPRIMARY\s+KEY\b(?!\s*\()", line[col.end():], re.I):
            slots.setdefault(f"__col_{col.group(1).lower()}", (col.group(1).lower(),))
    return slots


def build_final_keys(mig_dir: Path) -> dict[str, set[tuple[str, ...]]]:
    """{表名: 最终态键集合}，按版本顺序累计，**文件内按文本顺序**应用换键事件。

    换键事件（DROP CONSTRAINT / ADD CONSTRAINT UNIQUE / ADD PRIMARY KEY）必须按出现
    次序施加：006 与 010 都是"先 DROP 旧键再 ADD 新键"，乱序会把刚建的键又删掉，
    得出"键集为空"的假违规。
    """
    state: dict[str, dict[str, tuple[str, ...]]] = {}
    for path in _migration_files(mig_dir):
        sql = _join_adjacent_literals(_strip_comments(path.read_text(encoding="utf-8")))
        for table in (t.lower() for t in _CREATE_TABLE.findall(sql)):
            state.setdefault(table, {}).update(_slots_of_body(_table_body(sql, table)))
        events: list[tuple[int, str, tuple]] = []
        for m in _ALTER_ADD_UNIQUE.finditer(sql):
            events.append((m.start(), "add_uq", (m.group(1).lower(), m.group(2).lower(), _norm_cols(m.group(3)))))
        for m in _ALTER_ADD_PK.finditer(sql):
            events.append((m.start(), "add_pk", (m.group(1).lower(), _norm_cols(m.group(2)))))
        for m in _ALTER_DROP.finditer(sql):
            events.append((m.start(), "drop", (m.group(1).lower(), m.group(2).lower())))
        for _pos, kind, args in sorted(events):
            if kind == "add_uq":
                tbl, cons, cols = args
                state.setdefault(tbl, {})[cons] = cols
            elif kind == "add_pk":
                tbl, cols = args
                state.setdefault(tbl, {})["__pk"] = cols
            else:
                tbl, cons = args
                slots = state.setdefault(tbl, {})
                slots.pop(cons, None)
                if cons in ("__pk", f"{tbl}_pkey"):  # PG 给 PK 的自动命名
                    slots.pop("__pk", None)
    return {t: set(slots.values()) for t, slots in state.items() if slots}


def _collect_refs(sql: str) -> set[str]:
    refs: set[str] = set()
    for pat in _REF_PATTERNS:
        for m in pat.finditer(sql):
            name = m.group(1).lower()
            if name in _NOT_RELATIONS:
                continue
            if sql[m.end(): m.end() + 2].lstrip().startswith("("):  # FROM fn(...) 非关系
                continue
            refs.add(name)
    return refs


def check_refs(dirs: list[Path]) -> tuple[list[str], set[str]]:
    """M-1：引用闭包。返回 (违规, 命中的外部登记表项)。"""
    problems: list[str] = []
    hit: set[str] = set()
    for mig_dir in dirs:
        created: set[str] = set()
        for path in _migration_files(mig_dir):
            sql = _join_adjacent_literals(_strip_comments(path.read_text(encoding="utf-8")))
            # 同一文件内"先建后引"是常态（001 建 7 张表后在同文件里 ALTER 它们），
            # 故比对基线含本文件新建的表。
            this_file = {t.lower() for t in _CREATE_TABLE.findall(sql)}
            for rel in sorted(_collect_refs(sql) - this_file - created):
                if rel.startswith(_SYSTEM_PREFIXES):
                    continue
                if rel in _EXTERNAL:
                    hit.add(rel)
                    continue
                problems.append(
                    f"M-1 {path.name}: 引用了到本文件为止从未创建的关系 `{rel}`"
                    f"（{mig_dir.name} 此前累计建表 {len(created)} 张）。真 PG 上这里 42P01 "
                    f"并连带回滚整条迁移链——引用别处的表以 `CREATE TABLE` 原文为准，"
                    f"不信迁移文件名"
                )
            created |= this_file
    return problems, hit


def _registry_diff(registered: dict[str, str], active: set[str], kind: str) -> list[str]:
    """登记表双向对称差：未命中条目 = 过期登记；命中但未登记 = 新缺口。

    两条判据共用（M-3 外部关系、M-4 抽取盲区）。空登记表不构成"判据空转"——
    空转的证据由 --selftest 的 ghost 用例负责。
    """
    if not registered:
        return []
    problems = [
        f"{kind} 登记表项 `{k}` 未被命中（登记过期或判据失效：要么删条目，"
        f"要么补它为何仍需登记的证据）。原登记：{registered[k]}"
        for k in sorted(set(registered) - active)
    ]
    return problems


def check_external_registry(hit: set[str]) -> list[str]:
    return _registry_diff(_EXTERNAL, hit, "M-3 外部关系")


def _fold_text(node: ast.AST) -> str:
    """把字符串常量 / f-string / 相邻字面量拼接折叠成一段文本供正则扫。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                parts.append("{%s}" % _fold_text(v.value) if isinstance(v.value, ast.Name) else "{}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _fold_text(node.left) + " " + _fold_text(node.right)
    return ""


def _production_py() -> list[Path]:
    """待扫的 Python 生产文件（清单口径；测试与本机未入库目录不进判据）。"""
    out = []
    for py in _tracked("*.py"):
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        if rel.startswith(("tests/", "scripts/lint_migration_refs.py", "eval/", "courses/")):
            continue
        if "/tests/" in f"/{rel}" or "__pycache__" in rel:
            continue
        out.append(py)
    return out


def _python_ddl_tables() -> dict[str, set[tuple[str, ...]]]:
    """Python 里内嵌的 CREATE TABLE（迁移 runner 自建表等）也纳入键集合。"""
    out: dict[str, set[tuple[str, ...]]] = {}
    for py in _production_py():
        if not py.is_file():
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            text = _fold_text(node.value) if node.value is not None else ""
            if "CREATE TABLE" not in text.upper():
                continue
            sql = _strip_comments(text)
            for table in (t.lower() for t in _CREATE_TABLE.findall(sql)):
                out.setdefault(table, set()).update(_slots_of_body(_table_body(sql, table)).values())
    return out


def _conflict_targets_from_text(text: str) -> list[tuple[str, tuple[str, ...], int]]:
    """按文本位置配对 `INSERT INTO <t>` … `ON CONFLICT (cols)`。

    不按单个字面量配对：durability_pg 等处的 SQL 是跨多行多字面量拼接的，按字面量
    配会整批漏抽（初版实跑 10 处 vs 实际数十处）。取"最近的前置 INSERT INTO"，
    且表名是插值占位（`{...}`）时跳过——那类走 spec 常量通道。
    """
    ins = [(m.start(), m.group(1).lower().strip("\"'"), text[: m.start()].count("\n") + 1) for m in _INSERT_INTO.finditer(text)]
    out: list[tuple[str, tuple[str, ...], int]] = []
    for m in _ON_CONFLICT.finditer(text):
        raw_cols = m.group(1)
        # 键名本身是 f-string 表达式或运行期变量（`{', '.join(key_cols)}`、
        # `{conflict_col}`）⇒ 静态读不出列，交 M-4 登记，不许当成"列名叫 {"}"报违规
        if "{" in raw_cols or "%" in raw_cols or "'" in raw_cols:
            continue
        cols = _norm_cols(raw_cols)
        if not cols:
            continue
        lineno = text[: m.start()].count("\n") + 1
        prior = [i for i in ins if i[0] < m.start() and m.start() - i[0] < 1200]
        if not prior:
            continue
        table = prior[-1][1]
        if not table or table.startswith("%"):
            continue
        # `{self._table}` 这类动态表名**保留原样**交给调用侧判定（弱通道），
        # 不许在这里硬猜成某张具体的表
        out.append((table, cols, lineno))
    return out


def _spec_tuple_targets(py: Path) -> list[tuple[str, tuple[str, ...], int]]:
    """`NAME = ("table", ("key", "cols"), ("updatable",))` 形态的仓储常量。

    `_upsert` 把冲突键从常量拼出来（`ON CONFLICT ({', '.join(key_cols)})`），文本里
    根本没有字面键名——meta_repository 那 6 张表（B-3 的现场）只能从这里取。
    """
    out: list[tuple[str, tuple[str, ...], int]] = []
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 3):
            continue
        spec = node.value.elts
        if not (isinstance(spec[0], ast.Constant) and isinstance(spec[0].value, str)):
            continue
        if not isinstance(spec[1], ast.Tuple) or not spec[1].elts:
            continue
        cols = tuple(
            sorted(e.value.lower() for e in spec[1].elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
        )
        if len(cols) != len(spec[1].elts):
            continue
        target = getattr(spec[1].elts[0], "ctx", None)
        if isinstance(target, ast.Store):  # 目标位置不可能是要素，非表规格
            continue
        out.append((spec[0].value.lower(), cols, node.lineno))
    return out


def check_conflict_keys(dirs: list[Path]) -> tuple[list[str], int, list[str], list[str], list[str]]:
    """M-2：ON CONFLICT 目标键必须被最终态唯一键覆盖。

    返回 (违规, 校验数, 未识别表名, 抽取不到目标的文件, 动态表名弱通道命中)。
    后三类进 M-4 登记与 -v 汇报，让覆盖缺口可见而不是静默通过。
    """
    per_dir_keys = {str(mig_dir.relative_to(ROOT)): build_final_keys(mig_dir) for mig_dir in dirs}
    py_keys = _python_ddl_tables()
    # 表名 → 键集合，外加"去掉前缀也能查到"的索引（仓储常量存的是去前缀名）
    index: dict[str, set[tuple[str, ...]]] = {}
    for keys in per_dir_keys.values():
        for table, colsets in keys.items():
            index[table] = index.get(table, set()) | colsets
    for table, colsets in py_keys.items():
        index.setdefault(table, set()).update(colsets)

    problems: list[str] = []
    checked = 0
    unknown: list[str] = []
    blind: list[str] = []
    dynamic_hits: list[str] = []
    for py in _production_py():
        if not py.is_file():
            continue
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        try:
            text = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not _ON_CONFLICT.search(text):
            continue  # 只在注释/docstring 里提 ON CONFLICT（无括号目标）不算站点
        targets = _conflict_targets_from_text(text)
        # spec 常量通道无条件并跑：`_upsert` 的键是从常量拼出来的，文本配对看不见
        seen = {(t, c) for t, c, _ in targets}
        for t, c, lineno in _spec_tuple_targets(py):
            if (t, c) not in seen:
                targets.append((t, c, lineno))
        if not targets:
            blind.append(rel)
            continue
        for table, cols, lineno in targets:
            checked += 1
            if "{" in table:
                # 动态表名（来自构造参数）：退化为"该键集必须在全链任一表上存在"，
                # 弱一档但仍能咬住 B-3 那类"键在新 schema 里根本不存在"。
                all_keys = {uk for ks in index.values() for uk in ks}
                if not any(set(cols) <= set(uk) for uk in all_keys):
                    problems.append(
                        f"M-2 {rel}:{lineno}: 动态表名 {table} 的 ON CONFLICT {cols} "
                        f"在迁移链最终态**任何**表上都无覆盖键（真 PG 42P10）"
                    )
                else:
                    dynamic_hits.append(f"{rel}:{lineno} {table}{cols}")
                continue
            match = index.get(table)
            if match is None:
                # 仓储常量里是不带前缀的表名（nl2sql_ 前缀在运行时拼）：按后缀找
                suffix_hits = {t: ks for t, ks in index.items() if t.endswith("_" + table) or t == table}
                if len(suffix_hits) == 1:
                    table_key, match = next(iter(suffix_hits.items()))
                else:
                    unknown.append(f"{rel}:{lineno} {table}")
                    continue
            if not any(set(cols) <= set(uk) for uk in match):
                problems.append(
                    f"M-2 {rel}:{lineno}: ON CONFLICT {table}{cols} 在迁移链最终态无覆盖"
                    f"它的唯一键（真 PG 42P10）。该表已声明键集：{sorted(match)}"
                )
    return problems, checked, unknown, blind, dynamic_hits


def check_blind_registry(blind: list[str]) -> list[str]:
    """M-4：抽取盲区登记表双向对称差（登记必须带证据，判据修好了就得删条目）。"""
    problems = [
        f"M-4 {f} 有 ON CONFLICT 但一个目标都没抽到，且未登记 ⇒ 判据出现新盲区。"
        f"要么补抽取规则，要么登记它为何暂时抽不出（附证据），后者让本门禁知情而非静默"
        for f in sorted(set(blind) - set(_COVERAGE_BLIND))
    ]
    problems += _registry_diff(_COVERAGE_BLIND, set(blind), "M-4 抽取盲区")
    return problems


def _selftest() -> list[str]:
    """合成违规样本：判据必须咬到它们，否则门禁在空转（每行是一条会被咬中的形状）。"""
    problems: list[str] = []
    if "nl2sql_ghost" not in _collect_refs("SELECT 1 FROM nl2sql_ghost"):
        problems.append("SELFTEST M-1: FROM 后的关系名没被抓到 ⇒ 引用判据空转")
    if "nl2sql_in_comment" in _collect_refs(_strip_comments("-- nl2sql_in_comment\nSELECT 1 FROM x")):
        problems.append("SELFTEST M-1: 注释里的表名被当成引用 ⇒ 假阳性源")
    if "set" in _collect_refs("INSERT INTO t (a) VALUES (%s) ON CONFLICT (a) DO UPDATE SET a = 1"):
        problems.append("SELFTEST M-1: `DO UPDATE SET` 的关键字被当关系名 ⇒ 假阳性源")

    multi = "id bigserial primary key,\n question text not null,\n PRIMARY KEY (a, b),\n CONSTRAINT uq_x UNIQUE (c, d)"
    vals = set(_slots_of_body(multi).values())
    for expect in {("id",), ("a", "b"), ("c", "d")}:
        if expect not in vals:
            problems.append(f"SELFTEST M-2: 键抽取漏了 {expect} -> {vals}")
    if _slots_of_body("question text, UNIQUE (c, d)").get("__anon_0") != ("c", "d"):
        problems.append("SELFTEST M-2: 匿名 UNIQUE 读不出（001 的匿名约束形态）")

    paired = _conflict_targets_from_text(
        'sql = (\n  "INSERT INTO budget_usage (a,b) VALUES (%s,%s) "\n  "ON CONFLICT (tenant_id, dimension) DO UPDATE "\n)'
    )
    if ("budget_usage", ("dimension", "tenant_id"), 3) not in paired:
        problems.append(f"SELFTEST M-2: 跨字面量拼接的 upsert 没配对上 -> {paired}")
    dyn = _conflict_targets_from_text('f"INSERT INTO {self._table} (execution_id) VALUES ON CONFLICT (execution_id)"')
    if dyn and dyn[0][0] != "{self._table}":
        problems.append(f"SELFTEST M-2: 动态表名不该被硬换成别的表 -> {dyn}")
    if _conflict_targets_from_text('f"INSERT INTO t (a) VALUES ON CONFLICT ({cols})"'):
        problems.append("SELFTEST M-2: 键名是运行期表达式时不该造出目标（该走 M-4 登记）")
    if _conflict_targets_from_text('"ON CONFLICT (a) DO NOTHING"'):
        problems.append("SELFTEST M-2: 没有 INSERT 时不该凭空造出目标")
    split = _join_adjacent_literals("EXECUTE 'ALTER TABLE x ADD CONSTRAINT uq_y '\n    'UNIQUE (a, b)';")
    if not _ALTER_ADD_UNIQUE.findall(split):
        problems.append(f"SELFTEST M-2: 跨行续写字符串的换键语句读不出 -> {split!r}")

    if not _registry_diff({"ghost": "证据"}, set(), "M-3"):
        problems.append("SELFTEST M-3/M-4: 登记项未被命中却不判红 ⇒ 登记表机制空转")
    if _registry_diff({}, {"ghost"}, "M-3"):
        problems.append("SELFTEST M-3/M-4: 空登记表被误判为违规")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="迁移 SQL 静态门禁（无 PG 依赖）")
    ap.add_argument("--selftest", action="store_true", help="额外跑合成违规样本，证明判据非空转")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印未识别表名清单")
    args = ap.parse_args(argv)

    try:
        dirs = _discover_migration_dirs()
    except RuntimeError as exc:
        print(f"[FAIL] 迁移目录枚举失效: {exc}")
        return 2

    problems, hit = check_refs(dirs)
    problems += check_external_registry(hit)
    m2, checked, unknown, blind, dynamic_hits = check_conflict_keys(dirs)
    problems += m2
    problems += check_blind_registry(blind)
    if args.selftest:
        problems += _selftest()

    for line in problems:
        print(f"[FAIL] {line}")
    print(
        f"迁移静态门禁：迁移目录 {len(dirs)} 个（"
        f"{', '.join(str(d.relative_to(ROOT)).replace(chr(92), '/') for d in dirs)}）；"
        f"M-1 引用闭包 + M-3 登记表({len(hit)}/{len(_EXTERNAL)} 项) + "
        f"M-2 冲突目标校验 {checked} 处（盲区文件 {len(blind)}，登记 {len(_COVERAGE_BLIND)}）"
        f" + M-4 盲区对称差；违规 {len(problems)} 项"
    )
    if args.verbose and unknown:
        print("[INFO] M-2 未识别表名（不判违规，仅暴露覆盖缺口）：")
        for u in unknown:
            print(f"       - {u}")
    if args.verbose and blind:
        print("[INFO] M-4 当前抽取盲区文件：" + ", ".join(sorted(blind)))
    if args.verbose and dynamic_hits:
        print(f"[INFO] M-2 动态表名走弱通道（只验「全链存在此键集」）{len(dynamic_hits)} 处：")
        for d in dynamic_hits:
            print(f"       - {d}")
    if checked == 0:
        print("[FAIL] M-2 校验数为 0：冲突目标抽取判据没咬到任何生产 SQL，视为门禁失效")
        return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
