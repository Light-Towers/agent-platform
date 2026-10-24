# -*- coding: utf-8 -*-
"""nl2sql-service 的 env 模板一致性用例（roadmap #21 / P2-5，与 §19 会展侧同族）。

钉三件事：

1. **正向齐全**：`Settings.model_fields`（含从 `shared_schemas.BaseLLMSettings` 继承的 12 个）每个字段的
   env 名都必须作为 active 键出现在 `applications/nl2sql-service/.env.example`。
   反例形状：代码加了字段、模板没加 ⇒ 照模板部署时该能力静默保持代码默认值（`RERANK_*` 整族此前就是这样）。
2. **补齐段的值 == 代码 Field 默认**：只校 §marker 之后那一段，段内不出现代码不读的键。
3. **前提守卫**：本服务 `env_prefix` 为空且字段无 alias ⇒ "字段名大写"才等于真实 env 名。

**为什么不照搬会展那条反向判据**（"模板里每个带前缀的键都必须是字段"）：本服务前缀为空，
该判据会把模板里**经 `os.getenv` 读取的非 pydantic 键**一并打成死键，而全仓 `os.getenv` 扫描的范围与
形态属待拍板项（见 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §3 第 12 项）⇒ 本批只做段内齐全与段内值等。
另注：`PORT=8002` 与代码默认 8000 **刻意不一致**（避开与 agent_server 抢端口，文件内第 27-29 行已写明依据），
所以它落在 marker 段之外、不参与等值比对——这是设计，不是漏检。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nl2sql_service.conf.settings import Settings

_TEMPLATE = Path(__file__).resolve().parents[1] / ".env.example"
_MARKER = "# ===== nl2sql-service 模板补齐（2026-10-16）====="


def _active_key_values(text: str) -> dict[str, str]:
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


def _env_defaults() -> dict[str, object]:
    return {name.upper(): field.default for name, field in Settings.model_fields.items()}


def test_env_names_are_field_names_uppercased():
    """守卫本用例口径：一旦引入 env_prefix / alias，"字段名大写"就不再是真实 env 名。"""
    cfg = Settings.model_config or {}
    assert not cfg.get("env_prefix"), f"本用例按无前缀口径比对，env_prefix 现为 {cfg.get('env_prefix')!r}"
    for name, field in Settings.model_fields.items():
        assert field.alias is None and field.validation_alias is None, f"{name} 带 alias，需同步改用例口径"


def test_every_settings_field_is_documented_in_env_example():
    documented = set(_active_key_values(_TEMPLATE.read_text(encoding="utf-8-sig")))
    missing = sorted(set(_env_defaults()) - documented)
    assert not missing, f"代码读而 .env.example 未记载的键 {len(missing)} 个：{missing}"


def test_backfill_section_values_match_code_defaults():
    text = _TEMPLATE.read_text(encoding="utf-8-sig")
    _, sep, tail = text.partition(_MARKER)
    if not sep:
        pytest.fail(f".env.example 缺少补齐段标记：{_MARKER}")

    defaults = _env_defaults()
    section = _active_key_values(tail)
    assert section, "补齐段里没有任何 active 键，用例等于空转"

    unknown = sorted(set(section) - set(defaults))
    assert not unknown, f"补齐段里有代码不读的键：{unknown}"

    drift = {k: (v, _expected_value(defaults[k])) for k, v in section.items() if v != _expected_value(defaults[k])}
    assert not drift, f"补齐段默认值与代码 Field 默认不一致（键: 模板值, 代码值）：{drift}"
