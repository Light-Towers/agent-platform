"""SlotCommand：槽位填充/清除命令。"""

from dataclasses import dataclass

from dialogue_framework.dialogue_understanding.commands.base import BaseCommand


@dataclass
class SlotCommand(BaseCommand):
    name: str = "slot"

    async def execute(self, tracker) -> dict:
        slot_name = self.params.get("name")
        action = self.params.get("action", "fill")
        if action == "fill" and slot_name:
            tracker.set_slot(slot_name, self.params.get("value", ""))
        elif action == "clear" and slot_name and slot_name in tracker.slots:
            tracker.slots[slot_name].reset()
        return {"type": "slot", "name": slot_name, "action": action}
