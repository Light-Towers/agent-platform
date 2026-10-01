#!/usr/bin/env python3
"""一次性会话身份迁移：legacy ``user-{sha256[:12]}`` → 新 ``user-{HMAC-SHA256(pepper)[:32]}``。

背景（CodeQL 收口 Batch 2 / DUP-1）：会话身份派生原先由四处散点的裸 ``sha256(api_key)`` 实现，
已收敛到内核 ``agent_core.guardrails.auth.derive_thread_id``。**派生算法变更会让同一密钥
落到新的 thread_id**，因而：

- agent_federation：``updated/session_user-<legacy>/`` 目录名不再与新会话对齐（历史上传件成为孤儿目录）；
- agent_server / LangGraph：checkpointer 表中 ``thread_id`` 为 legacy 值的行，``/history`` 读不到。

本脚本把 legacy → new 的映射变成**可计算**（依赖内核 ``legacy_thread_id`` 保留旧格式），
并对文件系统部分做显式改名。

安全边界（刻意的取舍，勿"顺手"扩展）：
- **默认 dry-run**，须显式 ``--apply`` 才改名；
- **不直连数据库执行 UPDATE**：本仓库 CI 无 PG，SQL 路径无法在此实跑验证，故只**打印**语句，
  由运维在备份后自行执行（避免把一个未验证的破坏性写操作固化进脚本）。

用法::

    # 1) 只看映射（无任何副作用）
    uv run python scripts/migrate_thread_identity.py --api-key "$API_KEY"

    # 2) 迁移 federation 会话目录（先 dry-run 复核，再 --apply）
    uv run python scripts/migrate_thread_identity.py --api-key "$API_KEY" \
        --sessions-dir applications/agent_federation/updated
    uv run python scripts/migrate_thread_identity.py --api-key "$API_KEY" \
        --sessions-dir applications/agent_federation/updated --apply

    # 3) 打印 checkpointer 表需要执行的 SQL（人工在备份后执行）
    uv run python scripts/migrate_thread_identity.py --api-key "$API_KEY" --emit-sql
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_core.guardrails.auth import derive_thread_id, legacy_thread_id

# LangGraph AsyncPostgresSaver 落库表（thread_id 为键的三张表）
_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_writes", "checkpoint_blobs")


def thread_id_pair(api_key: str | None) -> tuple[str, str]:
    """返回 ``(legacy_thread_id, new_thread_id)``，供迁移两侧对齐。"""
    return legacy_thread_id(api_key), derive_thread_id(api_key)


def session_dir_name(thread_id: str) -> str:
    """federation ``/api/upload`` 的会话目录名（``_sanitize_filename`` 对本格式为恒等变换）。"""
    return f"session_{thread_id}"


def plan_session_renames(
    sessions_root: Path, legacy_thread_id: str, new_thread_id: str
) -> tuple[list[tuple[Path, Path]], list[str]]:
    """扫描 ``sessions_root`` 下待改名的会话目录。

    :return: ``(rename_pairs, skipped_reasons)``——pairs 为 (源, 目标)；
             目标已存在时不覆盖，计入 skipped（碰撞属人工核实项）。
    """
    src = sessions_root / session_dir_name(legacy_thread_id)
    dst = sessions_root / session_dir_name(new_thread_id)
    if not src.is_dir():
        return [], []
    if dst.exists():
        return [], [f"目标已存在，拒绝覆盖：{dst}（请人工核实是否与 {src} 重复）"]
    return [(src, dst)], []


def apply_session_renames(pairs: list[tuple[Path, Path]]) -> int:
    """执行改名，返回成功条数。"""
    moved = 0
    for src, dst in pairs:
        src.rename(dst)
        moved += 1
        print(f"  renamed: {src} → {dst}")
    return moved


def build_checkpoint_sql(legacy_thread_id: str, new_thread_id: str) -> list[str]:
    """生成 checkpointer 表 thread_id 改名 SQL（**仅打印，不在本脚本执行**）。

    参数以百分号占位以免 SQL 注入面：运维请用绑定变量替换后执行。
    """
    stmts: list[str] = []
    for table in _CHECKPOINT_TABLES:
        stmts.append(
            f"UPDATE {table} SET thread_id = %s WHERE thread_id = %s;  "
            f"-- new={new_thread_id} legacy={legacy_thread_id}"
        )
    return stmts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="会话身份 legacy → new 一次性迁移")
    parser.add_argument(
        "--api-key",
        default=os.getenv("API_KEY", ""),
        help="目标密钥（默认取 env API_KEY）；迁移的是该密钥派生的那一个会话身份",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help="federation updated/ 根目录（其下为 session_* 子目录）",
    )
    parser.add_argument("--emit-sql", action="store_true", help="打印 checkpointer 表迁移 SQL")
    parser.add_argument("--apply", action="store_true", help="真正执行改名（默认 dry-run）")
    args = parser.parse_args(argv)

    if not args.api_key:
        print("错误：需 --api-key 或设置环境变量 API_KEY（派生会话身份的前提）", file=sys.stderr)
        return 2

    legacy, new = thread_id_pair(args.api_key)
    print(f"legacy thread_id : {legacy}")
    print(f"new   thread_id  : {new}")
    pepper_state = "已配置" if os.getenv("AGENT_PLATFORM_SECURITY_PEPPER") else "未配置"
    print(f"pepper ({pepper_state}) : AGENT_PLATFORM_SECURITY_PEPPER 变更后 new 值会漂移，"
          "务必与线上部署一致")

    rc = 0
    if args.sessions_dir is not None:
        root = args.sessions_dir
        if not root.is_dir():
            print(f"错误：--sessions-dir 不存在或不是目录：{root}", file=sys.stderr)
            rc = 1
        else:
            pairs, skipped = plan_session_renames(root, legacy, new)
            for reason in skipped:
                print(f"  skipped: {reason}")
                rc = 1
            if not pairs and not skipped:
                print(f"  无需迁移：{root} 下未发现 {session_dir_name(legacy)}")
            elif args.apply:
                print(f"  执行改名（{len(pairs)} 项）：")
                apply_session_renames(pairs)
            else:
                print(f"  [dry-run] 将改名 {len(pairs)} 项（加 --apply 执行）：")
                for src, dst in pairs:
                    print(f"    {src} → {dst}")

    if args.emit_sql:
        print("\n-- checkpointer 迁移 SQL（请先备份，人工核实行数后执行；本脚本不代执行）")
        for stmt in build_checkpoint_sql(legacy, new):
            print(stmt)

    return rc


if __name__ == "__main__":
    sys.exit(main())
