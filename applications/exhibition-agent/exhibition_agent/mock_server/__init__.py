"""mock_server/：warehouse 侧契约的假实现（9 场景 fixture 切换）。

不依赖真实 warehouse / MySQL，供 exhibition-agent 自测跑通契约链路。
"""

from exhibition_agent.mock_server.warehouse_mock import (
    MOCK_SCENARIOS,
    create_mock_app,
)

__all__ = ["create_mock_app", "MOCK_SCENARIOS"]
