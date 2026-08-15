"""DialogueStack：Flow 嵌套调用栈管理。"""

from dialogue_framework.dialogue_understanding.stack.stack_frame import StackFrame


class DialogueStack:
    def __init__(self) -> None:
        self._frames: list[StackFrame] = []

    def push(self, flow_id: str, step_index: int = 0) -> None:
        self._frames.append(StackFrame(flow_id=flow_id, step_index=step_index))

    def pop(self) -> StackFrame | None:
        return self._frames.pop() if self._frames else None

    def top(self) -> StackFrame | None:
        return self._frames[-1] if self._frames else None

    @property
    def depth(self) -> int:
        return len(self._frames)
