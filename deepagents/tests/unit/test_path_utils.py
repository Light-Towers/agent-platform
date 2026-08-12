import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from utils.path_utils import resolve_path


class TestResolvePath:
    def test_virtual_prefix_workspace(self):
        result = resolve_path("/workspace/report.md", "/tmp/output/session_123")
        assert "report.md" in result

    def test_virtual_prefix_mnt(self):
        result = resolve_path("/mnt/data/test.md", "/tmp/output/session_123")
        assert "test.md" in result

    def test_updated_dir(self):
        result = resolve_path("updated/upload/file.pdf", "/tmp/output/session_123")
        assert "updated" in result
        assert "file.pdf" in result

    def test_no_session_dir(self):
        result = resolve_path("sub/test.md", None)
        assert "test.md" in result

    def test_relative_path(self):
        result = resolve_path("sub1/sub2/test.md", "/tmp/output/session_123")
        assert "session_123" in result
        assert "test.md" in result

    def test_session_name_in_path_prevents_nesting(self):
        result = resolve_path("session_123/report.md", "/tmp/output/session_123")
        assert result.count("session_123") <= 2
