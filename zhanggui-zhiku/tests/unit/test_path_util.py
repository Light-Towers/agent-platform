# -*- coding: utf-8 -*-
"""
test_path_util.py —— 验证 app/utils/path_util.py 的路径工具。

【不依赖重型依赖，可在纯 pytest+numpy+python-dotenv 环境运行。】
path_util 仅依赖 stdlib（pathlib / os）与 app.core.config，
而 app.core.config 亦为纯逻辑模块，不会拉起重型依赖。

覆盖：
- get_path_dir(ps)：基于 __file__ 向上取第 ps 级目录，返回 Path
- get_project_root(identifier)：优先读 PROJECT_ROOT 环境变量，否则回落全局 PROJECT_ROOT
"""

from pathlib import Path

from app.utils.path_util import get_path_dir, get_project_root


def test_get_path_dir_returns_path():
    d = get_path_dir(0)
    assert isinstance(d, Path)


def test_get_path_dir_zero_points_to_utils():
    # path_util.py 位于 app/utils，parents[0] == app/utils
    d = get_path_dir(0)
    assert d.name == "utils"
    assert (d / "path_util.py").is_file()


def test_get_path_dir_one_points_to_app():
    d = get_path_dir(1)
    assert d.name == "app"


def test_get_path_dir_two_points_to_repo_root():
    d = get_path_dir(2)
    # 仓库根目录名
    assert d.is_dir()


def test_get_project_root_returns_path():
    root = get_project_root()
    assert isinstance(root, Path)


def test_get_project_root_default_is_repo_root():
    # 无 PROJECT_ROOT 环境变量时应回落到全局 PROJECT_ROOT（仓库根）
    import os

    env_val = os.environ.pop("PROJECT_ROOT", None)
    try:
        root = get_project_root()
        assert (root / "app").is_dir()
    finally:
        if env_val is not None:
            os.environ["PROJECT_ROOT"] = env_val


def test_get_project_root_env_override(monkeypatch):
    # 若 PROJECT_ROOT 环境变量存在且目录存在，应优先返回它

    from app.core.config import PROJECT_ROOT as GLOBAL_ROOT

    monkeypatch.setenv("PROJECT_ROOT", str(GLOBAL_ROOT))
    root = get_project_root()
    assert root == GLOBAL_ROOT
