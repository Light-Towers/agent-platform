"""kefu-service 测试 conftest：将仓库根加入 sys.path，便于导入 kefu_agent 包。"""
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
