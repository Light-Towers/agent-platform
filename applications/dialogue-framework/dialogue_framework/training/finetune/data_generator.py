"""DataGenerator：微调数据生成。

将训练样本转换为 LLM 微调格式（OpenAI JSONL），支持改写增强。
"""

import json
from pathlib import Path

from agent_core.logging import get_logger

from dialogue_framework.training.finetune.paraphraser import Paraphraser

logger = get_logger(__name__)


class DataGenerator:
    """微调数据生成器。"""

    def __init__(self, paraphraser: Paraphraser | None = None) -> None:
        self._paraphraser = paraphraser or Paraphraser()

    async def generate(
        self,
        examples: list[dict],
        output_path: str | Path,
        augment: bool = False,
        system_prompt: str = "你是对话理解助手，根据用户消息判断意图。",
    ) -> int:
        """生成微调 JSONL（OpenAI 格式）。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for ex in examples:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ex["question"]},
                {"role": "assistant", "content": ex["expected_capability"]},
            ]
            lines.append(json.dumps({"messages": messages}, ensure_ascii=False))

            if augment:
                paraphrased = await self._paraphraser.rephrase(ex["question"])
                if paraphrased and paraphrased != ex["question"]:
                    messages_aug = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": paraphrased},
                        {"role": "assistant", "content": ex["expected_capability"]},
                    ]
                    lines.append(json.dumps({"messages": messages_aug}, ensure_ascii=False))

        count = len(lines)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("generated %d fine-tune samples to %s", count, path)
        return count
