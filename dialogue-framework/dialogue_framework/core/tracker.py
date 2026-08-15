"""Tracker：对话状态追踪。"""

from dataclasses import dataclass, field
from typing import Any

from dialogue_framework.core.slots import Slot


@dataclass
class Tracker:
    session_id: str
    slots: dict[str, Slot] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    stack: list[dict[str, Any]] = field(default_factory=list)
    latest_intent: str | None = None
    latest_action: str | None = None

    def get_slot(self, name: str) -> Slot | None:
        return self.slots.get(name)

    def set_slot(self, name: str, value: str) -> None:
        if name not in self.slots:
            self.slots[name] = Slot(name=name)
        self.slots[name].fill(value)

    def add_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def update(self, action: str, **kwargs: Any) -> None:
        self.latest_action = action
        self.add_event({"action": action, **kwargs})

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "slots": {n: {"name": s.name, "value": s.value, "filled": s.filled} for n, s in self.slots.items()},
            "events": self.events,
            "stack": self.stack,
            "latest_intent": self.latest_intent,
            "latest_action": self.latest_action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tracker":
        tracker = cls(session_id=data["session_id"])
        for name, s in data.get("slots", {}).items():
            tracker.slots[name] = Slot(name=s["name"], value=s.get("value"), filled=s.get("filled", False))
        tracker.events = data.get("events", [])
        tracker.stack = data.get("stack", [])
        tracker.latest_intent = data.get("latest_intent")
        tracker.latest_action = data.get("latest_action")
        return tracker
