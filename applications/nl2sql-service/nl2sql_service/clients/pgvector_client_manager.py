"""pgvector 客户端管理：向量召回 + 全文检索 tsvector/ts_query。

2026-10-18（P0-10 标识符白名单落地）：此前 table/embedding_col/tsvector_col/
extra_cols 与 `filter_clause` 整段 SQL 都是 f-string 直拼——`filter_clause`
尤其危险：它是调用方传进来的 SQL 片段，正则校验不了（S4 登记的最高危点）。
现改为：
- 所有标识符经 `agent_core.sql.identifiers` 白名单校验；
- `filter_clause: str` **取消**，换成结构化 `filters=((列, 值), ...)`——
  谓词由代码生成、值永远参数化，调用方没有"传一段 SQL"的机会。
"""

import re
from collections.abc import Sequence
from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.identifiers import validate_identifier, validate_identifier_list

logger = get_logger(__name__)

#: 至少含一个"词字符"（`\w` 含 CJK）才进 tsquery，纯标点 token 直接丢
_WORD_RE = re.compile(r"\w", re.UNICODE)
#: 单次 tsquery 的 lexeme 上限：关键词爆炸时防超长查询串
_TSQUERY_MAX_TERMS = 20


def build_tsquery(tokens: Sequence[str], max_terms: int = _TSQUERY_MAX_TERMS) -> str:
    """把已分词的 tokens 拼成 `to_tsquery` 表达式：``'tok1' | 'tok2'``。

    2026-10-18（方案 P0-5③ 查询侧）：此前用 `plainto_tsquery`，它把词之间按
    **AND** 连接——一个词没命中就整体空召回；对中文更糟：`'simple'` 配置不分词，
    整串当一个 lexeme，永远匹配不上 Python 侧切出来的 token。
    这里改为**显式 OR + 逐 token 单引号转义**，并保证：
    - token 来自同一个 Python 分词器（写入侧/查询侧单源，方案 B1 前半）；
    - `'` 双写转义，token 内的 `& | ! ( ) : *` 因被引号包住而按字面处理；
    - 空 token / 纯标点 token 丢弃；超过 `max_terms` 截断。

    ⚠️ 索引侧仍由 PG 的某个配置产出 tsvector（`nl2sql_value_info.value_tsvector`，
    生成方式仓内无 DDL，见方案 §2-④/Q23）。中文能否真正命中取决于索引侧分词，
    本函数只保证"查询表达式本身是对的"。
    """
    terms: list[str] = []
    for raw in tokens:
        for piece in str(raw).split():
            if not piece or not _WORD_RE.search(piece):
                continue
            terms.append("'" + piece.replace("'", "''") + "'")
            if len(terms) >= max_terms:
                return " | ".join(terms)
    return " | ".join(terms)


def _where_clause(filters: Sequence[tuple[str, Any]]) -> tuple[str, list[Any]]:
    """结构化过滤 → (WHERE 片段, 参数列表)。列名过白名单，值参数化。"""
    if not filters:
        return "", []
    clauses = [f"{validate_identifier(col, '过滤列')} = %s" for col, _ in filters]
    return " WHERE " + " AND ".join(clauses), [value for _, value in filters]


class PgvectorClientManager:
    """pgvector 向量召回 + Postgres 全文检索。"""

    def __init__(self, pool=None) -> None:
        self._pool = pool

    def set_pool(self, pool) -> None:
        self._pool = pool

    async def vector_search(
        self,
        table: str,
        embedding_col: str,
        query_embedding: list[float],
        top_k: int = 10,
        extra_cols: str = "*",
        filters: Sequence[tuple[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        validate_identifier(table, "检索表名")
        validate_identifier(embedding_col, "向量列名")
        if extra_cols != "*":
            validate_identifier_list(extra_cols, "返回列清单")
        where, params = _where_clause(filters)
        sql = f"SELECT {extra_cols}, {embedding_col} <=> %s AS distance FROM {table}{where}"
        sql += " ORDER BY distance LIMIT %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (*params, query_embedding, top_k))
            rows = await cur.fetchall()
            return [dict(row._mapping) for row in rows]

    async def fulltext_search(
        self,
        table: str,
        tsvector_col: str,
        tokens: Sequence[str],
        top_k: int = 10,
        extra_cols: str = "*",
        filters: Sequence[tuple[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        """全文召回路：tokens 经 `build_tsquery` 变 OR 表达式后执行。

        入参从"整段 query 文本"改为"已分词的 tokens"（2026-10-18）：
        分词只做一次、只在一侧做，避免查询侧 Python 分词与 PG 侧
        `plainto_tsquery('simple')` 两套词表互相认不出。
        `filters` 补上 N3 登记的"全文路无作用域过滤"缺口（P1-1/P1-6 落点）。
        """
        validate_identifier(table, "检索表名")
        validate_identifier(tsvector_col, "tsvector 列名")
        if extra_cols != "*":
            validate_identifier_list(extra_cols, "返回列清单")
        tsquery = build_tsquery(tokens)
        if not tsquery:
            return []
        where, params = _where_clause(filters)
        sql = (
            f"SELECT {extra_cols}, ts_rank({tsvector_col}, to_tsquery('simple', %s)) AS rank "
            f"FROM {table}{where} "
            f"WHERE {tsvector_col} @@ to_tsquery('simple', %s) "
            f"ORDER BY rank DESC LIMIT %s"
        )
        # 参数顺序按 SQL 文本出现序：rank 的 tsquery → filters 值 → @@ 的 tsquery → top_k
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (tsquery, *params, tsquery, top_k))
            rows = await cur.fetchall()
            return [dict(row._mapping) for row in rows]

    async def upsert_vector(
        self,
        table: str,
        data: dict[str, Any],
        embedding_col: str,
        embedding: list[float],
        conflict_col: str = "id",
    ) -> None:
        validate_identifier(table, "写入表名")
        validate_identifier(embedding_col, "向量列名")
        cols = [validate_identifier(c, "写入列名") for c in data.keys()] + [embedding_col]
        placeholders = ", ".join(["%s"] * (len(cols)))
        col_names = ", ".join(cols)
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_col}) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != conflict_col)
        )
        params = tuple(data.values()) + (embedding,)
        async with self._pool.connection() as conn:
            await conn.execute(sql, params)
