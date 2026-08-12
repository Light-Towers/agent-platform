# -*- coding: utf-8 -*-
"""
轻量 yaml 配置加载工具（M3，方案 §7）。

设计原则：
- 复用 `app/conf/` 既有「配置模块 + 模块级单例」风格（见 milvus_config.py），不引入
  Hydra / MLflow 等重型框架。
- yaml 解析用标准库生态的 ``yaml.safe_load``（pyyaml 已随项目依赖传递存在，见 uv.lock）。
- 返回 ``CfgDict``：dict 子类 + 属性访问，支持 ``cfg.rrf.k`` 与 ``cfg.rrf.weights["embedding"]``
  两种风格，便于节点代码以最自然的方式读取。
- 支持环境变量覆盖 yaml 路径（如 ``ZHANGUI_RETRIEVAL_YAML``），便于部署与单测覆盖。
"""

import os
from pathlib import Path
from typing import Any

import yaml


class CfgDict(dict):
    """
    dict 子类，支持属性访问；嵌套 dict / list 在加载时递归转换为 CfgDict。

    例：
        cfg = CfgDict({"rrf": {"k": 60}})
        cfg.rrf.k == 60        # 属性访问
        cfg["rrf"]["k"] == 60  # dict 访问
        cfg.rrf.weights["embedding"] == 1.0  # 混合访问
    """

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"CfgDict 无属性 {key!r}") from None

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def _to_cfg(value: Any) -> Any:
    """递归把 dict → CfgDict、list → list[CfgDict]。"""
    if isinstance(value, dict):
        return CfgDict({k: _to_cfg(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_cfg(v) for v in value]
    return value


def load_yaml_config(path: Path, env_override_key: str) -> CfgDict:
    """
    加载 yaml 配置。

    参数：
        path: 默认配置文件路径（随代码分发）
        env_override_key: 环境变量名；若设置，则用它指向的路径替代默认路径
                          （部署覆盖 / 单测隔离用）
    返回：
        CfgDict - 嵌套属性访问配置对象
    异常：
        FileNotFoundError - 默认与覆盖路径均不存在
        yaml.YAMLError - yaml 内容非法（不静默吞掉，便于发现配置错误）
    """
    override = os.getenv(env_override_key)
    target = Path(override) if override else path
    if not target.exists():
        raise FileNotFoundError(f"yaml 配置不存在：{target}（默认路径 {path}，可用环境变量 {env_override_key} 覆盖）")
    with open(target, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"yaml 配置顶层必须是映射：{target}")
    return CfgDict({k: _to_cfg(v) for k, v in data.items()})
