"""Singleflight：从 agent_runtime 重导出（F-S1-04 收口）。

原实现已迁至 ``agent_runtime.singleflight``（通用，无 federation 依赖）。
"""

from agent_runtime.singleflight import singleflight

__all__ = ["singleflight"]
