# app/utils/path_util.py
"""
项目路径工具。

统一从 `app.core.config` 读取 `PROJECT_ROOT`，不再各自加载 .env / 递归查找根目录。
保留 get_path_dir / get_project_root 两个兼容函数：
- get_path_dir：基于 __file__ 向上取第 N 级目录（静态资源定位常用）；
- get_project_root：优先读取 PROJECT_ROOT 环境变量，未配置时回退到全局 PROJECT_ROOT。
"""

from pathlib import Path
import os

from app.core.config import PROJECT_ROOT


def get_path_dir(ps: int = 0) -> Path:
    """
    pathlib.Path 提供了 parents 属性，这是一个有序的路径上级目录迭代器，直接通过索引取值就能快速获取「上 N 级目录」，完美解决多层 .parent 繁琐的问题，这也是官方推荐的简化写法！
    核心规则：parents[N] 索引对应「向上的层级数」
    parents[0] → 等价于 .parent（当前路径的上 1 级目录）
    parents[1] → 等价于 .parent.parent（当前路径的上 2 级目录）
    parents[2] → 等价于 .parent.parent.parent（当前路径的上 3 级目录）
    以此类推，parents[N] → 直接获取上 N+1 级目录，索引越⼤，层级越靠上
    :param ps: 向上层级数
    :return: 对应的目录 Path
    """
    dir_path = Path(__file__).parents[ps]
    return dir_path


def get_project_root(identifier: str = ".env") -> Path:
    """
    获取项目根目录。
    优先读取 PROJECT_ROOT 环境变量（生产环境常用）；未配置或目录不存在时，
    直接返回全局统一的 PROJECT_ROOT（来自 `app.core.config`，由应用启动时统一加载的环境变量保证生效）。
    :param identifier: 兼容旧逻辑保留的占位参数，已不再用于递归查找
    :return: 项目根目录 Path
    """
    env_root = os.getenv("PROJECT_ROOT")
    if env_root and Path(env_root).absolute().exists():
        return Path(env_root).absolute()
    return PROJECT_ROOT
