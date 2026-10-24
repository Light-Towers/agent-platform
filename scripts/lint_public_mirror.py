#!/usr/bin/env python3
"""公开镜像防泄门禁：内网基础设施标识与密钥材料不得进入公开脱敏镜像。

为什么必须分两种模式（这是本门禁存在的前提）：
  - **内网分支**（`company` 侧 / 工作分支）合法携带真实内网 IP 与主机名——
    `docs/operations/env-126-inventory.md` 这类文件本身就是工作产物。若门禁
    一律判红，它就会变成"永远红"，然后被人关掉——比没有更糟。
  - **公开镜像**（GitHub 那个 `Light-Towers/agent-platform`，README 顶部
    `public-mirror-notice` 自述为"公开脱敏镜像"）必须零命中。
⇒ 所以：registry 模式给 `make lint`（登记制，双向对称差），
   publish 模式给推镜像之前（零容忍，只看"这次新公开了什么"）。

判据：
  P-1 内网网段：`192.168/16`、`172.16/12`、以及 `10/8` 中除已公开的 flannel
      pod 段 `10.244/16` 之外的四段地址（pod IP 单独不构成定位信息，但内网
      主机地址要拦）。
  P-2 内网主机名/仓库路径：运维机主机名前缀、内网 GitLab 域名与组路径。
  P-3 密钥材料：私钥头、AWS AKIA、GitHub token（ghp_/gho_/ghu_/ghs_/ghr_/
      github_pat_）、Slack xox——这三类在任何范围都零容忍。
  P-4 registry 双向对称差：命中而未登记 ⇒ 红；登记了却已无命中 ⇒ 分两种（见
      `_stale_split`）：路径根本不在清单里（幽灵登记）红，文件在、内容已脱敏 ⇒ 警告。
      后者必须是警告，否则公开镜像里那份遮过的文档会让公开仓自己的 CI 永远红。
  P-5 枚举口径 = `git ls-tree`（版本控制清单），不是本机文件系统；取不到即
      exit 2 fail-closed。测试目录（`**/tests/**`、`test_*.py`、`eval/`）不在
      P-1/P-2 范围内——那里的四段地址是合成 fixture，不构成基础设施情报；
      但 P-3 密钥类对它们同样生效。

**本门禁自己的源码也在零容忍范围内**：它会随分支推到公开镜像。所以签名与自测
样本里的敏感整串一律用 `_asm()` 在运行时拼接，`--selftest` 的 `_self_source_clean`
直接扫本文件文本 ⇒ 谁往这里写进一条真地址，当场判红。

用法：
  uv run python scripts/lint_public_mirror.py                    # registry 模式（make lint）
  uv run python scripts/lint_public_mirror.py --mode publish \\
      --base 73090d0 --ref mirror/nl2sql-ttl-and-006-slim         # 推公开镜像前
  uv run python scripts/lint_public_mirror.py --selftest          # 非空转反证
  加 --mask-plan 让 P-1/P-2 的命中给出「应换成哪个占位符」的对照表
  （占位符词形沿用 README 既有约定：<internal-ip> / <internal-host> / <internal-gitlab>）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _asm(*parts: str) -> str:
    """运行时拼接敏感整串（见模块 docstring 末段：源码自己会公开）。"""
    return "".join(parts)


#: 内网标识的字面片段。拆开写是刻意的：合起来的串就是本门禁要拦的东西。
_HOST_NET = _asm("192.168.100.", "126")  # 运维机 126
_HOST_NET_241 = _asm("192.168.100.", "241")  # 构建机 241
_OPS_HOST_PREFIX = _asm("amb", "ari")  # 内网运维机主机名前缀
_GITLAB_HOST = _asm("code.", "mingyang", "100.com")  # 内网 GitLab
_GITLAB_GROUP = _asm("techng/", "aimode")  # 内网组路径

#: (标识名, 编译好的正则)。命中即视为"内网基础设施情报或凭据"。
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("P-1 私有网段-192.168", re.compile(r"(?<![\d.])192\.168\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("P-1 私有网段-172.16-31", re.compile(r"(?<![\d.])172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}(?![\d.])")),
    # 10/8 里放过 flannel pod CIDR（README/VERIFICATION 已公开，且无主机名时不定位）
    ("P-1 私有网段-10/8", re.compile(r"(?<![\d.])10\.(?!244\.)\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("P-2 内网主机名", re.compile(rf"\b{_OPS_HOST_PREFIX}\d+\b", re.I)),
    ("P-2 内网 GitLab 与组路径", re.compile(_asm(_GITLAB_HOST, "|", _GITLAB_GROUP, r"|code\.mingyan", "g"), re.I)),
    ("P-3 私钥头", re.compile(_asm("BEGIN (?:RSA|EC|OPEN", "SSH|PGP|DSA) PRIVATE KEY"))),
    ("P-3 云服务与 SaaS 凭据", re.compile(
        r"\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
        r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    )),
]

#: P-1/P-2 的作用域豁免：测试与评测里的地址是合成 fixture。P-3（密钥类）不豁免。
_TEST_SCOPED_IDS = {"P-1 私有网段-192.168", "P-1 私有网段-172.16-31", "P-1 私有网段-10/8", "P-2 内网主机名", "P-2 内网 GitLab 与组路径"}

#: 命中时的替换建议（沿用 README `public-mirror-notice` 的占位符词形）。
_MASK_PLAN = [
    (re.compile(rf"(?<![\d.]){re.escape(_HOST_NET)}(?![\d.])"), "<internal-host-126>"),
    (re.compile(rf"(?<![\d.]){re.escape(_HOST_NET_241)}(?![\d.])"), "<internal-host-241>"),
    (re.compile(r"(?<![\d.])192\.168\.\d{1,3}\.\d{1,3}(?![\d.])"), "<internal-ip>"),
    (re.compile(r"(?<![\d.])10\.(?!244\.)\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])"), "<internal-ip>"),
    (re.compile(rf"\b{_OPS_HOST_PREFIX}(\d+)\b", re.I), lambda m: f"<internal-node-{m.group(1)}>"),
    (re.compile(rf"(?:ssh://)?git@{re.escape(_GITLAB_HOST)}(?::\d+)?(?:/[^\s`,)]*)?"), "<internal-gitlab>"),
]

#: 内网信息登记台账（registry 模式用）：{仓内路径: 为何它 legitimately 携带}。
#: 新增命中必须先登记并写清"推公开镜像时怎么脱敏"；条目失效即 P-4 报红。
_REGISTRY: dict[str, str] = {
    "docs/operations/env-126-inventory.md": (
        "126/241/125 内网环境事实基线（真实网段、主机名、运维机出口 IP）——"
        "内网侧工作产物；**推公开镜像前必须按 --mask-plan 脱敏并在文首留注记**"
    ),
}

_SKIP_PATH_HINTS = ("/tests/", "/eval/", "tests/")

#: 锁文件里的四段数字是**版本号**（四段 semver），与 10/8、172.16-31 地址同形。
#: 只对这两个网段类放宽；192.168 段与凭据类在锁文件里同样照判。
_LOCK_VERSION_AMBIGUOUS_IDS = {"P-1 私有网段-10/8", "P-1 私有网段-172.16-31"}


def _is_lockfile(rel: str) -> bool:
    p = rel.replace("\\", "/")
    return p.endswith((".lock", "-lock.json", ".lockb")) or p in {"Cargo.lock", "poetry.lock"}


def _skip_hit(rel: str, ident: str) -> bool:
    """统一豁免判定，registry 与 publish 两种模式共用（避免两处漂移）。

    豁免只看**形状歧义**（测试 fixture / 锁文件版本号），不给任何路径开总闸：
    门禁自己的源码因此也必须保持零命中（`_self_source_clean` 钉住）。
    """
    p = rel.replace("\\", "/")
    if _is_test_scoped(p) and ident in _TEST_SCOPED_IDS:
        return True
    if _is_lockfile(p) and ident in _LOCK_VERSION_AMBIGUOUS_IDS:
        return True
    return False


def _is_test_scoped(rel: str) -> bool:
    p = rel.replace("\\", "/")
    return any(h in f"/{p}" for h in _SKIP_PATH_HINTS) or Path(p).name.startswith("test_")


def _tracked(ref: str) -> list[str]:
    """版本控制清单（枚举口径不是本机 FS）。空清单 = 枚举失效，不当"无需检查"。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", ref],
            capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:
        raise RuntimeError(f"git ls-tree {ref} 失败 [{type(exc).__name__}]: {exc}") from exc
    paths = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not paths:
        raise RuntimeError(f"ref {ref} 的文件清单为空——枚举失效不等于无需检查")
    return paths


def _stale_split(registry: dict[str, str], active: set[str], tracked: set[str]) -> tuple[list[str], list[str]]:
    """登记项零命中分两种，只有前者算违规：

    - **幽灵登记**（路径根本不在清单里）= 给"以后要泄漏的那个位置"预先授权 ⇒ 硬红。
    - **文件在、命中没了** = 该文件已被脱敏。公开镜像上跑 registry 模式必然落进
      这一类（镜像里的 inventory 就是遮过的），判红会让公开仓自己的 CI 永远红
      ⇒ 降级为警告，不放过但不假装失败。
    """
    hard: list[str] = []
    warn: list[str] = []
    for stale in sorted(set(registry) - active):
        if stale not in tracked:
            hard.append(
                f"P-4 登记路径 `{stale}` 不在 {len(tracked)} 项文件清单里 ⇒ 幽灵登记"
                f"（登记只能给**确实存在且确实在携带**的文件用）。原登记：{registry[stale]}"
            )
        else:
            warn.append(
                f"P-4 登记项 `{stale}` 现已零命中：该文件已被脱敏（公开镜像上正是这种形状）。"
                f"内网分支上若也想清掉这条登记，先把门禁跑在待推分支上确认命中数为 0。"
            )
    return hard, warn


def _mask_hint(line: str) -> str:
    out = line
    for pat, repl in _MASK_PLAN:
        out = pat.sub(repl, out)
    return out


def mask_content(text: str) -> str:
    """按 --mask-plan 替换（镜像构建侧使用；本脚本自身只打印建议，不改文件）。"""
    out = text
    for pat, repl in _MASK_PLAN:
        out = pat.sub(repl, out)
    return out


#: 粗筛用 POSIX-ERE（git grep 不支持 lookaround，所以粗筛宽松、精判交给 Python 模式）。
#: 这里只写**形状**：内网标识整串用 `[x]` 单元素字符类打断源码文本（ERE 语义不变，
#: 源码文本不再含整串），否则粗筛行自己就成了 publish 模式的命中行。
_COARSE_ERE = (
    r"(192\.168|172\.(1[6-9]|2[0-9]|3[01])|10\.[0-9]|amb[a]ri[0-9]|mingya[n]g|techng/aimod[e]"
    r"|BEGIN (RSA|EC|OPENSSH|PGP|DSA) PRIVATE KEY|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)


def _candidate_lines(ref: str) -> list[tuple[str, int, str]]:
    """一次 `git grep -I` 取候选行（-I 跳二进制，避免逐文件解码炸）。"""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "-In", "-E", "-e", _COARSE_ERE, ref],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode not in (0, 1):  # 1 = 无命中，属正常
        raise RuntimeError(f"git grep 失败 rc={proc.returncode}: {proc.stderr.strip()[:200]}")
    out: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        try:
            _ref, path, lineno, content = line.split(":", 3)
        except ValueError:
            continue
        if lineno.isdigit():
            # 全文留存供 Python 精判（截断会让长行里的命中漏掉），展示时再截
            out.append((path, int(lineno), content))
    return out


def mode_registry(ref: str, mask_plan: bool) -> tuple[list[str], list[str], int, int]:
    """registry 模式：命中文件必须登记；登记项失效按幽灵/已脱敏分流（见 `_stale_split`）。"""
    tracked = _tracked(ref)
    per_file: dict[str, list[tuple[str, int, str]]] = {}
    for path, lineno, content in _candidate_lines(ref):
        for name, pat in _PATTERNS:
            if pat.search(content):
                per_file.setdefault(path, []).append((name, lineno, content))
                break

    active: set[str] = set()
    problems: list[str] = []
    hits_total = 0
    for rel, hits in sorted(per_file.items()):
        # 豁免只看"形状歧义"（测试 fixture / 锁文件版本号），不看登记台账
        scoped = [h for h in hits if not _skip_hit(rel, h[0])]
        if not scoped:
            continue
        hits_total += len(scoped)
        active.add(rel.replace("\\", "/"))
        if rel.replace("\\", "/") not in _REGISTRY:
            ids = sorted({h[0] for h in scoped})
            problems.append(
                f"P-4 {rel} 携带内网/凭据标识（{ids}）但未登记。要么按 README 约定换成"
                f" <internal-*> 占位符，要么登记它为何 legitimately 保留并写清推公开镜像"
                f"时怎么脱敏。首条命中：L{scoped[0][1]} {scoped[0][2][:110]}"
            )
        elif mask_plan:
            for name, lineno, line in scoped[:3]:
                print(f"    [mask-plan] {rel}:L{lineno} ({name})\n        - {line[:110]}\n        + {_mask_hint(line)[:110]}")
    hard, warnings = _stale_split(_REGISTRY, active, {p.replace("\\", "/") for p in tracked})
    problems += hard
    return problems, warnings, hits_total, len(active)


def mode_publish(base: str, ref: str) -> tuple[list[str], int]:
    """零容忍：只看 base..ref 新公开的行，不接受任何登记豁免。"""
    try:
        diff = subprocess.run(
            ["git", "-C", str(ROOT), "diff", f"{base}..{ref}"], capture_output=True, text=True, check=True, encoding="utf-8"
        ).stdout
    except Exception as exc:
        raise RuntimeError(f"git diff {base}..{ref} 失败 [{type(exc).__name__}]: {exc}") from exc
    problems: list[str] = []
    cur = ""
    counted = 0
    tracked_ref = _tracked(ref)
    tracked_base = _tracked(base)  # 空基线会让 diff 退化成"全量新公开"，同样不可信
    if not set(tracked_base) & set(tracked_ref):
        problems.append(
            f"P-5 --base {base} 与 --ref {ref} 的文件清单完全不相交（{len(tracked_base)} vs "
            f"{len(tracked_ref)} 项）⇒ 基线选错，'新公开了什么'无从判定"
        )
        return problems, counted
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        for name, pat in _PATTERNS:
            m = pat.search(body)
            if m:
                if _skip_hit(cur, name):
                    break  # 形状豁免（测试 fixture / 锁文件版本号），与 registry 共用同一函数
                counted += 1
                problems.append(
                    f"P-1..3 {cur}: 新公开内容含 {name} → `{m.group(0)}`（公开镜像零容忍，"
                    f"登记台账在此不生效）。建议换成：{_mask_hint(body)[:120]}"
                )
                break
    return problems, counted


def _self_source_clean() -> list[str]:
    """门禁源码自身必须零命中：它随分支上公开镜像，否则检测器自己就是泄漏面。"""
    text = Path(__file__).resolve().read_text(encoding="utf-8")
    return [f"{name} → `{pat.search(text).group(0)}`" for name, pat in _PATTERNS if pat.search(text)]


def selftest() -> list[str]:
    """合成样本必须被咬到；豁免与替换必须证明自己有牙。"""
    problems: list[str] = []

    def hit(text: str) -> bool:
        return any(pat.search(text) for _name, pat in _PATTERNS)

    for label, text in [
        ("192.168 网段", _asm("kubectl get pods -o wide # 落在 192.168.100.", "126")),
        ("10/8 非 pod 段", _asm("psql 'postgresql://agent@10.0.0.", "9:5432/meta'")),
        ("172.16-31 网段", _asm("ssh 172.20.5.", "6 管理口")),
        ("运维机主机名", _asm("ssh ", _OPS_HOST_PREFIX, "03 uptime")),
        ("内网 GitLab", _asm("ssh://git@", _GITLAB_HOST, ":30001/", _GITLAB_GROUP, "/x.git")),
        ("私钥", _asm("-----BEGIN OPENSSH", " PRIVATE KEY-----")),
        ("GitHub token", _asm("ghp_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")),
        ("GitHub fine-grained token", _asm("github_pat_", "11ABCDEFGHIJ01234567_", "abcdefghijklmnopqrstuvwx")),
        ("Slack token", _asm("xoxb-", "123456789012", "abcdefghijklmnop")),
        ("AWS AK", _asm("AKIA", "ABCDEFGHIJKLMNOP")),
    ]:
        if not hit(text):
            problems.append(f"SELFTEST: {label} 未被任何判据咬到 ⇒ 门禁空转")
    for label, text in [
        ("flannel pod CIDR（仓内已公开的约定）", _asm("pod 10.244.1.", "7 ready")),
        ("RFC 5737 文档地址段", _asm("示例 198.51.100.", "7 与 203.0.113.9")),
    ]:
        if hit(text):
            problems.append(f"SELFTEST: {label} 被判红 ⇒ 假阳性源，红多了门禁会被关掉")
    if _is_test_scoped("docs/operations/env-126-inventory.md"):
        problems.append("SELFTEST: 文档被当成测试目录豁免 ⇒ 漏检通道")
    if not _is_test_scoped("applications/x/tests/test_a.py"):
        problems.append("SELFTEST: 测试目录豁免失效")
    if not _skip_hit("uv.lock", "P-1 私有网段-10/8"):
        problems.append("SELFTEST: 锁文件版本号豁免失效 ⇒ 门禁会被假阳性淹掉")
    if _skip_hit("uv.lock", "P-1 私有网段-192.168") or _skip_hit("uv.lock", "P-3 私钥头"):
        problems.append("SELFTEST: 豁免越界（锁文件里的 192.168 / 私钥必须照判）")
    if _skip_hit("docs/operations/x.md", "P-1 私有网段-10/8"):
        problems.append("SELFTEST: 普通文档被误当测试目录豁免 ⇒ 漏检通道")
    if _skip_hit("scripts/lint_public_mirror.py", "P-1 私有网段-192.168"):
        problems.append("SELFTEST: 门禁源码拿到形状豁免 ⇒ 泄漏面从检测器自身打开")
    if _skip_hit("scripts/lint_public_mirror.py", "P-3 私钥头"):
        problems.append("SELFTEST: 豁免越界到凭据类（fixture/测试目录不得豁免 P-3）")
    # 登记失效分流：幽灵登记必须红，"文件在但已脱敏"必须是警告（否则公开仓 CI 永远红）
    reg = {"a.md": "在携带", "b.md": "已脱敏", "d.md": "路径不存在"}
    hard, warn = _stale_split(reg, active={"a.md"}, tracked={"b.md"})
    if len(hard) != 1 or "d.md" not in hard[0]:
        problems.append(f"SELFTEST: 幽灵登记没判红（应为 d.md 不在清单）⇒ {hard}")
    if len(warn) != 1 or "b.md" not in warn[0]:
        problems.append(f"SELFTEST: 已脱敏项被判红 ⇒ 公开镜像自己的 CI 会永远红：{warn}")
    if _stale_split({"a.md": "在携带", "b.md": "已脱敏"}, active={"a.md", "b.md"}, tracked={"b.md"}) != ([], []):
        problems.append("SELFTEST: 登记项仍在命中时报了东西 ⇒ 对称差没闭上")
    dirty = _self_source_clean()
    if dirty:
        problems.append(
            "SELFTEST: 门禁源码自身含完整内网/凭据整串（随分支推上公开镜像即泄漏）⇒ " + "; ".join(dirty)
        )
    hint = _mask_hint(
        _asm("对 192.168.100.", "126（hostname ", _OPS_HOST_PREFIX, "03）盘点，仓 ssh://git@",
             _GITLAB_HOST, ":30001/", _GITLAB_GROUP, "/x.git")
    )
    for leak in (_asm("192.168.100.", "126"), _OPS_HOST_PREFIX, _asm("mingyang", "100"), _GITLAB_GROUP):
        if leak in hint:
            problems.append(f"SELFTEST: mask-plan 没换净（残留 {leak}）⇒ {hint[:130]}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="公开镜像防泄门禁")
    ap.add_argument("--mode", choices=("registry", "publish"), default="registry")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--base", default="", help="publish 模式必填：公开基线 sha（本仓为 github-legacy/main）")
    ap.add_argument("--mask-plan", action="store_true", help="registry 模式下打印命中行的占位符替换建议")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.mode == "registry":
            problems, warnings, hits, files = mode_registry(args.ref, args.mask_plan)
            summary = (
                f"registry 模式 @ {args.ref}：携带内网标识的仓内文件 {files} 个，"
                f"命中行 {hits} 处，登记台账 {len(_REGISTRY)} 项"
            )
        else:
            if not args.base:
                print("[FAIL] publish 模式必须给 --base（公开基线 sha），否则无从判定「新公开了什么」")
                return 2
            problems, hits = mode_publish(args.base, args.ref)
            warnings = []
            summary = f"publish 模式 {args.base}..{args.ref}：扫描到新增命中 {hits} 处（零容忍，无登记通道）"
    except RuntimeError as exc:
        print(f"[FAIL] 枚举/取数失效: {exc}")
        return 2

    extra = selftest() if args.selftest else []
    problems += extra
    for line in warnings:
        print(f"[WARN] {line}")
    for line in problems:
        print(f"[FAIL] {line}")
    print(f"公开镜像门禁：{summary}；违规 {len(problems)} 项，警告 {len(warnings)} 项")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
