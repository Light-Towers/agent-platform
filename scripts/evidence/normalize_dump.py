#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 PowerShell 重定向产物按 BOM 嗅探编码，转成 UTF-8 落盘（可选打印）。

存在理由：PowerShell 的 `>` / `Out-File` 在 Windows PowerShell 5.1 下默认写 **UTF-16 LE**
（带 BOM）。以 utf-8 读会得到「每字符夹一个 NUL」的文本 —— `print` 出来肉眼正常，
但正则匹配与计数全为 0 ⇒ 取证时会把「有内容」误判成「空产物」。本工具把编码判定
固化下来，不再靠每次手写三行。

用法：

    uv run --no-sync python scripts/evidence/normalize_dump.py <文件> [<文件> ...]
    uv run --no-sync python scripts/evidence/normalize_dump.py --no-print <文件>

输出写到 `<原文件名>.utf8`（同名目录内），退出码 0 = 全部转换成功，1 = 有文件读不到。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path


def sniff_encoding(raw: bytes) -> str:
    """按 BOM 判定编码。UTF-16 必须在 UTF-8 之前判，否则 utf-8 解码得到夹 NUL 的假文本。"""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    return "utf-8"


def normalize(path: Path) -> tuple[Path, str, str]:
    """读入 → 嗅探 → 解码 → 剥 NUL → 落 `.utf8`。返回 ``(产物路径, 编码, 文本)``。"""
    raw = path.read_bytes()
    enc = sniff_encoding(raw)
    text = raw.decode(enc, "replace").replace("\x00", "")
    dest = path.with_name(path.name + ".utf8")
    io.open(dest, "w", encoding="utf-8", newline="").write(text)
    return dest, enc, text


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    do_print = True
    if args and args[0] == "--no-print":
        do_print, args = False, args[1:]
    if not args:
        print("用法：normalize_dump.py [--no-print] <文件> ...", file=sys.stderr)
        return 2

    rc = 0
    for name in args:
        p = Path(name)
        try:
            dest, enc, text = normalize(p)
        except OSError as exc:
            print("### %s 读取失败：%s" % (p, exc), file=sys.stderr)
            rc = 1
            continue
        print("### %s bom=%s raw=%dB chars=%d -> %s" % (p, enc, p.stat().st_size, len(text), dest))
        if do_print:
            sys.stdout.write(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
