#!/usr/bin/env python3
"""一次性会话身份迁移：**枚举**现存会话标识 → 重挂到 ``tenant-<服务端断言主体>``。

背景（B7b-4 / CodeQL 链① 拆除）：会话身份原先由调用方凭据摘要派生
（``user-<sha256(api_key)[:12]>`` → ``user-<HMAC-SHA256(pepper)[:32]>``）。主体化后新写入的
会话是 ``tenant-<id>``，**不再有任何摘要**，因此历史数据需要一次性重挂。

为何是「枚举」而不是「复算」（这是本脚本形态的根因，勿改回）：
- 旧 thread_id **本已存在于数据里**（``updated/session_*`` 目录名、``checkpoints.thread_id`` 行），
  不需要从密钥反算就能拿到；复算要求脚本持有凭据原文，而那些凭据可能早已轮转/不可得。
- 因此本脚本**不含任何 hashlib / hmac**（由 ``tests/governance/test_thread_identity_migration.py``
  的 AST 用例锁死）。一旦有人想「加回 --api-key 直接算」，那条用例会红。

判别式（前缀换成 ``tenant-`` 后才成立，这也是 A-1 换前缀与迁移必须同批的原因）：
- 待迁移集合 = ``^user-[0-9a-f]{12}$`（legacy 48bit）或 ``^user-[0-9a-f]{32}$``（现行 128bit 摘要），
  两代都是凭据派生、都要重挂；
- ``user-`` 开头但不命中上式者**一律不动**并列入人工核实（已知两类来源：
  ``api/monitor.py`` 的 ``build_thread_id()`` 产出 ``user-<uid>-session-<sid>``（零调用者的兼容符号）、
  开发模式客户端自填如 ``user-x``）；
- 主体化后新写入的 ``tenant-*`` 天然不在 ``user-`` 集合内 ⇒ 不需长度/字符集启发式。

安全边界（刻意的取舍，勿"顺手"扩展）：
- **默认 dry-run**，须显式 ``--apply`` 才改名；兼容窗口内旧目录**只读不删**（改名即可回滚）；
- **目标已存在则拒绝覆盖**（碰撞属人工核实项，绝不静默合并两个会话）；
- **不直连数据库执行 UPDATE**：本仓库 CI 无 PG，SQL 路径无法在此实跑验证，故只**打印**语句，
  由运维在备份后自行执行（避免把一个未验证的破坏性写操作固化进脚本）。

局限（必须写破，属部署侧前置核实项）：枚举法把「历史上存在过多把密钥」的部署视作**同一主体**
——一把密钥 = 一个部署的现状下等价成立；若某部署曾把多把密钥分给不同租户，则它们会被并入
同一个 ``tenant-<principal>``，需按本脚本列出的 source 清单人工分拆。

用法::

    # 1) 只枚举、只看计划（无任何副作用）
    uv run python scripts/migrate_thread_identity.py --principal acme \\
        --sessions-dir applications/agent_federation/updated

    # 2) 复核计划后执行目录改名（旧目录不删，可 rename 回去）
    uv run python scripts/migrate_thread_identity.py --principal acme \\
        --sessions-dir applications/agent_federation/updated --apply

    # 3) 打印 checkpointer 表需要执行的 SQL（人工在备份后执行）；
    #    --source 可重复，传只读查询枚举出来的旧 id（不传则只出只读核实语句）
    uv run python scripts/migrate_thread_identity.py --principal acme --emit-sql \\
        --source user-0123456789ab --source user-0123456789abcdef0123456789abcd
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from agent_core.guardrails.auth import resolve_thread_identity

# LangGraph AsyncPostgresSaver 落库表（thread_id 为键的三张表）
_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_writes", "checkpoint_blobs")

# 两代凭据摘要形态（legacy 48bit 截断 / 现行 128bit），两者都要重挂
_LEGACY_DIGEST_RES = (
    re.compile(r"^user-[0-9a-f]{12}$"),
    re.compile(r"^user-[0-9a-f]{32}$"),
)

# 旧前缀（历史数据的字面量，与 kernel THREAD_ID_PREFIX 无关，勿合并）
_LEGACY_PREFIX = "user-"

# federation /api/upload 的会话目录前缀：``session_<thread_id>``
_SESSION_DIR_PREFIX = "session_"


def is_credential_digest(thread_id: str) -> bool:
    """是否为「凭据摘要形态」的旧 thread_id（即待迁移集合）。"""
    return any(rx.match(thread_id) for rx in _LEGACY_DIGEST_RES)


def needs_manual_review(thread_id: str) -> bool:
    """``user-`` 开头但不命中摘要形态 ⇒ 既非待迁移也非新格式，不得自动改名。"""
    return thread_id.startswith(_LEGACY_PREFIX) and not is_credential_digest(thread_id)


def session_dir_name(thread_id: str) -> str:
    """federation ``/api/upload`` 的会话目录名（``safe_filename`` 对这两种形态均为恒等变换）。"""
    return f"{_SESSION_DIR_PREFIX}{thread_id}"


def plan_session_renames(
    sessions_root: Path, principal: str
) -> tuple[list[tuple[Path, Path]], list[str], list[str], str]:
    """枚举 ``sessions_root`` 下的会话目录并分类。

    :return: ``(rename_pairs, skipped_reasons, review_thread_ids, target_thread_id)``

        - ``rename_pairs``：命中摘要形态 → ``(源目录, 目标目录)``；
        - ``skipped_reasons``：幂等跳过（已是目标名）与「目标已存在拒绝覆盖」；
        - ``review_thread_ids``：``user-`` 前缀但非摘要形态 ⇒ 人工核实，**不动**；
        - ``target_thread_id``：本次重挂的目标 id。

        多个源目录命中同一目标时只取排序后的第一个，其余计入 skipped（不会静默合并两个会话）。
    """
    target = resolve_thread_identity(principal)
    target_dir = sessions_root / session_dir_name(target)

    pairs: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    review: list[str] = []

    for child in sorted(sessions_root.iterdir()) if sessions_root.is_dir() else []:
        if not child.is_dir():
            continue
        tid = child.name[len(_SESSION_DIR_PREFIX):] if child.name.startswith(_SESSION_DIR_PREFIX) else None
        if tid is None:
            continue  # 非 session_* 目录不参与
        if tid == target:
            skipped.append(f"已是目标格式，跳过（幂等）：{child}")
            continue
        if is_credential_digest(tid):
            if pairs:  # 已有一个源挂向同一目标：其余交人工核实，不合并
                skipped.append(f"目标 {target_dir} 已被 {pairs[0][0]} 占用，本目录不并挂：{child}")
                review.append(tid)
                continue
            if target_dir.exists():
                skipped.append(f"目标已存在，拒绝覆盖：{target_dir}（请人工核实是否与 {child} 重复）")
                continue
            pairs.append((child, target_dir))
        elif needs_manual_review(tid):
            review.append(tid)

    return pairs, skipped, review, target


def apply_session_renames(pairs: list[tuple[Path, Path]]) -> int:
    """执行改名，返回成功条数。"""
    moved = 0
    for src, dst in pairs:
        src.rename(dst)
        moved += 1
        print(f"  renamed: {src} → {dst}")
    return moved


def build_verification_sql(target_thread_id: str) -> list[str]:
    """只读核实语句（先跑它拿到待迁移清单，再决定要不要执行 UPDATE）。

    PG 的 ``LIKE`` 不认正则，故取 ``user-`` 候选、由本脚本（或人工）按定长 hex 判别定案；
    两侧各自 ``<>`` 目标名以保幂等。宁可多捞再筛，不可漏筛。
    """
    stmts: list[str] = []
    for table in _CHECKPOINT_TABLES:
        stmts.append(
            f"SELECT DISTINCT thread_id FROM {table} "
            f"WHERE thread_id LIKE '{_LEGACY_PREFIX}%' AND thread_id <> '{target_thread_id}';"
        )
    return stmts


def build_checkpoint_sql(target_thread_id: str, source_thread_ids: list[str]) -> list[str]:
    """生成 checkpointer 表 thread_id 改名 SQL（**仅打印，不在本脚本执行**）。

    参数以百分号占位以免 SQL 注入面：运维请用绑定变量替换后执行。
    只接受命中摘要形态的 source（其余形态属人工核实项，脚本不猜）。
    """
    stmts: list[str] = []
    for source in sorted(set(source_thread_ids)):
        if not is_credential_digest(source):
            continue
        for table in _CHECKPOINT_TABLES:
            stmts.append(
                f"UPDATE {table} SET thread_id = %s WHERE thread_id = %s;  "
                f"-- new={target_thread_id} old={source}"
            )
    return stmts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="会话身份 枚举式迁移：旧凭据摘要 id → tenant-<主体>")
    parser.add_argument(
        "--principal",
        default=os.getenv("SINGLE_TENANT", ""),
        help="目标主体（服务端已断言的租户 id；默认取 env SINGLE_TENANT）——**不是密钥**",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help="federation updated/ 根目录（其下为 session_* 子目录）",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="THREAD_ID",
        help="只读查询枚举出的旧 thread_id（可重复）；用于生成 UPDATE 语句",
    )
    parser.add_argument("--emit-sql", action="store_true", help="打印 checkpointer 表迁移 SQL")
    parser.add_argument("--apply", action="store_true", help="真正执行改名（默认 dry-run）")
    args = parser.parse_args(argv)

    if not args.principal.strip():
        print(
            "错误：需 --principal（服务端断言的租户主体）或设置环境变量 SINGLE_TENANT；"
            "本脚本不接受密钥——旧 id 从数据里枚举，不从密钥复算",
            file=sys.stderr,
        )
        return 2

    try:
        target = resolve_thread_identity(args.principal)
    except ValueError as e:
        print(f"错误：--principal 非法（{e}）", file=sys.stderr)
        return 2

    print(f"principal      : {args.principal.strip()}")
    print(f"target  thread_id : {target}")
    print("旧形态         : user-<12hex>（48bit 截断）/ user-<32hex>（128bit 摘要），两代都重挂")

    rc = 0
    discovered: list[str] = []
    review: list[str] = []

    if args.sessions_dir is not None:
        root = args.sessions_dir
        if not root.is_dir():
            print(f"错误：--sessions-dir 不存在或不是目录：{root}", file=sys.stderr)
            return 1
        pairs, skipped, manual, target = plan_session_renames(root, args.principal)
        discovered = [src.name[len(_SESSION_DIR_PREFIX):] for src, _ in pairs]
        review = list(manual)
        for reason in skipped:
            print(f"  skipped: {reason}")
        if review:
            print(f"  人工核实（不自动改名，user- 前缀但非凭据摘要形态）：{', '.join(sorted(set(review)))}")
        if not pairs and not skipped:
            print(f"  无需迁移：{root} 下未发现待重挂的 session_{_LEGACY_PREFIX}<digest> 目录")
        elif args.apply:
            print(f"  执行改名（{len(pairs)} 项）：")
            apply_session_renames(pairs)
        else:
            print(f"  [dry-run] 将改名 {len(pairs)} 项（加 --apply 执行）：")
            for src, dst in pairs:
                print(f"    {src} → {dst}")
        # 目标已存在导致的碰撞：以非 0 退出，提示运维这是人工项而非「无事发生」
        rc = 1 if any("拒绝覆盖" in s for s in skipped) else 0

    sources = sorted(set(discovered) | set(args.source))

    if args.emit_sql:
        print("\n-- 第一步：只读核实（先拿到待迁移清单，再决定是否执行写操作）")
        for stmt in build_verification_sql(target):
            print(stmt)
        print(
            "-- 取回的行需按两代形态定案（LIKE 不认正则）："
            f"{ _LEGACY_DIGEST_RES[0].pattern } / { _LEGACY_DIGEST_RES[1].pattern }；"
            "其余 user- 开头者列入人工核实，不自动生成 UPDATE"
        )
        if sources:
            print("\n-- 第二步：改名 SQL（请先备份、人工核实行数后执行；本脚本不代执行）")
            for stmt in build_checkpoint_sql(target, sources):
                print(stmt)
        else:
            print(
                "\n-- 未提供 --source 且未从 --sessions-dir 枚举到旧 id：不生成 UPDATE。"
                "请先跑上面的只读语句，把命中摘要形态的 thread_id 逐个 --source 传入。"
            )

    return rc


if __name__ == "__main__":
    sys.exit(main())
