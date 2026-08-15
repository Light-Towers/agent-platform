"""deepagents 测试 conftest：统一 sys.path 注入。"""

import sys
from pathlib import Path

_deepagents_root = str(Path(__file__).resolve().parents[1])
if _deepagents_root not in sys.path:
    sys.path.insert(0, _deepagents_root)
