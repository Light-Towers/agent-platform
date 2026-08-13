"""wenda_adapter 专用 fixture。"""

import sys
from pathlib import Path

_WENDA_ADAPTER_DIR = Path(__file__).resolve().parent.parent.parent / "wenda-adapter"
if str(_WENDA_ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(_WENDA_ADAPTER_DIR))
