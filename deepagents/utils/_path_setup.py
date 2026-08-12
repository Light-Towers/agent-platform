import sys
from pathlib import Path

_agent_core_dir = Path(__file__).resolve().parent.parent.parent / "agent-core"
if _agent_core_dir.is_dir() and str(_agent_core_dir) not in sys.path:
    sys.path.insert(0, str(_agent_core_dir))
