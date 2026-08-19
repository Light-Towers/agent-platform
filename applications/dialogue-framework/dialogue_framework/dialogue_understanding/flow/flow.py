"""Flow + FlowStep：Flow 定义。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowStep:
    id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    next: str | None = None
    condition: str | None = None


@dataclass
class Flow:
    id: str
    steps: list[FlowStep] = field(default_factory=list)

    def get_step(self, step_id: str) -> FlowStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    @classmethod
    def from_dict(cls, data: dict) -> "Flow":
        steps = [
            FlowStep(
                id=s["id"],
                action=s["action"],
                params=s.get("params", {}),
                next=s.get("next"),
                condition=s.get("condition"),
            )
            for s in data.get("steps", [])
        ]
        return cls(id=data["id"], steps=steps)
