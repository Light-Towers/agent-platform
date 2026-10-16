# -*- coding: utf-8 -*-
"""agent_server 的 env 模板一致性用例（roadmap #21 / §10 P2-5 缺口 ①）。

钉两件事，都只针对根 `.env.example` 里"补齐"那一段（口径见该段抬头）：

1. **正向齐全**：`Settings.model_fields` 每个字段名都必须作为 active 键出现在模板里。
   反例形状：代码加了字段、模板没加 ⇒ 运维照模板部署后该能力静默保持默认值。
   这正是 KS 观测两键漂移的对偶面（那处是"模板有而代码无"，见
   `applications/knowledge-service/tests/unit/test_tracing.py::test_env_example_observability_keys_are_read_by_code`）。
2. **补齐段的值 == 代码 Field 默认**，且段内不出现代码不读的键。

为什么补在根模板而不是给 agent_server 单独建一份：agent_server 的 `.env` 解析基准是进程 CWD，
本地 `uvicorn agent_server.main:app`（AGENTS.md 运行方式）与镜像内 `Dockerfile:3`
`WORKDIR /srv/agent-platform` 都落在仓库根 ⇒ 单独那份从来不会被读。

**不做全仓反向门禁**（"模板里每个键都必须有读取方"）：那要先扫全仓 `os.getenv` 与各家
`env_prefix` 折算，范围与形态属待拍板项（见 plan-unfinished-completion-schedule §3 第 12 项）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_server.config import Settings

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env.example"
_BACKFILL_MARKER = "# ===== agent_server（supervisor 平台）模板补齐（2026-10-16）====="


def _active_key_values(text: str) -> dict[str, str]:
    """解析"会生效"的键：跳过整行注释，剥掉行内注释。"""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.split("#", 1)[0].strip()
    return result


def _field_defaults() -> dict[str, object]:
    return {name.upper(): f.default for name, f in Settings.model_fields.items()}


def test_every_settings_field_is_documented_in_root_env_example():
    documented = set(_active_key_values(_ROOT_ENV.read_text(encoding="utf-8-sig")))
    missing = sorted(set(_field_defaults()) - documented)
    assert not missing, (
        f"agent_server 读而根 .env.example 未记载的键 {len(missing)} 个：{missing}。"
        "补进根模板（它是本服务实际加载的那份），不要新建 applications/agent_server/.env.example。"
    )


def test_field_names_are_env_names_verbatim():
    """键名 = 字段名大写：本服务与 BaseLLMSettings 都不得引入 env_prefix / alias。

    一旦有人加前缀或别名，上面那条按"字段名大写"做的比对就会与真实读取名脱节 —— 那是
    KS 观测两键那类漂移的又一种形状（判某 env 名有没有被读，不能只字面 grep）。
    """
    from pydantic_settings import BaseSettings

    for cls in (Settings, *Settings.__mro__[1:]):
        if not issubclass(cls, BaseSettings):
            continue
        cfg = cls.model_config or {}
        assert not cfg.get("env_prefix"), f"{cls.__name__} 引入了 env_prefix，需同步改用例口径"
        for name, field in cls.model_fields.items():
            assert field.alias is None and field.validation_alias is None, (
                f"{cls.__name__}.{name} 带 alias，大写键名不再是真实 env 名"
            )


def _backfill_section() -> dict[str, str]:
    text = _ROOT_ENV.read_text(encoding="utf-8-sig")
    _, sep, tail = text.partition(_BACKFILL_MARKER)
    if not sep:
        pytest.fail(f"根 .env.example 缺少补齐段标记：{_BACKFILL_MARKER}")
    return _active_key_values(tail)


def _expected_value(default: object) -> str:
    if isinstance(default, bool):
        return "true" if default else "false"
    return "" if default is None else str(default)


def test_backfill_section_values_match_code_defaults():
    defaults = _field_defaults()
    section = _backfill_section()

    unknown = sorted(set(section) - set(defaults))
    assert not unknown, f"补齐段里有代码不读的键：{unknown}"

    drift = {k: (v, _expected_value(defaults[k])) for k, v in section.items() if v != _expected_value(defaults[k])}
    assert not drift, f"补齐段默认值与代码 Field 默认不一致（键: 模板值, 代码值）：{drift}"
