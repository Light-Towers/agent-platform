"""Vanna 式 Text-to-SQL 管线：召回上下文 → LLM 生成 → 白名单守卫 → 只读执行。

执行层双保险：守卫校验 + 连接级只读（sqlite URI mode=ro / PG default_transaction_read_only）。
"""

import asyncio
import re
import sqlite3
import urllib.parse

from agent_core.sql.guard import validate_sql

from app.config import get_settings
from app.sql.guard import detect_dialect
from app.sql.schema_store import fetch_context

_SYSTEM_PROMPT = (
    "你是严谨的数据库分析助手。根据给定的表结构(DDL)、业务文档和历史 SQL 范例，"
    "把用户问题转换为一条只读 SELECT SQL。要求：\n"
    "1. 只输出一个 ```sql 代码块，不要解释；\n"
    "2. 只用 DDL 中存在的表和列；\n"
    "3. 业务口径以文档为准；\n"
    "4. 优先参考与问题相似的范例 SQL。"
)


def build_prompt(question: str, context: dict) -> str:
    parts = ["## 表结构 DDL"]
    parts.extend(context["ddl"] or ["（未提供）"])
    parts.append("\n## 业务文档")
    parts.extend(context["docs"] or ["（未提供）"])
    parts.append("\n## 历史 SQL 范例")
    for ex in context["examples"]:
        parts.append(f"问题: {ex['question']}\nSQL: {ex['sql']}")
    if not context["examples"]:
        parts.append("（未提供）")
    parts.append(f"\n## 用户问题\n{question}")
    return "\n".join(parts)


def extract_sql(text: str) -> str:
    """从 LLM 输出中提取 SQL：优先 ```sql 代码块，退化为整体文本。"""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()


def _run_sqlite(path: str, sql: str, max_rows: int) -> dict:
    conn = sqlite3.connect(f"file:{urllib.parse.unquote(path)}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchmany(max_rows)]
    finally:
        conn.close()
    return {"columns": columns, "rows": rows}


async def execute_readonly(sql: str, max_rows: int) -> dict:
    """在业务库上只读执行；未配置 SQL_DSN 时返回明确提示。"""
    settings = get_settings()
    dsn = settings.sql_dsn
    if not dsn:
        raise RuntimeError("SQL_DSN 未配置，无法执行查询")

    if dsn.startswith("sqlite:///"):
        path = dsn[len("sqlite:///") :]
        return await asyncio.to_thread(_run_sqlite, path, sql, max_rows)

    if dsn.startswith("postgres"):
        import psycopg

        # 连接级只读第二道防线：用 psycopg 原生 options 参数（避免 URL 编码在含 ?
        # 的 conninfo 下被版本相关行为跳过），并在建连后显式 SET 双保险，
        # 即使白名单守卫被绕过（如 sqlglot 未知 CVE），业务库也不可写入。
        async with await psycopg.AsyncConnection.connect(
            dsn, options="-c default_transaction_read_only=on"
        ) as conn:
            await conn.execute("SET default_transaction_read_only = on")
            cur = await conn.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = [list(r) async for r in cur]
        return {"columns": columns, "rows": rows[:max_rows]}

    raise RuntimeError(f"暂不支持的业务库类型: {dsn.split('://')[0]}（MySQL 留待 Phase 3）")


async def text_to_sql(pool, question: str, llm=None) -> dict:
    """完整管线；返回 {question, context_found, sql, result|error}。"""
    settings = get_settings()
    context = await fetch_context(pool, question)
    context_found = bool(context["ddl"] or context["docs"] or context["examples"])

    if llm is None:
        return {
            "question": question,
            "context_found": context_found,
            "sql": None,
            "error": "LLM 未配置，无法生成 SQL",
        }

    raw = await llm.ainvoke(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": build_prompt(question, context)}]
    )
    candidate = extract_sql(raw.content if hasattr(raw, "content") else str(raw))
    dialect = detect_dialect(settings.sql_dsn)
    ok, reason, safe_sql = validate_sql(candidate, dialect, settings.sql_max_rows)
    if not ok:
        return {
            "question": question,
            "context_found": context_found,
            "sql": candidate,
            "error": f"SQL 被安全守卫拦截: {reason}",
        }

    try:
        result = await execute_readonly(safe_sql, settings.sql_max_rows)
    except Exception as exc:  # noqa: BLE001 执行错误转成结构化结果返回给上层
        return {
            "question": question,
            "context_found": context_found,
            "sql": safe_sql,
            "error": f"SQL 执行失败: {exc}",
        }
    return {
        "question": question,
        "context_found": context_found,
        "sql": safe_sql,
        "result": result,
    }


def format_result(payload: dict) -> str:
    """把管线结果格式化为给 LLM 汇总用的文本证据。"""
    if payload.get("error"):
        return f"SQL 链路失败：{payload['error']}"
    result = payload["result"]
    lines = [f"执行的 SQL：{payload['sql']}", "查询结果（最多展示前 20 行）："]
    lines.append(" | ".join(result["columns"]))
    for row in result["rows"][:20]:
        lines.append(" | ".join(str(v) for v in row))
    if not result["rows"]:
        lines.append("（空结果集）")
    return "\n".join(lines)
