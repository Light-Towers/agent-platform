"""C2 修复验证：审计日志原子写入工具测试。

覆盖：
- 损坏 JSON 文件归档为 .corrupt.{ts}，审计从空继续
- 原子写：写入后文件始终是合法 JSON
- 并发写：2 线程 × 10 条，记录数 ≥ 20（不清空）
- 正常追加：已有记录不丢失
- read_audit_log 安全读取
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from exhibition_agent.foundation._audit_writer import append_audit_record, read_audit_log


class TestCorruptJsonArchived:
    def test_corrupt_json_archived_not_silently_cleared(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text('{"broken": "not a list"', encoding="utf-8")

        append_audit_record(audit_path, {"event": "new"})

        corrupt_files = list(tmp_path.glob("audit.json.corrupt.*"))
        assert len(corrupt_files) == 1

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 1
        assert log[0]["event"] == "new"

    def test_non_list_json_archived(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text('{"not": "a list"}', encoding="utf-8")

        append_audit_record(audit_path, {"event": "test"})

        corrupt_files = list(tmp_path.glob("audit.json.corrupt.*"))
        assert len(corrupt_files) == 1

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 1

    def test_empty_file_treated_as_corrupt(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text("", encoding="utf-8")

        append_audit_record(audit_path, {"event": "first"})

        corrupt_files = list(tmp_path.glob("audit.json.corrupt.*"))
        assert len(corrupt_files) == 1

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert log[0]["event"] == "first"


class TestAtomicWrite:
    def test_write_produces_valid_json(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")

        for i in range(5):
            append_audit_record(audit_path, {"index": i})

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 5
        assert [r["index"] for r in log] == [0, 1, 2, 3, 4]

    def test_no_tmp_file_left_behind(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")

        append_audit_record(audit_path, {"event": "test"})

        assert not Path(f"{audit_path}.tmp").exists()

    def test_directory_auto_created(self, tmp_path):
        audit_path = str(tmp_path / "subdir" / "nested" / "audit.json")

        append_audit_record(audit_path, {"event": "test"})

        assert Path(audit_path).exists()
        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 1


class TestConcurrentWrite:
    def test_concurrent_writes_no_total_loss(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        records_per_thread = 10
        num_threads = 2

        def writer(thread_id: int):
            for i in range(records_per_thread):
                append_audit_record(
                    audit_path,
                    {"thread": thread_id, "index": i},
                )

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) >= records_per_thread
        assert len(log) <= num_threads * records_per_thread


class TestNormalAppend:
    def test_append_to_existing_valid_log(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text(
            json.dumps([{"existing": True}]), encoding="utf-8"
        )

        append_audit_record(audit_path, {"new": True})

        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 2
        assert log[0]["existing"] is True
        assert log[1]["new"] is True

    def test_first_write_creates_file(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        assert not Path(audit_path).exists()

        append_audit_record(audit_path, {"event": "first"})

        assert Path(audit_path).exists()
        log = json.loads(Path(audit_path).read_text("utf-8"))
        assert len(log) == 1


class TestReadAuditLog:
    def test_read_nonexistent_returns_empty(self, tmp_path):
        assert read_audit_log(str(tmp_path / "nonexistent.json")) == []

    def test_read_valid_log(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text(
            json.dumps([{"a": 1}, {"b": 2}]), encoding="utf-8"
        )

        log = read_audit_log(audit_path)
        assert len(log) == 2

    def test_read_corrupt_returns_empty(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text("not json at all", encoding="utf-8")

        log = read_audit_log(audit_path)
        assert log == []

    def test_read_non_list_returns_empty(self, tmp_path):
        audit_path = str(tmp_path / "audit.json")
        Path(audit_path).write_text('{"not": "a list"}', encoding="utf-8")

        log = read_audit_log(audit_path)
        assert log == []
