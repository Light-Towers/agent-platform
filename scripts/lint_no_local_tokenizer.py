"""架构不变量：检索链路上禁止服务内本地分词实现（ADR-0017 / T14）。

唯一允许的实现是 `agent_runtime.retrieval_tokenizer`；以下白名单只覆盖
"已登记待退役"或"与检索无关的同名函数"，新增条目必须带理由并进 ADR 复审。

- rc=0：扫描面零违规
- rc=1：发现本地分词实现
- rc=2：前置不可用（扫描根缺失）
- --self-test：在临时目录注入违规样本，验证本门禁 rc=1，然后返回 0
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN_ROOTS = (
    "applications/knowledge-service/knowledge_service",
    "applications/agent_server",
    "applications/nl2sql-service/nl2sql_service",
    "packages/agent-runtime/agent_runtime",
)

# 路径相对 ROOT；值是登记理由，禁止无理由扩充。
WHITELIST = {
    "packages/agent-runtime/agent_runtime/retrieval_tokenizer.py": "T14 唯一共享实现",
    "packages/agent-runtime/agent_runtime/vector_sparse.py": "已登记待退役的历史稀疏路（T6 阶段三删除）",
    "applications/knowledge-service/knowledge_service/lm/sparse_vectorizer.py": "已登记待退役的历史稀疏路（T6 阶段三删除）",
    "packages/agent-runtime/agent_runtime/capabilities/registry.py": "_tokenize 用于 capability 名称匹配，非检索词法路",
}

_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(?:[A-Za-z0-9]*_)?tokenize\s*\(", re.MULTILINE)


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _scan(root: Path, whitelist: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = _rel(path)
        if rel in whitelist:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in _DEF_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: {match.group(0).strip()}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="注入违规样本，验证门禁能咬")
    args = parser.parse_args(argv)

    if args.self_test:
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "local_tokenizer.py"
            victim.write_text("def tokenize(text):\n    return list(text)\n", encoding="utf-8")
            if not _scan(Path(tmp), {}):
                print("SELF-TEST FAILED: 注入本地 tokenize 后门禁仍报绿", file=sys.stderr)
                return 1
        print("SELF-TEST PASS: 注入本地 tokenize 后门禁报红")
        return 0

    missing = [name for name in SCAN_ROOTS if not (ROOT / name).is_dir()]
    if missing:
        print(f"前置不可用：扫描根不存在 {missing}", file=sys.stderr)
        return 2

    violations: list[str] = []
    for name in SCAN_ROOTS:
        violations.extend(_scan(ROOT / name, WHITELIST))

    if violations:
        for line in violations:
            print(f"FAIL {line} —— 请改用 agent_runtime.retrieval_tokenizer.get_tokenizer()", file=sys.stderr)
        return 1
    print(f"PASS: {len(SCAN_ROOTS)} 个扫描根零本地分词实现（白名单 {len(WHITELIST)} 项均带理由）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
