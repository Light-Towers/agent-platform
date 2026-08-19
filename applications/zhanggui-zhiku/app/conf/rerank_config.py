# -*- coding: utf-8 -*-
"""
重排配置（M3，方案 §7.3）：读取 ``app/conf/rerank.yaml``。

对外暴露模块级单例 ``rerank_cfg``（CfgDict，属性访问）：

    rerank_cfg.model                       # BAAI/bge-reranker-v2-m3
    rerank_cfg.max_concurrency             # 8
    rerank_cfg.dynamic_topk.gap_ratio      # 0.25
    rerank_cfg.dynamic_topk.gap_abs        # 0.5
    rerank_cfg.fallback.on_error           # passthrough

加载失败（文件缺失 / yaml 非法）会在 import 时立即抛出，避免运行到一半才发现配置错误。
环境变量 ``ZHANGUI_RERANK_YAML`` 可覆盖 yaml 路径（部署 / 单测隔离用）。
"""

from pathlib import Path

from app.conf.yaml_config_utils import CfgDict, load_yaml_config

# yaml 文件路径（与代码同目录分发）
_RERANK_YAML = Path(__file__).resolve().parent / "rerank.yaml"
# 环境变量覆盖键
_RERANK_YAML_ENV = "ZHANGUI_RERANK_YAML"

# 模块级单例：全项目统一从此处读取重排配置
rerank_cfg: CfgDict = load_yaml_config(_RERANK_YAML, _RERANK_YAML_ENV)
