"""StackFrame：Flow 嵌套调用栈帧。"""

from dataclasses import dataclass


@dataclass
class StackFrame:
    flow_id: str
    step_index: int = 0
