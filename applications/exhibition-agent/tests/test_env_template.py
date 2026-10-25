# -*- coding: utf-8 -*-
"""exhibition-agent 的 env 模板一致性用例（roadmap #21 / P2-5 的会展侧对偶面）。

与 `tests/governance/test_agent_server_env_template.py` 同族但**口径不能共用**：本服务的
`Settings.model_config` 带 `env_prefix="EXHIBITION_AGENT_"`，真实 env 名是
`前缀 + 字段名大写`，直接套那份用例会得出「10 个字段里 9 个没记载」的**假缺口**
（2026-10-16 实测踩过：前缀-blind 的探针就是这么说的）。⇒ 本用例先从代码读前缀，再比对。

钉三件事：

1. **正向齐全**：`Settings.model_fields` 每个字段的真实 env 名都必须作为 active 键出现在
   `applications/exhibition-agent/.env.example`。反例形状：加字段没加模板 ⇒ 照模板部署时该能力静默保持默认值。
2. **值 == 代码 Field 默认**：模板写的默认值必须与 `Field(default=...)` 一致（不杜撰、不滞后）。
3. **反向不悬空（限前缀内）**：模板里任何 `EXHIBITION_AGENT_*` 键都必须是 `Settings` 的字段。
   本服务 `extra="ignore"` ⇒ 带前缀而非字段名的键**代码根本不读**，正是 knowledge-service
   观测两键那种「模板有、代码无」的死键形状（那处的教训见
   `applications/knowledge-service/tests/unit/test_tracing.py::test_env_example_observability_keys_are_read_by_code`）。

**不做的事**：不扫 `os.getenv` 做全仓反向门禁，也不给非 pydantic-settings 的服务（kefu / nl2sql /
federation / KS 的配置面是 `os.getenv` 与 dataclass，字段名推不出 env 名）建同款用例 —— 范围与形态属
待拍板项（见 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §3 第 12 项）。
"""

from __future__ import annotations

from pathlib import Path

from exhibition_agent.config import Settings

_TEMPLATE = Path(__file__).resolve().parents[1] / ".env.example"
_PREFIX = Settings.model_config.get("env_prefix", "")


def _active_key_values(text: str) -> dict[str, str]:
    """解析"会生效"的键：跳过整行注释，剥掉行内注释。"""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.split("#", 1)[0].strip()
    return result


def _expected_value(default: object) -> str:
    if isinstance(default, bool):
        return "true" if default else "false"
    return "" if default is None else str(default)


def _env_names() -> dict[str, object]:
    return {f"{_PREFIX}{name.upper()}": field.default for name, field in Settings.model_fields.items()}


def test_prefix_is_read_from_code_not_assumed():
    """守卫本用例自己的前提：前缀若被人改掉，下面两条比对的键名会整体失真。"""
    assert _PREFIX == "EXHIBITION_AGENT_", (
        f"env_prefix 变成 {_PREFIX!r}：本用例按「前缀 + 字段名大写」折算真实 env 名，"
        "改前缀必须同步改模板键名，否则模板与代码同时漂移。"
    )
    for name, field in Settings.model_fields.items():
        assert field.alias is None and field.validation_alias is None, f"{name} 带 alias，大写键名不再是真实 env 名"


def test_every_settings_field_is_documented_in_env_example():
    documented = set(_active_key_values(_TEMPLATE.read_text(encoding="utf-8-sig")))
    missing = sorted(set(_env_names()) - documented)
    assert not missing, f"代码读而 .env.example 未记载的键 {len(missing)} 个：{missing}"


def test_template_defaults_match_code_and_no_prefixed_key_is_dead():
    defaults = _env_names()
    template = _active_key_values(_TEMPLATE.read_text(encoding="utf-8-sig"))

    drift = {k: (v, _expected_value(defaults[k])) for k, v in template.items() if k in defaults and v != _expected_value(defaults[k])}
    assert not drift, f"模板默认值与代码 Field 默认不一致（键: 模板值, 代码值）：{drift}"

    # extra="ignore" ⇒ 带前缀却不是字段名的键，代码根本不读
    dead = sorted(k for k in template if k.startswith(_PREFIX) and k not in defaults)
    assert not dead, f"模板里有 {len(dead)} 个带前缀而代码不读的键（死键）：{dead}"
