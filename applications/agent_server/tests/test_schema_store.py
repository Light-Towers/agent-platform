"""schema_store + pipeline 契约测试：存取/降级/错误分支。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


class TestFetchContext:
    async def test_pool_none_returns_empty(self):
        from agent_server.sql.schema_store import fetch_context

        result = await fetch_context(None, "test question")
        assert result == {"ddl": [], "docs": [], "examples": []}

    async def test_with_mocked_pool(self):
        from agent_server.sql.schema_store import fetch_context

        mock_pool = MagicMock()

        async def mock_vector_search(pool, table, cols, embedding, k=3):
            if table == "sql_ddl":
                return [("CREATE TABLE t1 (id int)",)]
            if table == "sql_docs":
                return [("doc content",)]
            if table == "sql_examples":
                return [("question1", "SELECT 1",)]
            return []

        with patch("agent_server.sql.schema_store.embed_query", new_callable=AsyncMock, return_value=[0.1, 0.2]), \
             patch("agent_server.sql.schema_store.vector_search", side_effect=mock_vector_search):
            result = await fetch_context(mock_pool, "test", k=3)
        assert len(result["ddl"]) == 1
        assert len(result["docs"]) == 1
        assert len(result["examples"]) == 1
        assert result["examples"][0]["question"] == "question1"


class TestPipeline:
    def test_extract_sql_code_block(self):
        from agent_server.sql.pipeline import extract_sql

        text = "Here is the SQL:\n```sql\nSELECT 1\n```"
        assert "SELECT 1" in extract_sql(text)

    def test_extract_sql_no_block(self):
        from agent_server.sql.pipeline import extract_sql

        assert extract_sql("SELECT 1").strip() == "SELECT 1"

    def test_build_prompt_with_context(self):
        from agent_server.sql.pipeline import build_prompt

        context = {"ddl": ["CREATE TABLE t1"], "docs": ["doc1"], "examples": [{"question": "q", "sql": "s"}]}
        prompt = build_prompt("test question", context)
        assert "CREATE TABLE t1" in prompt
        assert "doc1" in prompt
        assert "test question" in prompt

    def test_build_prompt_empty_context(self):
        from agent_server.sql.pipeline import build_prompt

        prompt = build_prompt("test", {"ddl": [], "docs": [], "examples": []})
        assert "test" in prompt

    async def test_text_to_sql_no_llm(self):
        from agent_server.sql.pipeline import text_to_sql

        result = await text_to_sql(None, "test question", llm=None)
        assert result.get("sql") is None
        assert "error" in result

    def test_format_result_error(self):
        from agent_server.sql.pipeline import format_result

        result = format_result({"question": "q", "sql": None, "error": "test error"})
        assert "test error" in result or "失败" in result

    def test_format_result_success(self):
        from agent_server.sql.pipeline import format_result

        result = format_result({"question": "q", "sql": "SELECT 1", "result": {"columns": ["a"], "rows": [{"a": 1}]}})
        assert isinstance(result, str)


class TestGuard:
    def test_detect_dialect_sqlite(self):
        from agent_server.sql.guard import detect_dialect

        assert detect_dialect("sqlite:///path") == "sqlite"

    def test_detect_dialect_postgres(self):
        from agent_server.sql.guard import detect_dialect

        assert detect_dialect("postgresql://localhost") == "postgres"

    def test_detect_dialect_mysql(self):
        from agent_server.sql.guard import detect_dialect

        assert detect_dialect("mysql://localhost") == "mysql"

    def test_detect_dialect_unknown(self):
        from agent_server.sql.guard import detect_dialect

        assert detect_dialect("unknown://localhost") == "postgres"
