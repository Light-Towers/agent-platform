#!/usr/bin/env python3
"""`scripts/lint_migration_refs.py` 的非空转反证：把缺陷注入**临时副本**，看门禁是否报红。

为什么需要它：门禁刚上线时报绿没有信息量——它可能只是什么都没咬。本脚本三形各一：
  R-3 阴性对照（原样副本）⇒ M-1/M-2 必须零违规（证明红是缺陷造成的，不是判据噪声）
  R-1 注入 B-1 错表名（`nl2sql_example_info` → 从未创建的 `nl2sql_example_corpus`）⇒ M-1 必须报红
  R-2 摘掉 006（模拟"代码先发、迁移没上"）⇒ M-2 视角下 006 建立的目标键必须消失

全程只在 `tempfile` 副本上动，**不碰工作树**。

退出码：`0` = 三形符合预期 · `1` = 反证失败（门禁在空转或判据漂移） · `2` = 前置不可用。

    uv run --no-sync python scripts/evidence/migration_gate_mutation_probe.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import lint_migration_refs as g
except ImportError as exc:
    print(f"[PRE] 取不到 scripts/lint_migration_refs.py: {exc}")
    sys.exit(2)

NL = ROOT / "applications" / "nl2sql-service" / "nl2sql_service" / "migrations"
EXAMPLE_KEY = ("datasource_id", "question", "tenant_id")
fails: list[str] = []


def key_set(mig_dir: Path) -> set[tuple[str, ...]]:
    return {tuple(sorted(k)) for k in g.build_final_keys(mig_dir).get("nl2sql_example_info", set())}


for label, mutate in (
    ("R-3 阴性对照（原样）", None),
    (
        "R-1 注入 B-1 错表名",
        lambda p: p.write_text(
            p.read_text(encoding="utf-8").replace("nl2sql_example_info", "nl2sql_example_corpus"), encoding="utf-8"
        ),
    ),
    ("R-2 摘掉 006（未迁移态）", lambda p: p.unlink()),
):
    tmp = Path(tempfile.mkdtemp(prefix="migmut_"))
    try:
        d = tmp / "migrations"
        shutil.copytree(NL, d)
        if mutate:
            mutate(d / "006_meta_unique_drop_workspace.up.sql")
        m1, _ = g.check_refs([d])
        keys = key_set(d)
        m2_would_fire = EXAMPLE_KEY not in keys
        print(f"=== {label} ===")
        print(f"    M-1 违规 {len(m1)} 项" + (f"，首条: {m1[0][:110]}" if m1 else ""))
        print(f"    example_info 最终键集 = {sorted(keys)} ⇒ M-2 {'会报红' if m2_would_fire else '放行'}")
        if label.startswith("R-3") and (m1 or m2_would_fire):
            fails.append("R-3 阴性对照不干净（原样副本被报红 ⇒ 判据有噪声）")
        if label.startswith("R-1") and not any("nl2sql_example_corpus" in x for x in m1):
            fails.append("R-1 注入的错表名没被 M-1 抓到 ⇒ 门禁空转")
        if label.startswith("R-2") and not m2_would_fire:
            fails.append("R-2 摘掉 006 后 M-2 仍认为目标键存在 ⇒ 门禁空转")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print("\n结论:", "三形反证符合预期" if not fails else f"反证失败: {fails}")
sys.exit(1 if fails else 0)
