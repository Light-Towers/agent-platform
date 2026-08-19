# -*- coding: utf-8 -*-
"""
检索链路配置（M3，方案 §7.2）：读取 ``app/conf/retrieval.yaml``。

对外暴露模块级单例 ``retrieval_cfg``（CfgDict，属性访问）：

    retrieval_cfg.hybrid.dense_weight     # 0.8
    retrieval_cfg.rrf.k                   # 60
    retrieval_cfg.rrf.weights["embedding"]  # 1.0
    retrieval_cfg.channels.embedding.timeout_s  # 1.5

加载失败（文件缺失 / yaml 非法）会在 import 时立即抛出，避免运行到一半才发现配置错误。
环境变量 ``ZHANGUI_RETRIEVAL_YAML`` 可覆盖 yaml 路径（部署 / 单测隔离用）。
"""

from pathlib import Path

from app.conf.yaml_config_utils import CfgDict, load_yaml_config

# yaml 文件路径（与代码同目录分发）
_RETRIEVAL_YAML = Path(__file__).resolve().parent / "retrieval.yaml"
# 环境变量覆盖键
_RETRIEVAL_YAML_ENV = "ZHANGUI_RETRIEVAL_YAML"

# 模块级单例：全项目统一从此处读取检索配置
retrieval_cfg: CfgDict = load_yaml_config(_RETRIEVAL_YAML, _RETRIEVAL_YAML_ENV)
