# -*- coding: utf-8 -*-
"""重算 `docs/TODO.md` §0 索引表的声明值 vs 实算值（roadmap 阶段0 #2 的一个落点实例）。

判据来自该索引表自己的括号计数（如「0.3 D 功能面存量（13 条…）」）。表格形态有两类，都要处理：
- 一行一事项（0.1 / 0.2 / 0.4 / 0.5）⇒ body 行数即条数；
- **一行一组 + 独立的「条数」列**（0.3）⇒ 声明值要按该列**求和**，body 行数只是组数。

退出码：全部一致 0；任何一项不符 1（供人复跑时一眼看出，不静默通过）。
**不做成 CI 门禁**：判据含"声明值写在标题里"这一约定，改标题措辞就会报红，属噪声源；
本脚本的定位是"复算时不必手数字"，见 `docs/operations/evidence-format.md` §7 的同类取舍。
"""

from __future__ import annotations

import pathlib
import re
import sys

TODO = pathlib.Path(__file__).resolve().parents[2] / "docs" / "TODO.md"


def _sections(text: str) -> list[tuple[str, int, int]]:
    """返回 [(标题, body 行数, 「条数」列求和)]，只取 §0 下的 ### 子节。"""
    sec0 = re.split(r"^## (?!0\.)", text, maxsplit=1, flags=re.M)[0]
    out = []
    for block in re.split(r"^### ", sec0, flags=re.M)[1:]:
        title = block.splitlines()[0]
        rows = [ln for ln in block.splitlines() if ln.startswith("|")][2:]  # 去表头 + 分隔行
        counted = 0
        for ln in rows:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) > 1 and re.fullmatch(r"\d+", cells[1] or ""):
                counted += int(cells[1])
        out.append((title, len(rows), counted))
    return out


def _declared(title: str) -> int | None:
    m = re.search(r"（(\d+)\s*(?:条|行在册)", title)
    return int(m.group(1)) if m else None


def main() -> int:
    text = TODO.read_text(encoding="utf-8-sig")
    failures: list[str] = []

    print("=== docs/TODO.md §0 索引表复算 ===")
    for title, rows, counted in _sections(text):
        declared = _declared(title)
        if declared is None:
            print(f"  [无声明值] {title[:44]} body_rows={rows}")
            continue
        # 有「条数」列的（0.3）以列为准，否则以行数为准
        actual = counted if counted else rows
        flag = "OK " if actual == declared else "MISMATCH"
        print(f"  [{flag}] declared={declared:<3} actual={actual:<3} body_rows={rows}  {title[:40]}")
        if actual != declared:
            failures.append(title)

    opens = len(re.findall(r"^- \[ \]", text, re.M))
    closed = len(re.findall(r"^- \[x\]", text, re.M))
    print(f"  全文复选框：open={opens} closed={closed}（与 §0.4 / V3 段末条追记的读数对照）")

    if failures:
        print(f"\n❌ {len(failures)} 个分级声明与实算不符，需订正标题或补登条目。")
        return 1
    print("\n✅ 全部一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
