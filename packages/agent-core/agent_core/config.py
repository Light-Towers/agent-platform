# -*- coding: utf-8 -*-
"""内核配置层（WS-5）：env 读取集中化 + 类型化解析。

背景：此前内核各模块散点 ``os.getenv``（SEMANTIC_MEMORY_ENABLED /
SEMANTIC_MEMORY_TYPED / MEMORY_FORGET_THRESHOLD / VECTOR_BACKEND ...），
无统一校验、无类型转换、无文档化清单。本模块提供：

- ``env_bool / env_int / env_float / env_str``：类型化 env 解析，非法值记警告并回退默认；
- ``env_database_url``：数据库 URL 解析（新名 ``AGENT_PLATFORM_DATABASE_URL``
  优先，旧名 ``DEEPAGENTS_DATABASE_URL`` 兼容一个小版本并触发弃用警告）；
- ``KernelConfig``：常用内核配置快照（dataclass），供宿主一次性构造注入。

环境变量清单（新增 env 必须登记，见 packages/agent-core/README.md）：

==========================  ====================  ==============================
变量                         默认值                用途
==========================  ====================  ==============================
SEMANTIC_MEMORY_ENABLED      false                语义记忆总开关
SEMANTIC_MEMORY_TYPED        true                 typed 加权策略开关（WS-1 起默认开，不再决定走哪条栈）
SEMANTIC_MEMORY_COLLECTION   semantic_memory      向量集合/表名
VECTOR_BACKEND               milvus               向量后端（milvus|pg）
MILVUS_URI / MILVUS_TOKEN    localhost:19530 / "" Milvus 连接
AGENT_PLATFORM_DATABASE_URL  ""（回退 DATABASE_URL）pg 后端 URL（旧名 DEEPAGENTS_DATABASE_URL）
TENANT_ID                    default              多租户隔离
MEMORY_FORGET_THRESHOLD      0.1                  consolidate 重要度阈值
MEMORY_FORGET_AGE_DAYS       30                   consolidate 老化天数
EMBEDDING_MODE / EMBEDDING_DIM / SILICONFLOW_API_KEY  mock/512/""  embedder 选型
==========================  ====================  ==============================

§3 内核护栏：仅 stdlib。
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field

from agent_core.logging import get_logger

logger = get_logger(__name__)

# 数据库 URL：新名优先；旧名 deepagents 改名遗留，兼容一个小版本（WS-5）
ENV_DATABASE_URL = "AGENT_PLATFORM_DATABASE_URL"
LEGACY_ENV_DATABASE_URL = "DEEPAGENTS_DATABASE_URL"


def env_bool(name: str, default: bool = False) -> bool:
    """布尔 env 解析：1/true/yes/on 为真（不区分大小写）；非法值回退默认并警告。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off", ""):
        return False
    logger.warning("[config] %s=%r 非法布尔值，回退默认 %s", name, raw, default)
    return default


def env_int(name: str, default: int) -> int:
    """整型 env 解析；非法值回退默认并警告。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("[config] %s=%r 非法整型值，回退默认 %d", name, raw, default)
        return default


def env_float(name: str, default: float) -> float:
    """浮点 env 解析；非法值回退默认并警告。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[config] %s=%r 非法浮点值，回退默认 %s", name, raw, default)
        return default


def env_str(name: str, default: str = "") -> str:
    """字符串 env 读取（集中化入口，WS-5）：未设置返回默认值。

    内核模块读字符串型 env 统一经本函数，便于后续统一审计/清单登记。
    """
    value = os.getenv(name)
    return default if value is None else value


def env_database_url(legacy_fallback: str = "DATABASE_URL") -> str:
    """数据库 URL 解析：新名 → 旧名（弃用警告）→ 通用回退名。

    deepagents 已改名 agent_federation，``DEEPAGENTS_DATABASE_URL`` 为遗留名：
    命中时触发一次 DeprecationWarning，提示迁移到 ``AGENT_PLATFORM_DATABASE_URL``。
    """
    url = os.getenv(ENV_DATABASE_URL)
    if url:
        return url
    legacy = os.getenv(LEGACY_ENV_DATABASE_URL)
    if legacy:
        warnings.warn(
            f"{LEGACY_ENV_DATABASE_URL} 已弃用，请迁移到 {ENV_DATABASE_URL}（WS-5）",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy
    return os.getenv(legacy_fallback, "")


@dataclass
class KernelConfig:
    """内核常用配置快照（宿主可一次性构造后注入，替代模块内散点读 env）。

    字段默认值与历史 env 默认一致；``from_env()`` 按上表解析当前进程 env。
    """

    semantic_memory_enabled: bool = False
    semantic_memory_typed: bool = True
    vector_backend: str = "milvus"
    semantic_memory_collection: str = "semantic_memory"
    tenant_id: str = "default"
    database_url: str = ""
    memory_forget_threshold: float = 0.1
    memory_forget_age_days: int = 30
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "KernelConfig":
        return cls(
            semantic_memory_enabled=env_bool("SEMANTIC_MEMORY_ENABLED", False),
            semantic_memory_typed=env_bool("SEMANTIC_MEMORY_TYPED", True),
            vector_backend=env_str("VECTOR_BACKEND", "milvus").lower(),
            semantic_memory_collection=env_str(
                "SEMANTIC_MEMORY_COLLECTION", "semantic_memory"
            ),
            tenant_id=env_str("TENANT_ID", "default"),
            database_url=env_database_url(),
            memory_forget_threshold=env_float("MEMORY_FORGET_THRESHOLD", 0.1),
            memory_forget_age_days=env_int("MEMORY_FORGET_AGE_DAYS", 30),
        )


__all__ = [
    "ENV_DATABASE_URL",
    "LEGACY_ENV_DATABASE_URL",
    "env_bool",
    "env_int",
    "env_float",
    "env_str",
    "env_database_url",
    "KernelConfig",
]
