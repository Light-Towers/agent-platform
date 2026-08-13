"""FlowExecutor：执行 Flow 步骤 + 跳转。"""

from typing import Any

from dialogue_framework.dialogue_understanding.flow.flow import Flow


class FlowExecutor:
    async def execute(self, flow: Flow, tracker, start_step: str = "start") -> dict[str, Any]:
        results = []
        step_id = start_step
        visited: set[str] = set()
        while step_id and step_id not in visited:
            visited.add(step_id)
            step = flow.get_step(step_id)
            if step is None:
                break
            tracker.update(step.action, step_id=step_id, **step.params)
            results.append({"step_id": step_id, "action": step.action})
            step_id = step.next
        return {"flow_id": flow.id, "steps": results}
