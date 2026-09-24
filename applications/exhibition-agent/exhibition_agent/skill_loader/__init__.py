"""会展 Skill 加载服务。

启动时读取 mingyang-warehouse 的 exhibition-readonly/SKILL.md，解析 48 个 REST 端点，
提供 Web 界面让用户选 skill、填参数、调用，服务代理调 warehouse REST 端点返回结果。
"""

from .parser import Endpoint, Param, load_endpoints, parse_skill_md

__all__ = ["Endpoint", "Param", "load_endpoints", "parse_skill_md"]
