#!/usr/bin/env python3
"""TODO.md §0 索引表机械重算（账面自洽门禁）。

**为什么存在**：2026-10-16 追记承诺「复算脚本入库可重跑，本文件为唯一数据源」，
但脚本实际从未提交（指针悬空至 2026-10-19 才补上）⇒ 账面一致性长期只靠口头/目测。
本脚本把「声明值 vs 实算值」变成机械判据。

**口径（先定义再引用，2026-10-19 版）**：

1. 复选框口径 = 行首 ``^- \\[ \\]`` / ``^- \\[x\\]``（re.M）。只认行首：追记正文里
   以 `` `- [ ]` → `- [x]` `` 形式引用复选框形态的文本不得混入（实测顶格与含缩进
   同数，但续行/表格内文本只有行首口径能排除）。
2. §0.1：标题「（N 条）」== 表格 body 行数。
3. §0.2 / §0.4：标题「（N 行在册 = M 条开项 + K 条已销项/清零）」== body 行数 N、
   非 ``~~`` 行数 M（``~~`` 删除线 = 已销项/已清零，本文件既有约定）。
4. §0.3：标题「（N 条」== 表格「条数」列求和（含记 0 的组）。
5. 全文复选框总数 == 本脚本 ``DECLARED_TOTAL`` 常量（**每批追记后必须同批更新**，
   注释注明更新来处；两条链分开记数的约定见 TODO §0 追记三「账面分叉登记」）。
6. **fail-closed**：任何一节标题数字缺失/表格缺失/解析失败 ⇒ MISMATCH（exit 1），
   绝不静默通过（空输出不等于通过——2026-10-16 追记自己踩过的坑）。

用法::

    uv run python scripts/evidence/recount_todo_index.py

全部一致 exit 0；任何不符 exit 1 并逐节打印「声明值 vs 实算值」。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TODO = ROOT / "docs" / "TODO.md"

# 每批翻转复选框后同批更新；注释记录更新来处（追记批次）。
# 现值 = 2026-10-19 追记五（main 链：F01 残差归零后 25/14）。
# 注意 feat/nl2sql-meta-build-recovery 分支另有 5 处翻转未合入（分叉登记见
# TODO §0 追记三）；feat 合入后本常量应随合并结果更新为 20/19（25/14 − 5 开 + 5 闭）。
DECLARED_TOTAL = {"open": 25, "closed": 14}


def _table_body_rows(section_text: str) -> list[str]:
    """取小节内 Markdown 表格的 body 行（去表头与分隔行）。"""
    rows: list[str] = []
    seen_separator = False
    for line in section_text.splitlines():
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s:|-]+\|$", line):
            seen_separator = True
            continue
        if not seen_separator:
            continue  # 表头
        rows.append(line)
    return rows


def _split_sections(text: str) -> dict[str, str]:
    """按 ``### 0.x`` 标题切小节（§0.5 及其后的大节不参与分级判据）。"""
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^### (0\.\d)[ ：]", text, re.M))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else text.find("\n## ", m.start())
        sections[m.group(1)] = text[m.start(): end if end > 0 else len(text)]
    return sections


def _int(pattern: str, text: str, what: str, problems: list[str]) -> int | None:
    m = re.search(pattern, text)
    if not m:
        problems.append(f"标题声明缺失：{what}（正则 {pattern!r} 未命中）")
        return None
    return int(m.group(1))


def recount() -> list[str]:
    """返回不一致清单（空 = 全部一致）。"""
    problems: list[str] = []
    text = TODO.read_text(encoding="utf-8")
    sections = _split_sections(text)

    for key in ("0.1", "0.2", "0.3", "0.4"):
        if key not in sections:
            problems.append(f"§{key} 小节缺失（TODO.md 结构被改？）")
            return problems
        sec = sections[key]
        title_line = sec.splitlines()[0]
        rows = _table_body_rows(sec)
        if not rows:
            problems.append(f"§{key} 表格 body 行数为 0（解析失败或表格被删）")
            continue

        if key == "0.1":
            declared = _int(r"（(\d+) 条）", title_line, "§0.1 条数", problems)
            if declared is not None and declared != len(rows):
                problems.append(f"§0.1 条数：声明 {declared} vs 实算 {len(rows)}")

        elif key == "0.3":
            declared = _int(r"（(\d+) 条", title_line, "§0.3 条数", problems)
            counts = []
            for row in rows:
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) < 2 or not cells[1].isdigit():
                    problems.append(f"§0.3 行「条数」列非整数：{row[:60]}")
                    counts = []
                    break
                counts.append(int(cells[1]))
            if declared is not None and counts and declared != sum(counts):
                problems.append(f"§0.3 条数：声明 {declared} vs 实算求和 {sum(counts)}（{counts}）")

        else:  # 0.2 / 0.4：行在册 + 开项
            declared_rows = _int(r"（(\d+) 行在册", title_line, f"§{key} 行在册", problems)
            if declared_rows is not None and declared_rows != len(rows):
                problems.append(f"§{key} 行在册：声明 {declared_rows} vs 实算 {len(rows)}")
            declared_open = _int(r"(\d+) 条开项", title_line, f"§{key} 开项", problems)
            actual_open = sum(1 for r in rows if "~~" not in r)
            if declared_open is not None and declared_open != actual_open:
                problems.append(f"§{key} 开项：声明 {declared_open} vs 实算 {actual_open}")

    raw_open = len(re.findall(r"^- \[ \]", text, re.M))
    raw_closed = len(re.findall(r"^- \[x\]", text, re.M))
    if raw_open != DECLARED_TOTAL["open"]:
        problems.append(
            f"全文 open：脚本声明 {DECLARED_TOTAL['open']} vs 实算 {raw_open}"
            "（每批翻转后必须同批更新 DECLARED_TOTAL，见 docstring）"
        )
    if raw_closed != DECLARED_TOTAL["closed"]:
        problems.append(
            f"全文 closed：脚本声明 {DECLARED_TOTAL['closed']} vs 实算 {raw_closed}"
            "（每批翻转后必须同批更新 DECLARED_TOTAL，见 docstring）"
        )
    return problems


def main() -> int:
    problems = recount()
    raw_open = len(re.findall(r"^- \[ \]", TODO.read_text(encoding="utf-8"), re.M))
    raw_closed = len(re.findall(r"^- \[x\]", TODO.read_text(encoding="utf-8"), re.M))
    print(f"TODO.md 原始复选框读数：open={raw_open} closed={raw_closed}（口径：行首，re.M）")
    print(f"DECLARED_TOTAL：open={DECLARED_TOTAL['open']} closed={DECLARED_TOTAL['closed']}")
    if problems:
        print("=== MISMATCH ===")
        for p in problems:
            print(f"  {p}")
        return 1
    print("=== 全部一致：PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
