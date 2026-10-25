"""重算 `docs/plans/` 的「状态行有无」——用 docs/README §5/§6 写死的口径，不再手测。

为什么需要这个脚本：§6 那条计数在 10-15 与 10-16 两次成文时给出过 **71 / 82 / 76** 三个分母，
差异全部来自口径没固定（有没有把 `docs/plans/README.md` 与嵌套目录算进去）。
分母不稳 ⇒ 分子也没意义，所以本脚本把口径钉成三条可核对的规则：

1. 范围 = `docs/plans/` **顶层** `.md`，**排除** 同目录的 `README.md`（它是索引不是 plan）；
2. 判据 = 文件前 25 行内匹配 `状态[^。；]{0,14}[:：]`（与 §6 原文一致）；
3. 已知漏计 = 冒号前超过 14 字的写法（如 `状态订正（2026-10-15 补）：`）会被判"未命中"，
   这类文件由 `KNOWN_CALIBER_MISSES` 显式登记 ⇒ 输出「未命中」与「真待补」两个数，不把漏计当缺陷。

退出码：`0` = 一切正常；`1` = `KNOWN_CALIBER_MISSES` 里有文件已不在未命中名单（口径修复了却没删登记，
或文件名写错）⇒ 强制保持这份例外清单与现实一致。

跑法：`uv run python scripts/evidence/recount_plan_status_lines.py`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLANS = Path(__file__).resolve().parents[2] / "docs" / "plans"
HEAD_LINES = 25
STATUS_RE = re.compile(r"状态[^。；]{0,14}[:：]")

# 冒号前超过 14 字 ⇒ 判据漏计，实际已有状态行（修好判据后要从这里删掉）
KNOWN_CALIBER_MISSES = {"p2-bucket-b-reduction-findings-2026-09-24.md"}


def main() -> int:
    if not PLANS.is_dir():
        # 本脚本按 __file__ 推仓库根 ⇒ 复制到别处运行时目录为空，
        # 那会表现为「例外清单过时」而实际原因是路径。宁可显式失败，不给假阳性读数。
        print(f"❌ 找不到 plan 目录：{PLANS}（请把脚本留在 scripts/evidence/ 下运行）", file=sys.stderr)
        return 2
    files = sorted(p for p in PLANS.glob("*.md") if p.name != "README.md")
    hit, miss = [], []
    for p in files:
        head = "\n".join(p.read_text(encoding="utf-8-sig").splitlines()[:HEAD_LINES])
        (hit if STATUS_RE.search(head) else miss).append(p.name)

    stale = sorted(KNOWN_CALIBER_MISSES - set(miss))
    real_pending = sorted(set(miss) - KNOWN_CALIBER_MISSES)
    print(f"分母（顶层 plan md，排除 README）= {len(files)}    命中 = {len(hit)}    未命中 = {len(miss)}")
    print(f"其中口径漏计 = {len(KNOWN_CALIBER_MISSES)} ⇒ **真待补 = {len(real_pending)}**")
    print("\n未命中名单：")
    for name in miss:
        tag = "（口径漏计，实际已有状态行）" if name in KNOWN_CALIBER_MISSES else ""
        print(f"  {name}{tag}")
    if stale:
        print(f"\n❌ 例外清单已过时（这些文件已命中，应从 KNOWN_CALIBER_MISSES 删除）：{stale}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
