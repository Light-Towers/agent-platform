"""
审计日志原子写入工具。

解决 read-modify-write 静默清空问题：
  - 损坏 JSON 归档为 .corrupt.{timestamp} 而非静默清空
  - 原子写（tmp + os.replace）避免截断
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_guard:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def append_audit_record(path: str, record: dict) -> None:
    """
    原子追加审计记录到 JSON array 文件。

    损坏文件归档为 {path}.corrupt.{timestamp}，从空列表继续。
    写入使用 tmp + os.replace 保证原子性。
    进程内 threading.Lock 串行化同路径并发写。
    """
    with _get_lock(path):
        _do_append(path, record)


def _do_append(path: str, record: dict) -> None:
    audit_log: list = []

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                audit_log = json.load(f)
            if not isinstance(audit_log, list):
                logger.warning(
                    "Audit log %s is not a list, archiving and starting fresh",
                    path,
                )
                _archive_corrupt(path)
                audit_log = []
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to load audit log %s, archiving corrupt file", path)
            _archive_corrupt(path)
            audit_log = []

    audit_log.append(record)

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = f"{path}.tmp.{uuid.uuid4().hex}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(audit_log, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def read_audit_log(path: str) -> list:
    """
    安全读取审计日志。

    文件不存在返回空列表。
    损坏文件打日志并返回空列表（不归档，归档仅在写入时发生）。
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("Audit log %s is not a list, returning empty", path)
            return []
        return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read audit log %s, returning empty", path)
        return []


def _archive_corrupt(path: str) -> None:
    """将损坏文件重命名为 .corrupt.{timestamp}。"""
    if not os.path.exists(path):
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    corrupt_path = f"{path}.corrupt.{ts}"
    try:
        os.replace(path, corrupt_path)
        logger.info("Archived corrupt audit log to %s", corrupt_path)
    except OSError:
        logger.exception("Failed to archive corrupt audit log %s", path)
