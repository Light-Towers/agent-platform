"""语义缓存配置面 ↔ 根 `.env.example` 的对码门禁（ADR-0013 Stage 5）。

钉三件事，形状照 `applications/nl2sql-service/tests/test_env_template.py` 与
`tests/governance/test_agent_server_env_template.py`，但**被检对象从代码 AST 派生**，
不手写清单——本仓复发过多次"门禁用手写列表数被检对象，列表本身就是盲区"
（见 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §31）。

1. **正向齐全**：`cache/config.py` 里每个被读的 env 名都必须是缓存段的 active 键，
   且值 == 代码默认。反例形状：代码加了旋钮、模板没写 ⇒ 照模板部署的人根本不知道该键存在。
2. **反向无死键**：缓存段里每个 active 键都必须真的被**这个模块**读取。派生口径只取
   `cache/config.py` 的 AST，因此不会把别处的同名键算进来——这一条的必要性是实测的：
   仓里有**两套**熔断旋钮（平台侧 `BREAKER_*` 由 agent_server 的 pydantic Settings 字段名派生，
   缓存侧 `CACHE_BREAKER_*` 由本模块直读），按字面 grep 判"有没有读取方"会把前者读成死键
   （2026-10-27 本人实踩，被既有的 agent_server 模板门禁当场判红纠正）。
3. **派生口径自检**：派生集必须同时含直调形（`env_int(...)`）与包装形（`_env_timeout_ms(...)`）
   两类键名，且缓存段非空——否则"清单空了"会读成"全都对得上"。
4. **两套同名旋钮各归各处**：`BREAKER_*` 在缓存段之外且不由本模块读取，`CACHE_BREAKER_*` 在段内
   且由本模块读取；混用会让运维改了平台侧阈值却以为在调缓存。

**不做全仓反向门禁**：那要扫全仓 `os.getenv` 与各家 `env_prefix` 折算，范围与形态属待拍板项
（`plan-unfinished-completion-schedule` §3 第 12 项）。本文件只把**缓存这一个配置面**闭环。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ENV = _ROOT / ".env.example"
_CONFIG = _ROOT / "packages" / "agent-runtime" / "agent_runtime" / "cache" / "config.py"
_MARKER = "# ===== 语义缓存模板补齐（2026-10-27，ADR-0013 Stage 5）====="
_ENV_FUNCS = {"env_bool", "env_int", "env_float", "env_str", "_env_timeout_ms"}


def _read_defaults() -> dict[str, object]:
    """从代码派生 {env 名: 默认值}：这是唯一真相源，不在测试里重述一遍。"""
    tree = ast.parse(_CONFIG.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id not in _ENV_FUNCS or len(call.args) < 2:
            continue
        name, default = call.args[0], call.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            if isinstance(default, ast.Constant):
                out[name.value] = default.value
    assert out, "cache/config.py 没派生出任何 env 键 —— 门禁自己空转了"
    return out


def _cache_section() -> str:
    text = _ENV.read_text(encoding="utf-8-sig")
    _, sep, tail = text.partition(_MARKER)
    if not sep:
        pytest.fail(f"根 .env.example 缺少缓存补齐段标记：{_MARKER}")
    # 段止于下一个顶层分组标题（`# --- ... ---`），否则会把无关分组的键算进来
    lines = []
    for line in tail.splitlines():
        if line.startswith("# --- "):
            break
        lines.append(line)
    return "\n".join(lines)


def _active_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.split("#", 1)[0].strip()
    return result


def _expected(default: object) -> str:
    if isinstance(default, bool):
        return "true" if default else "false"
    return str(default)


def test_every_cache_env_name_is_documented_with_code_default():
    section = _active_key_values(_cache_section())
    assert section, "缓存段解析出 0 个 active 键 —— 判据会退化成空转"
    defaults = _read_defaults()

    missing = sorted(set(defaults) - set(section))
    assert not missing, f"代码读而根 .env.example 缓存段未记载的键：{missing}"

    drift = {k: (section[k], _expected(v)) for k, v in defaults.items() if k in section and section[k] != _expected(v)}
    assert not drift, f"模板值与代码默认不一致（键: 模板值, 代码值）：{drift}"


def test_cache_section_has_no_dead_keys():
    """反向：缓存段内每个 active 键都必须由 `cache/config.py` 读取（段外键不参与）。"""
    section = _active_key_values(_cache_section())
    dead = sorted(set(section) - set(_read_defaults()))
    assert not dead, f"缓存段里有本模块不读的键：{dead}——照它设值是静默无效，不是报错"


def test_two_breaker_families_stay_separate():
    """平台侧 `BREAKER_*` 与缓存侧 `CACHE_BREAKER_*` 各归各处，互不冒充。

    两条判据合起来才闭环：只查"段内都被读"会漏掉"有人把平台侧键搬进缓存段"（键名对不上
    本模块 → 反过来被搬出的那条判据击中）；只查"段外"则管不住缓存侧键被搬走。
    """
    platform_keys = {"BREAKER_FAILURE_THRESHOLD", "BREAKER_RECOVERY_SECONDS"}
    cache_keys = {"CACHE_BREAKER_FAILURES", "CACHE_BREAKER_RECOVERY_SECONDS"}

    section = set(_active_key_values(_cache_section()))
    derived = set(_read_defaults())

    assert cache_keys <= section and cache_keys <= derived, "缓存侧熔断旋钮必须既在段内又被本模块读取"
    assert not (platform_keys & section), "平台侧 BREAKER_* 不属于缓存段：它由 agent_server 的 Settings 字段名派生"
    assert not (platform_keys & derived), "本模块不读 BREAKER_*：读它会把两套旋钮并成一套"

    documented = set(_active_key_values(_ENV.read_text(encoding="utf-8-sig")))
    assert platform_keys <= documented, (
        "BREAKER_* 仍是 agent_server 的真实旋钮（config.py:47-48，main.py:396 消费），不得删"
    )


def test_derivation_covers_both_direct_and_wrapped_env_reads():
    """派生口径必须同时抓到直调形与包装形，否则加一个旋钮就静默脱离门禁。

    `_env_timeout_ms` 是 `env_int` 的包装：只按 `env_*` 名字扫会漏掉两个超时键
    （实测漏检时它们从门禁里消失，而模板照样写着旧值也照样"全绿"）。
    """
    names = set(_read_defaults())
    assert {"CACHE_CONNECT_TIMEOUT_MS", "CACHE_COMMAND_TIMEOUT_MS"} <= names, (
        "包装形 env 读取没被派生到，门禁的被检对象少了一类"
    )
    assert "CACHE_ENABLED" in names and "CACHE_KEY_PREFIX" in names, "直调形派生意外缺失"
    assert "CACHE_BACKEND" in names
