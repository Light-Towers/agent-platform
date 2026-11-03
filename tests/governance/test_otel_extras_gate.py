"""L-4（OTel/langfuse extras 下界一致）的治理用例。

这条门禁此前**全仓零测试**——`check_otel_extras_alignment` 只在 `lint_architecture.py`
里被引用过，没有任何正反例。按 `docs/operations/evidence-format.md` §4 与 `tests/governance/`
既有范式，"没有反例的门禁无法区分确实合规与判据失效"，而这条门禁的判据失效已经实测到一次：
它的被检对象是手写表 `_OTEL_EXTRAS_SITES`（5 处），漏掉了
`applications/knowledge-service/pyproject.toml` 的 `[tracing]`（同样声明
`opentelemetry-api/sdk`）。漏掉的那一侧永远不会被要求合规 ⇒ 门禁绿着，而绿着不等于覆盖全。

因此本文件同时守两件事：① 下界比较本身有效（造离群值必须单独翻红）；
② 被检对象由派生补全，且手写下限不因派生而放松（删掉必检 extra 仍要报红）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    """与 tests/governance/ 既有范式一致：scripts/ 不是包，按文件路径加载。"""
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")

_KS_SITE = ("applications/knowledge-service/pyproject.toml", "tracing")


def _write_pyproject(root: Path, rel: str, extras: dict[str, list[str]]) -> None:
    """铺一个只含 optional-dependencies 的 pyproject（其余字段 L-4 不读）。"""
    body = ["[project]", 'name = "x"', "", "[project.optional-dependencies]"]
    for extra, reqs in extras.items():
        rendered = ", ".join(f'"{r}"' for r in reqs)
        body.append(f"{extra} = [{rendered}]")
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def _use_tree(tmp_path, monkeypatch, files: dict[str, dict[str, list[str]]]):
    """构造临时仓：ROOT 指向 tmp，并把 git 清单替换成这批文件（临时目录没有 git）。"""
    for rel, extras in files.items():
        _write_pyproject(tmp_path, rel, extras)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "_repo_file_listing", lambda: sorted(files))


# 完整基线树：手写表的 5 位 + KS 那位表外位，下界全部一致。
# 为什么必须铺满：本文件第一版只铺"要测的那两处"，结果其余必检位在临时仓里不存在，
# 得到的是"无法解析"而不是"extras 缺失"，两个分支都测不到却看起来像在测。
_BASELINE: dict[str, dict[str, list[str]]] = {
    "pyproject.toml": {"otel": ["opentelemetry-api>=1.45.1", "opentelemetry-sdk>=1.45.1"]},
    "packages/agent-core/pyproject.toml": {"tracing": ["opentelemetry-api>=1.45.1"]},
    "packages/agent-runtime/pyproject.toml": {
        "langfuse": ["langfuse>=5.0.4", "langchain>=1.4.6,<2"]
    },
    "applications/agent_federation/pyproject.toml": {
        "observability": ["langfuse>=5.0.4", "langchain>=1.4.6,<2"]
    },
    "applications/exhibition-agent/pyproject.toml": {
        "langfuse": ["langfuse>=5.0.4", "langchain>=1.4.6,<2"]
    },
    "applications/knowledge-service/pyproject.toml": {"tracing": ["opentelemetry-api>=1.45.1"]},
}


def _tree(tmp_path, monkeypatch, mutate=None):
    files = {rel: {k: list(v) for k, v in extras.items()} for rel, extras in _BASELINE.items()}
    if mutate is not None:
        mutate(files)
    _use_tree(tmp_path, monkeypatch, files)


def test_otel_gate_passes_on_current_repo():
    """正向控制：现网仓必须真被这条门禁判定过且为绿（不是"扫不到对象所以绿"）。"""
    assert lint.check_otel_extras_alignment() == []
    assert len(lint._otel_extras_candidate_sites()) >= len(lint._OTEL_EXTRAS_SITES)


def test_derived_sites_include_the_extra_the_hand_table_missed():
    """自检：任何声明了被跟踪观测依赖的 extras 位都必须在被检集合里。

    同时钉"KS 那处不在手写表里"——否则有人把它补进 `_OTEL_EXTRAS_SITES` 后，
    本用例会退化成"手写表 ⊆ 派生"的空转（手写清单漏项这件事就再也没人查了）。
    """
    derived = set(lint._otel_extras_candidate_sites())
    assert _KS_SITE not in set(lint._OTEL_EXTRAS_SITES), f"{_KS_SITE} 已进手写表，本用例失去意义"
    assert _KS_SITE in derived, "派生漏掉 knowledge-service[tracing]：它会带着离群下界静默入库"
    for site in lint._OTEL_EXTRAS_SITES:
        assert site in derived, f"手写表里的 {site} 在派生里找不到（声明被删？表该同步）"


def test_langchain_core_is_not_mistaken_for_langchain(tmp_path, monkeypatch):
    """派生按包名匹配，不能把 `langchain-core` 当成 `langchain`。

    这条不是想象中的风险：我第一版自查脚本就用子串匹配，把 nl2sql-service 的
    `langchain-core>=0.3` 误报成"漏检的观测声明位"。若门禁这么写，它会因为
    无关包恒红 ⇒ 早晚被人关掉。
    """
    _use_tree(
        tmp_path,
        monkeypatch,
        {
            "applications/nl2sql-service/pyproject.toml": {
                "dev": ["langchain-core>=0.3", "langchain-openai>=0.3"]
            }
        },
    )
    assert lint._otel_extras_candidate_sites() == []


def test_outlier_floor_on_a_derived_site_is_flagged(tmp_path, monkeypatch):
    """派生位不是"列出来看看"：手写表之外那处（KS 形状）改了下界必须单独翻红。

    这正是本条门禁原先的失效形状——KS 声明了 `opentelemetry-api` 却不在被检集合里，
    它改成任何下界都不会有人报警。
    """
    _tree(
        tmp_path,
        monkeypatch,
        lambda f: f["applications/knowledge-service/pyproject.toml"].__setitem__(
            "tracing", ["opentelemetry-api>=1.30.0"]
        ),
    )
    violations = lint.check_otel_extras_alignment()
    assert len(violations) == 1, violations
    assert "opentelemetry-api" in violations[0]
    assert "knowledge-service" in violations[0]
    assert "1.30.0" in violations[0] and "1.45.1" in violations[0]


def test_baseline_tree_is_clean(tmp_path, monkeypatch):
    """正向控制：同一棵完整树在"表外位也进判定"之后仍为绿，
    证明上一条的红来自离群值本身，而不是我把树铺坏了。"""
    _tree(tmp_path, monkeypatch)
    assert lint.check_otel_extras_alignment() == []


def test_required_extra_still_required_after_derivation(tmp_path, monkeypatch):
    """派生只会让集合变大，不得放松下限：摘掉某个必检位的 extra 仍要报"extras 缺失"。

    反过来说明为什么不能"纯派生"——extra 整段删除后它就再从派生结果里消失，门禁反而变绿，
    而那正是 L-4 明确要拦的形状（软依赖声明被摘 ⇒ 装不上时静默降级成"配了但不报"）。
    这里只动 federation 一位：必须**恰好**红这一条，其余 5 位不受影响。
    """
    _tree(
        tmp_path,
        monkeypatch,
        lambda f: f["applications/agent_federation/pyproject.toml"].pop("observability"),
    )
    violations = lint.check_otel_extras_alignment()
    assert len(violations) == 1, violations
    assert "extras 缺失" in violations[0]
    assert "applications/agent_federation/pyproject.toml[observability]" in violations[0]
