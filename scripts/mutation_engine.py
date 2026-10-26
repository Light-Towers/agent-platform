"""变异测试引擎（逻辑层仪表）：按 AST 算子批量下刀，量"杀死率"而不是量覆盖率。

为什么要有它：AGENTS.md 把逻辑测的判据写成"变异杀死率，覆盖率只是下限"，但仓里此前只有
一份**手工挑的性质**清单（`scripts/mutation_cache_branches.py`）。手工清单的分母由我的判断
决定——"挑了哪些"本身就是未验的前提。本引擎把刀口从判定节点自动展开，**分母来自代码**。

算子集（只做"看起来像真 bug"的最小语义改动）：
  cmp:*→*       比较算子改写（`>`→`>=` 这类边界归属，以及取反）
  bool:*        `and` ↔ `or`
  not_strip     删掉一个 `not`
  cond:True/False  布尔常量取反（门禁整段失效的形状）
  num:±1        整型常量 ±1（阈值/上限/重试次数差一格）

三道防自欺工序：
  1. **往返对照**：先把"只 unparse、不变异"的全套文件跑一遍套件；不绿就整体中止——
     否则"红"可能是仪表造的，不是缺陷。
  2. **编译前置**：每个变异产物先 `compile()`，编不过记 invalid，不当"杀死"。
  3. **字节还原**：结束按 sha256 核对原文件，不一致返回码 2 并打印清单（异常路径也还原）。

用法：
    uv run python scripts/mutation_engine.py \
        --target packages/agent-runtime/agent_runtime/cache \
        --command "{python} -m pytest packages/agent-runtime/tests/test_valkey_backend_wire.py \\
                   packages/agent-runtime/tests/test_cache_config.py tests/test_bench_cache_write_budget.py \\
                   -q -x --no-header -p no:cacheprovider"

存活体（survived）不是失败，是**待定性清单**：等价变异 / 引擎独占（假客户端解释不了的语义）/
真缺口。三类都要人分，不许把"套件仍绿"当成"没问题"。
"""

from __future__ import annotations

import argparse
import ast
import atexit
import hashlib
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]

CMP_MAP = {
    ast.Gt: (ast.GtE, ast.LtE),
    ast.GtE: (ast.Gt, ast.Lt),
    ast.Lt: (ast.LtE, ast.GtE),
    ast.LtE: (ast.Lt, ast.Gt),
    ast.Eq: (ast.NotEq,),
    ast.NotEq: (ast.Eq,),
    ast.Is: (ast.IsNot,),
    ast.IsNot: (ast.Is,),
    ast.In: (ast.NotIn,),
    ast.NotIn: (ast.In,),
}


@dataclass
class Site:
    node_index: int
    operator: str
    before: str
    after: str
    make_replacement: object


@dataclass
class Mutant:
    digest: str
    path: str
    lineno: int
    operator: str
    before: str
    after: str
    src: str


def _collect_sites(tree: ast.AST) -> list[Site]:
    sites: list[Site] = []
    for i, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare) and node.ops:
            op = node.ops[0]
            for target in CMP_MAP.get(type(op), ()):
                sites.append(
                    Site(
                        node_index=i,
                        operator=f"cmp:{type(op).__name__}→{target.__name__}",
                        before=type(op).__name__,
                        after=type(target).__name__,
                        make_replacement=_make_compare(target, node),
                    )
                )
        elif isinstance(node, ast.BoolOp):
            flipped = ast.Or if isinstance(node.op, ast.And) else ast.And
            sites.append(
                Site(
                    node_index=i,
                    operator=f"bool:{type(node.op).__name__}→{flipped.__name__}",
                    before=type(node.op).__name__,
                    after=flipped.__name__,
                    make_replacement=_make_boolop(flipped, node),
                )
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append(
                Site(
                    node_index=i,
                    operator="not_strip",
                    before="not X",
                    after="X",
                    make_replacement=_make_identity(node.operand),
                )
            )
        elif isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                sites.append(
                    Site(
                        node_index=i,
                        operator=f"cond:{value}→{not value}",
                        before=str(value),
                        after=str(not value),
                        make_replacement=_make_constant(not value),
                    )
                )
            elif isinstance(value, int):
                for delta in (1, -1):
                    sites.append(
                        Site(
                            node_index=i,
                            operator=f"num:{value}→{value + delta}",
                            before=str(value),
                            after=str(value + delta),
                            make_replacement=_make_constant(value + delta),
                        )
                    )
    return sites


def _make_compare(target: type, node: ast.Compare):
    def build(repl_parent: ast.AST, target_node: ast.expr) -> ast.expr:
        # ast 的 cmpop 字段要的是**实例**（`ast.GtE()`），传类会让 unparse 抛 KeyError: 'type'
        ops = [target()] + [type(op)() for op in target_node.ops[1:]]
        return ast.Compare(left=target_node.left, ops=ops, comparators=list(target_node.comparators))

    return build


def _make_boolop(flipped: type, node: ast.BoolOp):
    def build(repl_parent: ast.AST, target_node: ast.expr) -> ast.expr:
        return ast.BoolOp(op=flipped(), values=list(target_node.values))

    return build


def _make_identity(inner: ast.expr):
    def build(repl_parent: ast.AST, target_node: ast.expr) -> ast.expr:
        return inner

    return build


def _make_constant(value: object):
    def build(repl_parent: ast.AST, target_node: ast.expr) -> ast.expr:
        return ast.Constant(value=value)

    return build


def _apply(tree: ast.AST, node_index: int, build) -> ast.AST | None:
    """在**重新 parse 的树**上定位第 node_index 个节点，替换成 build 造出来的新节点。"""
    nodes = list(ast.walk(tree))
    if node_index >= len(nodes):
        return None
    target = nodes[node_index]
    parent_map = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    parent = parent_map.get(target)
    if parent is None:
        return None
    replacement = build(parent, target)
    ast.copy_location(replacement, target)
    for field, value in ast.iter_fields(parent):
        if value is target:
            setattr(parent, field, replacement)
            return tree
        if isinstance(value, list):
            for i, item in enumerate(value):
                if item is target:
                    value[i] = replacement
                    return tree
    return None


def _mutants_for(rel: str, src: str) -> tuple[list[Mutant], int]:
    baseline = ast.unparse(ast.parse(src))
    sites = _collect_sites(ast.parse(src))
    mutants: list[Mutant] = []
    seen: set[str] = set()
    invalid = 0
    for site in sites:
        tree = ast.parse(src)
        nodes = list(ast.walk(tree))
        if site.node_index >= len(nodes):
            invalid += 1
            continue
        if id(nodes[site.node_index]) in {id(n) for n in _docstring_nodes(tree)}:
            continue
        mutated = _apply(tree, site.node_index, site.make_replacement)
        if mutated is None:
            invalid += 1
            continue
        try:
            new_src = ast.unparse(mutated)
        except (RecursionError, ValueError):
            invalid += 1
            continue
        if new_src == baseline or new_src == src:
            invalid += 1
            continue
        try:
            compile(new_src, rel, "exec")
        except SyntaxError:
            invalid += 1
            continue
        digest = hashlib.sha256(new_src.encode("utf-8")).hexdigest()[:16]
        if digest in seen:
            continue
        seen.add(digest)
        target_node = nodes[site.node_index]
        mutants.append(
            Mutant(
                digest=digest,
                path=rel,
                lineno=getattr(target_node, "lineno", 0),
                operator=site.operator,
                before=site.before,
                after=site.after,
                src=new_src,
            )
        )
    return mutants, invalid


def _docstring_nodes(tree: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    out.append(body[0].value)
    return out


def _split(command: str) -> list[str]:
    """把 `--command` 拆成 argv（不走 shell）。

    Windows 侧必须 `posix=False`：posix 模式会把 `D:\\Study\\...` 里的反斜杠当转义吃掉。
    代价是 token 带引号，逐个剥掉即可。不走 shell 的直接收益是超时能杀到真正的子进程——
    `shell=True` 时 kill 只落在 cmd.exe 上，pytest 会变成孤儿继续占着就地改写的源文件。
    """
    if os.name == "nt":
        return [token.strip('"') for token in shlex.split(command, posix=False)]
    return shlex.split(command)


def _run(
    command: str, cwd: pathlib.Path | None = None, timeout: float = 0.0
) -> tuple[bool, str, bool]:
    """跑一遍套件。返回 (是否变红, 末行读数, 是否超时)。

    超时按"被杀死"计，但必须标记来源：一刀把套件跑挂不等于一刀暴露了缺陷，
    分诊时它是"待定性"，不能和断言失败混在同一个数里。
    """
    try:
        proc = subprocess.run(
            _split(command.replace("{python}", sys.executable)),
            cwd=cwd or ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout or None,
        )
    except subprocess.TimeoutExpired:
        return True, "TIMEOUT（套件挂死，按被杀计但不等于暴露缺陷）", True
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode != 0, (tail[-1] if tail else "(无输出)"), False


def _snapshot(originals: dict[pathlib.Path, bytes], rel_target: str) -> pathlib.Path:
    """开跑前把原始字节另存一份，并把 sha256 打出来。

    为什么非要一份仓外的拷贝：引擎是**就地改写**源文件的，而变异体是 `ast.unparse` 出来的
    ——注释全无、行数变短。进程被 SIGKILL（或机器重启）时 `finally` 不会执行，工作区就停在那个
    无注释版本上；本仓是共享工作区，并行会话会把这种半成品直接提交走（AGENTS.md「共享工作区」）。
    """
    snap = ROOT / ".tmp-scratch" / "mutation-snap" / rel_target.replace("/", "_")
    snap.mkdir(parents=True, exist_ok=True)
    print("开跑前的原始字节快照（进程被硬杀时用它恢复）：")
    for p, blob in originals.items():
        out = snap / p.name
        out.write_bytes(blob)
        print(f"  {out}  {hashlib.sha256(blob).hexdigest()[:16]}")
    return snap


def _install_restore_hook(originals: dict[pathlib.Path, bytes]) -> None:
    """任何退出路径（正常/异常/Ctrl-C/信号）都按字节恢复——恢复不是收尾工作，是前提。"""

    def _restore() -> None:
        for p, blob in originals.items():
            if p.read_bytes() != blob:
                p.write_bytes(blob)

    def _handler(signum: int, _frame: object) -> None:
        _restore()
        print(f"收到信号 {signum}：已按字节恢复 {len(originals)} 个源文件")
        raise SystemExit(130)

    atexit.register(_restore)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handler)
            except (OSError, ValueError):
                pass  # 非主线程装不了 handler；此时 atexit 仍是兜底


_PROBE_PY = "def is_ready(value):\n    return value > 3\n"
_PROBE_TEST = '''
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from probe import is_ready


def test_probe_boundary():
    assert is_ready(4) is True
    assert is_ready(3) is False
    assert is_ready(2) is False
'''


def _self_test() -> tuple[bool, str]:
    """仪表自己必须先证明"能杀"，否则后面所有 KILLED 读数都没有意义。

    形状：造一个只有 4 个判定结果的小模块（`value > 3`）+ 一条**恰好覆盖这些边界**的用例，
    让引擎对它下刀。这一组的四个变异（`>`→`>=`、`>`→`<=`、`3`→`4`、`3`→`2`）都必须被杀——
    少杀一个就说明算子展开、写盘或套件调用哪一环是空的（本仓 §11 第 16 行栽过"变异空转却记成已杀"）。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mut-selftest-") as tmp:
        d = pathlib.Path(tmp)
        (d / "probe.py").write_text(_PROBE_PY, encoding="utf-8")
        (d / "test_probe.py").write_text(_PROBE_TEST, encoding="utf-8")
        mutants, invalid = _mutants_for("probe.py", _PROBE_PY)
        if len(mutants) < 4:
            return False, f"探针只展开 {len(mutants)} 个变异（期望 ≥4，invalid={invalid}）"
        # 探针自带一条用例，**不**复用 --command：把项目套件卷进来会让"红"失去含义
        probe_cmd = f'{sys.executable} -m pytest {d / "test_probe.py"} -q -x --no-header -p no:cacheprovider'
        killed = 0
        for m in mutants:
            (d / "probe.py").write_text(m.src, encoding="utf-8")
            dirty, note, _ = _run(probe_cmd, cwd=d, timeout=120)
            if dirty:
                killed += 1
            (d / "probe.py").write_text(_PROBE_PY, encoding="utf-8")
        if killed != len(mutants):
            return False, f"探针 {killed}/{len(mutants)} 被杀——仪表有环节是空的，杀死率读数不可信"
        return True, f"探针 {killed}/{len(mutants)} 全杀（算子展开、写盘、套件调用都有效）"



def set_check_allowed(only: str, limit_per_file: int) -> bool:
    """本轮能不能拿"存活集合"跟声明比。

    带 `--only`/`--limit-per-file` 的复跑只覆盖了分母的一部分，比集合会把"没测"读成"没漂移"。
    """
    return not (only or limit_per_file)


def diff_survivors(results: list[dict], declared: list[dict]) -> dict[str, object]:
    """把"存活集合是否与上一轮一致"变成机器判据，而不是只写在 §11 的散文里。

    两个方向都要人定性，所以两个方向都报红：
      - `regressed`（以前杀得动 → 现在杀不动）＝ 用例退化或被让出，**这是要查的那种**；
      - `improved`（以前存活 → 现在被杀）＝ 用例获得了新能力，通常是好事，
        但它同样意味着"判据变了"，得确认不是假绿（新用例是不是开始依赖替身不存在的解释规则）。
    分母也要核：位置数变了（改过被检文件）就不许直接比集合——那会把"新增位置"读成"漂移"。
    """
    m_sv = {r["digest"] for r in results if r["verdict"] == "survived"}
    d_sv = {r["digest"] for r in declared if r["verdict"] == "survived"}
    by_digest = {r["digest"]: r for r in results}
    return {
        "regressed": sorted(m_sv - d_sv),
        "improved": sorted(d_sv - m_sv),
        "carried": len(m_sv & d_sv),
        "denominator": (len(results), len(declared)),
        "regressed_where": [
            f"{by_digest[d]['file'].split(chr(92))[-1]}:{by_digest[d]['line']} {by_digest[d]['operator']}"
            for d in sorted(m_sv - d_sv)
            if d in by_digest
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="AST 变异引擎（量杀死率）")
    ap.add_argument("--target", required=True, help="要变异的目录（递归收 .py）")
    ap.add_argument("--command", required=True, help="套件命令；非零 = 该变异被杀死")
    ap.add_argument("--report", default=".tmp-scratch/mutation-report.json")
    ap.add_argument("--limit-per-file", type=int, default=0, help="每文件最多下多少刀（0=不限）")
    ap.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="单刀套件超时秒数（0=不限）。挂死按被杀计并单独计数，绝不卡住整轮",
    )
    ap.add_argument(
        "--only",
        default="",
        help="只变异路径里含该子串的文件（补完一处用例后复跑单个文件，不必重跑整轮）",
    )
    ap.add_argument(
        "--declare",
        default="",
        help="上一轮的报告 JSON：把它的存活集合当声明，本轮漂移即 rc=3（两个方向都要人定性）",
    )
    args = ap.parse_args()

    target_dir = ROOT / args.target
    files = sorted(p for p in target_dir.rglob("*.py") if "__pycache__" not in p.parts)
    if args.only:
        files = [p for p in files if args.only in str(p.relative_to(ROOT))]
        if not files:
            print(f"--only {args.only!r} 在 {target_dir} 下没匹配到文件（清单见上一行的候选）")
            return 2
    if not files:
        print(f"目标目录里没有 .py：{target_dir}")
        return 2

    originals = {p: p.read_bytes() for p in files}
    _install_restore_hook(originals)
    _snapshot(originals, args.target + ("__" + args.only if args.only else ""))
    print(f"本轮被检文件 {len(files)} 个：{[str(p.relative_to(ROOT)) for p in files]}")
    mismatch: list[str] = []
    results: list[dict] = []
    ok, note = _self_test()
    if not ok:
        print(f"自检失败：{note}")
        return 2
    print(f"自检通过：{note}")
    try:
        dirty, last, _ = _run(args.command, timeout=args.timeout)
        if dirty:
            print(f"基线不绿（{last}）——变异读数全是噪声，先修套件")
            return 2
        print(f"基线绿：{last}")

        for p in files:
            p.write_text(ast.unparse(ast.parse(originals[p].decode("utf-8"))), encoding="utf-8")
        dirty, last, _ = _run(args.command, timeout=args.timeout)
        for p, blob in originals.items():
            p.write_bytes(blob)
        if dirty:
            print(f"往返对照失败（unparse 后变红：{last}）——仪表不可信，中止")
            return 2
        print(f"往返对照通过（unparse 不改语义）：{last}")

        for p in files:
            rel = str(p.relative_to(ROOT))
            mutants, invalid = _mutants_for(rel, originals[p].decode("utf-8"))
            if args.limit_per_file:
                mutants = mutants[: args.limit_per_file]
            print(f"—— {rel}: {len(mutants)} 刀（无效/等价跳过 {invalid}）")
            for m in mutants:
                p.write_text(m.src, encoding="utf-8")
                killed, note, timed_out = _run(args.command, timeout=args.timeout)
                results.append(
                    {
                        "digest": m.digest,
                        "file": m.path,
                        "line": m.lineno,
                        "operator": m.operator,
                        "before": m.before,
                        "after": m.after,
                        "verdict": "killed" if killed else "survived",
                        "timed_out": timed_out,
                        "note": note,
                    }
                )
                flag = "KILLED  " if killed else "SURVIVED"
                print(f"  {m.operator:<26} L{m.lineno:<5} {flag}{'  (timeout)' if timed_out else ''}")
                p.write_bytes(originals[p])
    finally:
        mismatch = [str(p.relative_to(ROOT)) for p, blob in originals.items() if p.read_bytes() != blob]
        for p, blob in originals.items():
            p.write_bytes(blob)

    if mismatch:
        print(f"恢复失败（工作区被改过，必须人工核对）：{mismatch}")
        return 2

    total = len(results)
    if not total:
        print("没有可变异的位置")
        return 0
    killed = sum(1 for r in results if r["verdict"] == "killed")
    survived = [r for r in results if r["verdict"] == "survived"]
    hung = sum(1 for r in results if r.get("timed_out"))
    rep = ROOT / args.report
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n合计 {total} 刀：KILLED={killed} SURVIVED={len(survived)} 杀死率={killed / total:.1%}")
    if hung:
        print(f"其中 {hung} 刀是**挂死超时**记成被杀的——这只证明套件没跑完，不证明用例有牙；分诊时要单独定性")
    print(f"报告：{args.report}")
    if survived:
        print("存活体（三类都要人分：等价 / 引擎独占 / 真缺口）：")
        for r in survived:
            print(f"  {r['file']}:{r['line']:<5} {r['operator']}")
    if args.declare:
        partial = not set_check_allowed(args.only, args.limit_per_file)
        if partial:
            print("!! --declare 需整轮复跑才判集合（本轮带 --only/--limit-per-file ⇒ 不做判定，别把'没报红'读成'没漂移'）")
        else:
            declared_rows = json.loads((ROOT / args.declare).read_text(encoding="utf-8"))
            drift = diff_survivors(results, declared_rows)
            before, after = drift["denominator"]
            print(
                f"\n集合判定：位置数 {before}→{after}，沿用 {drift['carried']} 刀，"
                f"新增存活 {len(drift['regressed'])}，新杀 {len(drift['improved'])}"
            )
            if before != after:
                print("!! 分母变了（被检文件动过）⇒ 不许直接比存活集合，先对齐位置集再判")
                return 3
            if drift["regressed"] or drift["improved"]:
                for row in drift["regressed_where"]:
                    print(f"  [退化] {row}")
                print(f"  [新增被杀] {len(drift['improved'])} 刀：用例获得新能力，要确认不是依赖替身的解释力")
                return 3
            print("存活集合与声明一致（未漂移）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
