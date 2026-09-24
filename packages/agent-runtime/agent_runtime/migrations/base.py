"""Migration protocol & registry（P1-4 轻量版 schema 迁移）。

设计：
- 每个迁移 = 一对 .sql 文件（up 必需，down 可选）；
- 命名约定：{NNN}_{name}.up.sql / {NNN}_{name}.down.sql；
- Migration 对象仅持有元数据 + 文件路径，runner 负责读文件与执行；
- 模板变量：SQL 文件内可用 {{vector_dim}} 占位符，runner 统一替换。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 匹配文件名：001_name.up.sql 或 001_name.down.sql
_FILE_PATTERN = re.compile(r"^(\d+)_(.+)\.(up|down)\.sql$")

# migrations 包所在目录
_MIGRATIONS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Migration:
    """单个 schema 迁移的元数据描述。

    Attributes:
        version:  单调递增整数（取自文件名前缀）。
        name:     人类可读短描述（取自文件名中段）。
        up_sql:   正向迁移 SQL 文件路径。
        down_sql: 回滚 SQL 文件路径（None = 不可逆）。
    """

    version: int
    name: str
    up_sql: Path
    down_sql: Optional[Path] = None

    def read_up(self) -> str:
        """读取正向迁移 SQL 内容。"""
        return self.up_sql.read_text(encoding="utf-8")

    def read_down(self) -> str | None:
        """读取回滚 SQL 内容（无 down 文件返回 None）。"""
        if self.down_sql is None:
            return None
        return self.down_sql.read_text(encoding="utf-8")

    def checksum(self) -> str:
        """基于 up SQL 文件内容的 hash，检测已应用迁移是否被篡改。"""
        try:
            content = self.up_sql.read_bytes()
        except OSError:
            content = f"{self.version}:{self.name}".encode()
        return hashlib.sha256(content).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Discovery (file-based scanning)
# ---------------------------------------------------------------------------

_REGISTRY: list[Migration] = []
_DISCOVERED = False


def discover(directory: Path | None = None) -> list[Migration]:
    """扫描 migrations/ 目录，返回按 version 排序的迁移列表。

    Args:
        directory: 自定义扫描目录（默认本包目录，测试可传入临时目录）。
    """
    global _DISCOVERED, _REGISTRY
    if _DISCOVERED and directory is None:
        return _REGISTRY

    scan_dir = directory or _MIGRATIONS_DIR
    entries: dict[int, dict[str, Path]] = {}

    for f in sorted(scan_dir.iterdir()):
        if not f.is_file():
            continue
        m = _FILE_PATTERN.match(f.name)
        if not m:
            continue
        version = int(m.group(1))
        name = m.group(2).replace("_", " ")
        direction = m.group(3)

        if version not in entries:
            entries[version] = {"name": Path(name)}  # type: ignore
        entries[version][direction] = f

    result: list[Migration] = []
    for ver in sorted(entries):
        info = entries[ver]
        up_path = info.get("up")
        if up_path is None:
            logger.warning("migration v%d has no .up.sql, skipping", ver)
            continue
        down_path = info.get("down")
        name = str(info["name"])
        result.append(Migration(
            version=ver,
            name=name,
            up_sql=up_path,
            down_sql=down_path,
        ))

    if directory is None:
        _REGISTRY = result
        _DISCOVERED = True

    return result


def max_version() -> int:
    """已发现迁移中的最大 version（空集返回 0）。"""
    migrations = discover()
    return migrations[-1].version if migrations else 0


def reset() -> None:
    """重置 registry 缓存（测试用）。"""
    global _REGISTRY, _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False


__all__ = ["Migration", "discover", "max_version", "reset"]
