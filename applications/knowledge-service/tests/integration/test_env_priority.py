# -*- coding: utf-8 -*-
"""
.env 与系统环境变量的优先级验证。

归并自：`test/01-env和系统环境变量的优先级.py`（原为 print 式手测脚本）。

原脚本要验证的语义（保留其注释中的结论，改为可断言的用例）：
- `load_dotenv()` 默认 `override=False`
  - 系统环境变量不存在 → 用 .env 里的值
  - 系统环境变量已存在 → **系统变量优先级更高**
- 想让 .env 覆盖系统变量，需显式传 `override=True`

依赖：仅 `python-dotenv`（已在 pyproject 的运行时依赖中），无外部服务，
因此优先级用例**无条件执行**；只有读取真实 `.env` 中密钥的冒烟用例需要守卫。
"""

import os

import pytest
from dotenv import load_dotenv

#: 集成测试总开关，未开启时跳过依赖真实 .env / 外部服务的用例。
INTEGRATION_ENABLED = bool(os.environ.get("ZHIKU_INTEGRATION", "").strip())

SKIP_REASON = "需要仓库根存在真实 .env，设置 ZHIKU_INTEGRATION=1 后启用"


def test_system_env_wins_when_override_false(tmp_path, monkeypatch):
    """override=False（默认）时，已存在的系统环境变量优先级更高。"""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=dotenv_val\n", encoding="utf-8")

    monkeypatch.setenv("MY_KEY", "system_val")
    load_dotenv(env_file, override=False)

    assert os.getenv("MY_KEY") == "system_val"


def test_dotenv_wins_when_override_true(tmp_path, monkeypatch):
    """显式 override=True 时，.env 的值覆盖系统环境变量。"""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=dotenv_val\n", encoding="utf-8")

    monkeypatch.setenv("MY_KEY", "system_val")
    load_dotenv(env_file, override=True)

    assert os.getenv("MY_KEY") == "dotenv_val"


def test_dotenv_fills_missing_system_env(tmp_path, monkeypatch):
    """系统环境变量不存在时，.env 的值被写入（无论 override 取值）。"""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=dotenv_val\n", encoding="utf-8")

    monkeypatch.delenv("MY_KEY", raising=False)
    load_dotenv(env_file, override=False)

    assert os.getenv("MY_KEY") == "dotenv_val"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_repo_dotenv_provides_openai_api_key():
    """冒烟：加载仓库根 .env 后应能读到 OPENAI_API_KEY（原脚本的核心动作）。"""
    load_dotenv(override=True)

    api_key = os.getenv("OPENAI_API_KEY")
    assert api_key, "未从 .env 或系统环境变量中读取到 OPENAI_API_KEY"
