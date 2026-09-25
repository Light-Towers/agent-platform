"""agent_federation 测试 conftest：统一 sys.path 注入。"""

import sys
from pathlib import Path

_agent_federation_root = str(Path(__file__).resolve().parents[1])
if _agent_federation_root not in sys.path:
    sys.path.insert(0, _agent_federation_root)
