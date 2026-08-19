"""YAML 加载工具（用于 Flow 定义、Domain 定义）。"""

from pathlib import Path

import yaml


def load_yaml(path: str | Path) -> dict:
    """加载 YAML 文件为 dict。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_yaml_str(text: str) -> dict:
    """从 YAML 字符串加载为 dict。"""
    return yaml.safe_load(text) or {}
