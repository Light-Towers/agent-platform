"""语义缓存的变异杀死率量测（逻辑层门禁，非功能层）。

为什么要有这个文件：AGENTS.md 把"逻辑测全不全"判给**变异杀死率**而不是覆盖率——
覆盖率只是下限。本模块此前每条反证都是会话里手敲一次（ADR-0013 §11 那 32 行的来源），
**反证不入库等于没做**：换个人/换个模型就没人能复跑，判据也就退化成一句叙述。

两个刻意的设计：
1. **每个变异先核前置再落刀**：`期望命中次数 == 实际命中次数` + `替换后文本必须变` +
   `py_compile` 过。三关任一不过就记"前置失败"而不是悄悄算成已杀——本仓 §11 第 16 行
   栽过"变异空转却记成判据无效"。
2. **杀死集合必须与声明一致**：`ENGINE_OWNED` 里那几个是**假客户端层杀不掉**的
   （fake 不解释查询串语义），它们的杀权在真机契约层。判据不是"越少越好"，而是"不许漂移"，
   漂移的两种解释要分开定性、都要留下实跑证据：
   ① 突然本地杀不掉了 ⇒ **用例退化**（必须先修用例或修产品，不许改声明）；
   ② 从"引擎独占"变成"本地也杀得掉" ⇒ 要么**用例获得了新能力**（如 2026-10-26 的 m11：
   替身开始记录"命令是否发出"，于是"SET 没发出去"这一层本地就能杀——**注意这只升级了被证的层次，
   "落盘后续读能命中"这个效果仍归真机**），要么**用例开始依赖假层不存在的解释规则**（那就是假绿，
   必须撤掉那条断言）。分辨方法：看红掉的到底是哪条用例、断言原文是不是这条性质。

跑法（本地，秒级 × 变异数）：`uv run python scripts/mutation_cache_branches.py`
引擎层那条链的复跑配方与实读数见 `docs/adr/0013-semantic-cache-single-track.md` §11 第 33–36 行。
"""

from __future__ import annotations

import pathlib
import py_compile
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = "packages/agent-runtime/agent_runtime/cache/valkey_backend.py"
CONFIG = "packages/agent-runtime/agent_runtime/cache/config.py"

# 假客户端层杀不掉、由真机契约层负责杀的变异（改动这个集合要连带改 §11 的行）
# 2026-10-26 集合从 {m05, m11} 收窄到 {m05}：m11（负缓存必须落盘）现被
# `test_invalidate_and_negative_write_act_when_epoch_exists` 杀掉——本地层证的是
# **"SET 命令确实发出"这一层**；"落盘之后续读能命中 null"这个**效果**仍只有真机能证
# （`test_cache_contract.py` 的负缓存用例）。定性过程与实跑读数见 §11 第 47 行。
ENGINE_OWNED = {"m05"}

SUITES = [
    "packages/agent-runtime/tests/test_valkey_backend_wire.py",
    "packages/agent-runtime/tests/test_cache_config.py",
    "tests/test_bench_cache_write_budget.py",
]

# (编号, 性质, 相对路径, 原文, 变异后, 原文在该文件里的期望次数)
MUTANTS: list[tuple[str, str, str, str, str, int]] = [
    ("m01", "空隔离值必须拒绝", BACKEND, '        if not value:\n            return "empty"', "        if False:\n            return 'empty'", 1),
    ("m02", "分隔符必须拒绝", BACKEND, '        if any(ch in value for ch in ("\\x00", _TAG_SEPARATOR)):\n            return "separator"', "        if False:\n            return 'separator'", 1),
    ("m03", "星号结尾必须拒绝（转义挡不住通配）", BACKEND, '        if value.endswith("*"):\n            return "wildcard"', "        if False:\n            return 'wildcard'", 1),
    ("m04", "跳过原因必须分账", BACKEND, '        return "skipped_unsafe_tag" if "wildcard" in reasons else "skipped_no_tenant"', '        return "skipped_no_tenant"', 1),
    ("m05", "KB 版本必须进 L2 过滤", BACKEND, 'f" @kb_version:{{{_escape_tag(kb_sig)}}}"', 'f" @kb_version:{{none}}"', 1),
    ("m06", "灰度桶必须进 L2 过滤", BACKEND, 'f" @gray_pct:{{{_escape_tag(gray_tag)}}}"', 'f" @gray_pct:{{0}}"', 1),
    ("m07", "epoch 必须进 L2 过滤", BACKEND, 'f" @epoch:{{{epoch}}})"', 'f" @epoch:{{*}})"', 1),
    ("m08", "超阈值必须判未命中", BACKEND, "        if distance > threshold:", "        if distance > threshold * 1000:", 1),
    ("m09", "L1 键必须含租户", BACKEND, "            kb_versions,\n            tenant_id,\n            gray_pct,", '            kb_versions,\n            "",\n            gray_pct,', 1),
    ("m10", "写侧 PII 门禁", BACKEND, "        if pii_types:", "        if False:", 1),
    ("m11", "负缓存必须落盘", BACKEND, 'lambda: self._client.set(keys["null"], "1", ex=self._cfg.null_ttl_seconds),', "lambda: None,", 1),
    ("m12", "熔断打开必须挡住写", BACKEND, "if not self._breaker.allow():", "if False:", 3),
    ("m13", "写队列满要计数并丢弃", BACKEND, 'self._runtime_counts["dropped_writes"] += 1', 'self._runtime_counts["dropped_writes"] += 0', 1),
    ("m14", "索引 TAG 必须 CASESENSITIVE", BACKEND, 'TagField("tenant", separator=_TAG_SEPARATOR, case_sensitive=True),', 'TagField("tenant", separator=_TAG_SEPARATOR, case_sensitive=False),', 1),
    ("m15", "索引名必须含 key_prefix", CONFIG, 'f"_k{safe_token(self.key_prefix)}_s{self.index_schema_version}"', 'f"_s{self.index_schema_version}"', 1),
    ("m16", "索引名必须含 schema 版本", CONFIG, 'f"_k{safe_token(self.key_prefix)}_s{self.index_schema_version}"', 'f"_k{safe_token(self.key_prefix)}"', 1),
    ("m17", "L2 必须只回传文本字段（向量不许回传）", BACKEND, '            .return_fields("value_json", "distance")\n', "", 1),
    # m18–m21 是战役 #5–#7 的产物（2026-10-26）：这四个节点此前只有**战役**能测到，
    # 而战役要 15 分钟、PR 门禁只有 20 秒——把它们提到门禁层，回归才能在合入前被抓到。
    # 定性依据见 §11 第 47–48 行；m18 只有并发用例杀得动（单协程里 `_index_ready` 不会在外层查过后变 True）。
    (
        "m18",
        "索引锁的第二个等待者必须复用结果（双检锁内层）",
        BACKEND,
        "        async with self._index_lock:\n            if self._index_ready:\n                return True",
        "        async with self._index_lock:\n            if False:\n                return True",
        1,
    ),
    (
        "m19",
        "dim 未知必须在调用 embedder **之前**止步",
        BACKEND,
        "        if self._dim <= 0:\n            return None\n        embedder = await self._ensure_embedder()",
        "        if self._dim < 0:\n            return None\n        embedder = await self._ensure_embedder()",
        1,
    ),
    (
        "m20",
        "embedder 冷却到期那一瞬归重试侧",
        BACKEND,
        "        if time.monotonic() < self._embedder_next_retry:",
        "        if time.monotonic() <= self._embedder_next_retry:",
        1,
    ),
    (
        "m21",
        "索引退避到期那一瞬归重试侧",
        BACKEND,
        "        if now < self._index_next_retry:",
        "        if now <= self._index_next_retry:",
        1,
    ),
]


def _run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *SUITES, "-q", "--no-header", "-p", "no:cacheprovider", "-x"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "(无输出)"
    return proc.returncode, last


def main() -> int:
    touched = {rel for _, _, rel, _, _, _ in MUTANTS}
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    killed: list[str] = []
    survived: list[str] = []
    broken: list[tuple[str, str]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="mut-staging-") as tmp:
            staging = pathlib.Path(tmp)
            for rel, blob in originals.items():
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
            for mid, prop, rel, old, new, expect in MUTANTS:
                base = (staging / rel).read_text(encoding="utf-8")
                if base.count(old) != expect:
                    broken.append((mid, f"前置失败：命中 {base.count(old)} 次，期望 {expect}"))
                    continue
                mutated = base.replace(old, new)
                if mutated == base:
                    broken.append((mid, "空转：替换后文本未变"))
                    continue
                target = ROOT / rel
                target.write_text(mutated, encoding="utf-8")
                try:
                    py_compile.compile(str(target), doraise=True)
                except py_compile.PyCompileError as exc:
                    broken.append((mid, f"变异产物语法错：{str(exc)[:80]}"))
                    shutil.copyfile(staging / rel, target)
                    continue
                rc, last = _run_suite()
                (killed if rc != 0 else survived).append(mid)
                print(f"{mid} | {prop} | {'KILLED' if rc != 0 else 'SURVIVED'} | {last}")
                shutil.copyfile(staging / rel, target)
    finally:
        for rel, blob in originals.items():
            (ROOT / rel).write_bytes(blob)

    mismatch = [rel for rel, blob in originals.items() if (ROOT / rel).read_bytes() != blob]
    if mismatch:
        print(f"恢复失败：{mismatch}（工作区已被改动，必须人工核对）")
        return 2

    print(f"\n合计 {len(MUTANTS)} 个变异：KILLED={len(killed)} SURVIVED={len(survived)} 前置/语法异常={len(broken)}")
    for mid, why in broken:
        print(f"  {mid}: {why}")
    local_survivors = set(survived)
    expected_engine_owned = ENGINE_OWNED
    if local_survivors != expected_engine_owned:
        print(
            f"存活集合与声明不一致：实得 {sorted(local_survivors)}，声明（引擎独占杀权）{sorted(expected_engine_owned)}\n"
            "⇒ 要么有用例退化了（本地该杀的杀不掉），要么有用例开始依赖假客户端不存在的解释能力。\n"
            "   两者都要先定性再改声明，不许把集合改成迁就当前结果。"
        )
        return 1
    if broken:
        print("存在前置失败的变异：锚点与代码已漂移，要么补刀要么删条目，不许留空转项。")
        return 1
    print(f"杀死集合与声明一致：本地层杀 {len(killed)} 个，{sorted(expected_engine_owned)} 个由真机契约层负责（§11 第 33-36 行有实读数）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
