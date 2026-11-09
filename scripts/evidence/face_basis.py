"""面基准（face basis）的唯一实现。

方案：`docs/plans/plan-error-contract-staged-split-2026-11-06.md` §3.4（本轮新根因）。

为什么需要一个"唯一实现"（2026-11-06 实测，不是推定）：门件那一轮 7 枚红里有 2 枚
（`MISS-DECL=2` 与 `BASIS-BLIND-TO-NEW-FILES=2`）**不是任何一刀的活坏了**，是三把量具
各自构造自己的"面"：门件用 `git diff --name-only HEAD`（32 行），现取派生件用
`git status --porcelain`（34 行），差的那两条恰好是两个**还没入库的新方案件** ⇒
同一件事被两格各报一次红，而每一格的判据单独看都自洽。

这在本仓不是第一次：`scripts/check_doc_sync.py` 在册那条「存在性判定基准 = 版本控制清单，
不是本机文件系统」（2026-10-04 实踩）是同型缺陷；本件是同型的第三条落点——
**基准散点式实现 = 迟早不同源**，所以按《架构决策原则》三层齐备收：

1. 单一实现：本文件（谓词都是纯函数，真读数与合成样件共用同一段代码）；
2. 全局装配：仓内/本机所有量具一律调本文件的 CLI，体内不许再自己拼 `git diff`/`git status`；
3. 强制门禁：门件的 `A-basis` 格拿两把尺子对拍，不同源即红；`tests/governance/test_face_basis_gate.py`
   钉住纯谓词（变异必须能咬，见该文件）。

基准定义（唯一一条）：`face = git diff --name-only HEAD` —— staged + unstaged 对 HEAD，
**新文件必须先 `git add -N`（intent-to-add）才在这条基准上可见**。没做那一步的量就是漏，
所以本件把 `??` 集合一并交出去，由消费方判 `NEW-NOT-INTENT-ADDED`，不各凭良心。

退出码沿用 `scripts/evidence/README.md`：`0` 达成 · `1` 未达成 · `2` 前置不可用（取不到 git）。
`2` 从不折算成通过。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 量具件的读法只准有一处：BOM 判定沿用同目录 `normalize_dump.sniff_encoding`（在册单一实现），
# 不在本文件复刻第二份——复刻就是散点式，而本轮 `ext-fresh` 第一次真跑就被 UTF-8 BOM 咬过一口
# （PS5.1 `Set-Content -Encoding utf8` 写带 BOM 的件，`read_text("utf-8")` 把首条路径读成
# `\ufeffapplications/...` ⇒ `git hash-object` 报不可读 ⇒ 一条**本来新鲜**的判决被说成 STALE）。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from normalize_dump import sniff_encoding  # noqa: E402

REPO_ROOT = _HERE.parents[1]

# git 对"没有内容"的索引项（intent-to-add）写的固定空 blob，全仓只此一处定义。
NULL_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SUMMARY_PAIR = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)=(\d+)")


def read_text(path: Path) -> str:
    """任何量具件的唯一读法：嗅探 BOM → 解码 → 剥 NUL。取不到就抛，不静默返回空串。"""
    raw = path.read_bytes()
    return raw.decode(sniff_encoding(raw), "replace").replace("\x00", "")


def norm(raw: str) -> str:
    """git 输出的路径列归一：去引号、反斜杠转正斜杠、去空白。"""
    return raw.strip().strip('"').replace("\\", "/")


def read_face(diff_out: str) -> list[str]:
    """`git diff --name-only HEAD` 的 stdout -> 有序去重路径集（纯函数）。"""
    return sorted({p for p in (norm(line) for line in diff_out.splitlines()) if p})


def read_porcelain(porc_out: str) -> tuple[list[str], list[str]]:
    """`git status --porcelain` -> (全部路径, 仅未跟踪路径)。

    porcelain 每行前两位是状态码、第 4 位起是路径；`?? ` 是未跟踪。重命名行
    （`R  old -> new`）只取右半边——本仓的门判据按"这份内容现在归谁"算，不按改名前算。
    """
    paths: set[str] = set()
    untracked: set[str] = set()
    for line in porc_out.splitlines():
        if len(line) < 4:
            continue
        code, tail = line[:2], norm(line[3:])
        if " -> " in tail:
            tail = norm(tail.split(" -> ")[-1])
        if not tail:
            continue
        paths.add(tail)
        if code == "??":
            untracked.add(tail)
    return sorted(paths), sorted(untracked)


def diff_sets(left: list[str], right: list[str]) -> dict[str, list[str]]:
    """两个集合的形状差：`only_left` / `only_right`。两向都算，缺向即空转。"""
    lset, rset = set(left), set(right)
    return {"only_left": sorted(lset - rset), "only_right": sorted(rset - lset)}


def off_face(face: list[str], untracked: list[str]) -> list[str]:
    """`NEW-NOT-INTENT-ADDED` 谓词：面上有 `??` 而基准面看不见 ⇒ 这一轮的量是漏的。

    返回非空时消费方**必须拒跑**，不许把它读成"这些文件不归我"。
    """
    return sorted({p for p in untracked if p not in set(face)})


def ext_fresh(registered: str, actual: str) -> bool:
    """判决新鲜度：登记的指纹必须是 40 位十六进制，且与实际 blob **逐字**相同。

    空串 / 非十六进制 / 两个相同的手抄垃圾串 全部判 False（fail-closed）。
    """
    if not _SHA40.match(registered or ""):
        return False
    if not _SHA40.match(actual or ""):
        return False
    return registered == actual


def read_derived(text: str, key: str) -> dict[str, object]:
    """解析量具落盘件里的**申报集**，并核对它自带的计数键（键绑内容，不绑件名）。

    认的形状（`k59-partition` 系量具的输出契约，改形状必须同步本函数与用例）::

        SUMMARY) head=<sha> candidate=<n> own=<n> held=<n> closure-violations=<n>
        OWN-FILE: <path>
        HELD-FILE: <path>

    纯路径清单（无 SUMMARY）走 `pure-list` 形状：`count` 取行数，`summary_count` 为 None，
    由调用方决定"没有计数键"算不算红（门件算）。
    """
    tag = f"{key}-FILE:"
    paths = [
        norm(line.split(":", 1)[1])
        for line in text.splitlines()
        if line.strip().startswith(tag) and norm(line.split(":", 1)[1])
    ]
    head = ""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("SUMMARY)"):
            head_m = re.search(r"head=([0-9a-f]+)", line)
            head = head_m.group(1) if head_m else ""
            counts = {k: int(v) for k, v in _SUMMARY_PAIR.findall(line)}
            break
    lower = key.lower()
    return {
        "key": key,
        "paths": paths,
        "count": len(paths),
        "summary_count": counts.get(lower),
        "counts": counts,
        "head": head,
        "shape": "summary-list" if counts else ("pure-list" if paths else "empty"),
    }


def bind_ok(derived: dict[str, object], current_head: str) -> tuple[bool, str]:
    """申报集与"它声称判决的那棵 HEAD"是否还同源。五种不合法形状各自点名。

    零值单独拦在册「零值拒判」那条：`own=0` 既可能是"这一轮真没活"，也可能是"面根本没读到"，
    两者在数字上不可区分 ⇒ 门件不许按空集放行（放行就等于旁路）。
    """
    if int(derived["count"]) == 0:
        return False, "NO-DECLARED-PATHS（件在而申报集为空：零值不许读成通过，也不许读成没活）"
    if derived["summary_count"] is None:
        return False, "NO-COUNT-KEY（件里没有 SUMMARY 计数键 ⇒ 数只绑件名不绑内容）"
    if int(derived["summary_count"]) != int(derived["count"]):
        return False, (
            f"COUNT-MISMATCH（计数键说 {derived['summary_count']} 而路径行有 {derived['count']} 条"
            "：件被改过，不是判决的原件）"
        )
    if not derived["head"]:
        return False, "NO-HEAD-BINDING（判决没绑它当时的 HEAD）"
    if derived["head"] != current_head:
        return False, f"HEAD-MOVED（判决 @{derived['head']} 现 HEAD @{current_head}）"
    return True, "BIND-OK"


# --- git 读数层（唯一允许起子进程的地方；纯谓词在上面那一段）-------------------


def _git(root: Path, *args: str) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:  # git 不可用 = 前置不可用，不降级成"空面通过"
        raise RuntimeError(f"git 不可调用：{exc}") from exc
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def read_state(root: Path) -> dict[str, object]:
    """一次读齐三把尺子，交给纯谓词对拍。取不到 git 直接抛（CLI 转 exit 2）。"""
    rc, out, err = _git(root, "rev-parse", "HEAD")
    if rc != 0:
        raise RuntimeError(f"rev-parse 失败 rc={rc} stderr={err.strip()[:200]}")
    head = out.strip()
    rc_f, face_out, _ = _git(root, "diff", "--name-only", "HEAD")
    rc_p, porc_out, _ = _git(root, "status", "--porcelain")
    rc_u, untracked_out, _ = _git(root, "ls-files", "--others", "--exclude-standard")
    if rc_f or rc_p or rc_u:
        raise RuntimeError(f"基准读数失败 face={rc_f} porcelain={rc_p} untracked={rc_u}")
    face = read_face(face_out)
    porc_paths, porc_untracked = read_porcelain(porc_out)
    ls_untracked = read_face(untracked_out)
    return {
        "head": head,
        "face": face,
        "porcelain_paths": porc_paths,
        "porcelain_untracked": porc_untracked,
        "ls_untracked": ls_untracked,
        "off_face": off_face(face, porc_untracked),
        "sets_diff": diff_sets(face, porc_paths),
    }


# --- 自测（合成样件跑在与真读数**完全相同**的谓词上）--------------------------


def selftest() -> tuple[bool, list[str]]:
    log: list[str] = []
    ok = True

    def cell(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        log.append(f"{name}={'OK' if passed else '<<< ' + detail}")

    # st-1 归一：反斜杠与引号必须被吃掉，否则两把尺子会因为书写不同而"看着不一样"。
    raw = ' "a' + chr(92) + 'b.md" '
    cell(
        "ST-1-norm",
        norm(raw) == "a/b.md",
        f"got={norm(raw)!r}",
    )
    # st-2 基准对拍：少一条必须咬，多一条也必须咬（单向比较就是空转）。
    d = diff_sets(["a.py", "b.py"], ["a.py", "c.py"])
    cell(
        "ST-2-diff-both-ways",
        d["only_left"] == ["b.py"] and d["only_right"] == ["c.py"],
        json.dumps(d, ensure_ascii=False),
    )
    cell(
        "ST-2b-diff-identical-no-bite",
        diff_sets(["a.py"], ["a.py"]) == {"only_left": [], "only_right": []},
        "identical sets must not bite",
    )
    # st-3 未跟踪漏量：?? 不在 face ⇒ 点名；已 intent-to-add ⇒ 不点名。
    cell(
        "ST-3-off-face-bites",
        off_face(["tracked.py"], ["new.md", "tracked.py"]) == ["new.md"],
        "一个已入基准一个新文件都没漏的量会被读成通过",
    )
    # st-4 porcelain 解析：重命名取右半、空行跳过、`?? ` 才进未跟踪。
    pp, uu = read_porcelain(" M a.py\n?? new.md\nR  old.py -> renamed.py\n\n")
    cell(
        "ST-4-porcelain-parse",
        pp == ["a.py", "new.md", "renamed.py"] and uu == ["new.md"],
        f"paths={pp} untracked={uu}",
    )
    # st-5 判决新鲜度：逐字相同才新鲜；四种坏形状全判不新鲜。
    good, bad1 = "a" * 40, "b" + "a" * 39
    cell(
        "ST-5-ext-fresh",
        ext_fresh(good, good)
        and not ext_fresh(bad1, good)
        and not ext_fresh("", good)
        and not ext_fresh(good, "")
        and not ext_fresh("not-a-hash", "not-a-hash"),
        "任一格失效都让减法在不可核对的判决上继续生效",
    )
    # st-6 键绑内容：计数键与路径行数不符（件被手改）必须咬。
    txt = (
        "SUMMARY) head=" + "c" * 40 + " own=2\n"
        "OWN-FILE: a.py\nOWN-FILE: b.py\nHELD-FILE: z.py\n"
    )
    dd = read_derived(txt, "OWN")
    cell(
        "ST-6a-derived-parse",
        dd["paths"] == ["a.py", "b.py"] and dd["count"] == 2 and dd["shape"] == "summary-list",
        json.dumps(dd, ensure_ascii=False),
    )
    b1, _ = bind_ok(dd, "c" * 40)
    b2, why2 = bind_ok(read_derived(txt, "HELD"), "c" * 40)
    b3, why3 = bind_ok(dd, "d" * 40)
    b4, why4 = bind_ok(read_derived("OWN-FILE: a.py\n", "OWN"), "c" * 40)
    b5, why5 = bind_ok(read_derived("SUMMARY) head=" + "c" * 40 + " own=0\nOWN-FILE: a.py\n", "OWN"), "c" * 40)
    cell(
        "ST-6b-bind-teeth",
        b1
        and not b2
        and why2.startswith("NO-COUNT-KEY")
        and not b3
        and why3.startswith("HEAD-MOVED")
        and not b4
        and why4.startswith("NO-COUNT-KEY")
        and not b5
        and why5.startswith("COUNT-MISMATCH"),
        f"good={b1} heldNoCount={b2}/{why2} moved={b3}/{why3} pure={b4}/{why4} drift={b5}/{why5}",
    )
    # st-7 空件不绿：件在而读不出任何申报 ⇒ 拒判（在册"零值拒判"同族）。
    cell(
        "ST-7-empty-artifact-refuses",
        read_derived("nothing here\n", "OWN")["shape"] == "empty"
        and not bind_ok(read_derived("nothing here\n", "OWN"), "c" * 40)[0],
        "空申报集被读成通过 = 门变成旁路",
    )
    # st-8 件读法：PS5.1 `Set-Content -Encoding utf8` 写的带 BOM 件与 UTF-16LE 重定向件都必须
    # 解成同一个集合——本轮就是这一型把一条**新鲜**的判决说成 STALE（BOM 粘在首条路径上，
    # 拿去 `git hash-object` 当然读不到）。不钉这一格，"唯一读法"就只是注释。
    with tempfile.TemporaryDirectory() as td:
        p8 = Path(td) / "syn.txt"
        payload = "applications/a.py\napplications/b.py\n"
        p8.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
        got8sig = read_text(p8)
        p8.write_bytes(payload.encode("utf-16"))  # utf-16 编码自带 LE BOM，与 PS5.1 `>` 同形
        got16 = read_text(p8)
        cell(
            "ST-8-read-text-bom-both-shapes",
            got8sig == got16 == payload,
            f"utf8sig={got8sig!r} utf16={got16!r}",
        )
    return ok, log


# --- CLI -----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="面基准唯一实现（见模块 docstring）")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--mode", required=True, choices=["face", "selftest", "derived", "ext-fresh"])
    ap.add_argument("--file", help="derived / ext-fresh 模式：路径清单件")
    ap.add_argument("--key", default="OWN", help="derived 模式：OWN / HELD")
    ap.add_argument("--expect-head", help="derived 模式：当前 HEAD（不符即 BIND 失败）")
    ap.add_argument("--hash-file", help="ext-fresh 模式：path<TAB>blob<TAB>... 指纹件")
    args = ap.parse_args(argv)

    if args.mode == "selftest":
        ok, log = selftest()
        print("FACE-BASIS-SELFTEST) " + " ".join(log))
        print("FACE-BASIS-SELFTEST-RC=" + ("0" if ok else "1"))
        return 0 if ok else 1

    root = Path(args.repo_root).resolve()
    try:
        state = read_state(root)
    except RuntimeError as exc:
        print(f"<<< FACE-BASIS-UNAVAILABLE {exc}", file=sys.stderr)
        return 2

    if args.mode == "face":
        print(
            f"FACE-BASIS) head={state['head']} face={len(state['face'])}"
            f" porcelain={len(state['porcelain_paths'])}"
            f" untracked-on-face={len(state['off_face'])}"
            f" only-in-face={len(state['sets_diff']['only_left'])}"
            f" only-in-porcelain={len(state['sets_diff']['only_right'])}"
        )
        # 路径逐行交出去（计数不算交付）：下游四把量具的候选集必须从**同一个**基准读出来，
        # 而不是各自再拼一遍 git —— 本轮七枚红里两枚的成因就是这个。
        for p in state["face"]:
            print(f"FACE-PATH: {p}")
        for p in state["off_face"]:
            print(f"NEW-NOT-INTENT-ADDED: {p}")
        for p in state["sets_diff"]["only_right"]:
            print(f"FACE-BASIS-SCATTER: {p}")
        return 0 if (not state["off_face"] and not state["sets_diff"]["only_right"]) else 1

    if args.mode == "derived":
        if not args.file:
            print("<<< FACE-BASIS-UNAVAILABLE derived 模式必须给 --file", file=sys.stderr)
            return 2
        path = Path(args.file)
        if not path.is_file():
            # 件不存在 ≠ 空集：这是"申报来源不可核对"，与"这一轮没有活"是两件事。
            print(f"<<< DECL-ARTIFACT-ABSENT {path}", file=sys.stderr)
            return 1
        derived = read_derived(read_text(path), args.key)
        good, why = bind_ok(derived, args.expect_head or str(state["head"]))
        print(
            f"DERIVED) key={args.key} count={derived['count']}"
            f" summary-count={derived['summary_count']} shape={derived['shape']}"
            f" verdict-head={derived['head'][:12]} current-head={str(state['head'])[:12]}"
            f" BIND={'OK' if good else '<<< ' + why}"
        )
        for p in derived["paths"]:  # type: ignore[index]
            print(f"{args.key}-FILE: {p}")
        return 0 if good else 1

    # ext-fresh：把「减 ext」这个动作的前提（判决还成立）交给同一个谓词判。
    if not args.file or not args.hash_file:
        print("<<< FACE-BASIS-UNAVAILABLE ext-fresh 模式必须给 --file 与 --hash-file", file=sys.stderr)
        return 2
    ext_path = Path(args.file)
    hash_path = Path(args.hash_file)
    if not ext_path.is_file() or not hash_path.is_file():
        print(f"<<< EXT-VERDICT-UNBOUND ext={ext_path.is_file()} hash={hash_path.is_file()}", file=sys.stderr)
        return 1
    blob_cache: dict[str, str] = {}
    ext_lines = [norm(x) for x in read_text(ext_path).splitlines() if norm(x)]
    rows = [ln for ln in read_text(hash_path).splitlines() if ln.strip()]
    bad: list[str] = []
    for f in ext_lines:
        hit = [r for r in rows if norm(r.split("\t")[0]) == f]
        if not hit:
            bad.append(f"EXT-NO-BINDING: {f}")
            continue
        reg = hit[0].split("\t")[1].strip()
        if f not in blob_cache:
            rc, out, _ = _git(root, "hash-object", "--", f)
            blob_cache[f] = out.strip() if rc == 0 else ""
        if not ext_fresh(reg, blob_cache[f]):
            bad.append(f"EXT-VERDICT-STALE: {f} registered={reg} now={blob_cache[f] or '(unreadable)'}")
    print(f"EXT-FRESH) declared={len(ext_lines)} unbound={len(bad)}")
    for line in bad:
        print("<<< " + line)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
