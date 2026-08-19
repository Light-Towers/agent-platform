import pytest

from tools.sql_validation import _validate_identifier, _validate_sql_select_only, _ensure_limit


class TestValidateIdentifier:
    def test_valid_simple(self):
        assert _validate_identifier("users") == "users"

    def test_valid_underscore(self):
        assert _validate_identifier("_test_table") == "_test_table"

    def test_valid_alphanumeric(self):
        assert _validate_identifier("table_2024") == "table_2024"

    def test_reject_semicolon(self):
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("users; DROP TABLE users")

    def test_reject_space(self):
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("users OR 1=1")

    def test_reject_empty(self):
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("")

    def test_reject_start_with_digit(self):
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("1table")


class TestValidateSqlSelectOnly:
    def test_valid_select(self):
        result = _validate_sql_select_only("SELECT * FROM users")
        assert result == "SELECT * FROM users"

    def test_valid_select_with_where(self):
        result = _validate_sql_select_only("SELECT id, name FROM users WHERE id > 10")
        assert "SELECT" in result

    def test_reject_insert(self):
        with pytest.raises(ValueError, match="仅允许 SELECT"):
            _validate_sql_select_only("INSERT INTO users VALUES (1, 'test')")

    def test_reject_delete(self):
        with pytest.raises(ValueError, match="仅允许 SELECT"):
            _validate_sql_select_only("DELETE FROM users WHERE id = 1")

    def test_reject_update(self):
        with pytest.raises(ValueError, match="仅允许 SELECT"):
            _validate_sql_select_only("UPDATE users SET name = 'test'")

    def test_reject_drop(self):
        with pytest.raises(ValueError, match="仅允许 SELECT"):
            _validate_sql_select_only("DROP TABLE users")

    def test_reject_multiple_statements(self):
        with pytest.raises(ValueError, match="单条"):
            _validate_sql_select_only("SELECT 1; SELECT 2")


class TestEnsureLimit:
    def test_adds_limit(self):
        result = _ensure_limit("SELECT * FROM users")
        assert "LIMIT 100" in result

    def test_preserves_existing_limit(self):
        result = _ensure_limit("SELECT * FROM users LIMIT 50")
        assert "LIMIT 50" in result
        assert result.count("LIMIT") == 1

    def test_strips_trailing_semicolon(self):
        result = _ensure_limit("SELECT * FROM users;")
        assert result.endswith("LIMIT 100")
        assert not result.endswith("; LIMIT 100")

    def test_custom_limit(self):
        result = _ensure_limit("SELECT * FROM users", default_limit=500)
        assert "LIMIT 500" in result
