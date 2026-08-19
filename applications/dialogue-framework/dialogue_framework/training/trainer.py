"""Trainer：训练器，对齐 eval/run_eval.py 评测管线。

训练数据生成 → eval golden.jsonl 格式，无 Rasa/课程栈依赖。
"""

import json
from pathlib import Path

from agent_core.logging import get_logger

from dialogue_framework.training.model_storage import ModelStorage

logger = get_logger(__name__)


class TrainingExample:
    def __init__(self, question: str, expected_capability: str, expected_keywords: list[str] | None = None) -> None:
        self.question = question
        self.expected_capability = expected_capability
        self.expected_keywords = expected_keywords or []


class Trainer:
    """训练器：生成评测数据 + 训练对话理解模型。"""

    def __init__(self, storage: ModelStorage | None = None) -> None:
        self._storage = storage or ModelStorage()
        self._examples: list[TrainingExample] = []

    def add_example(self, question: str, expected_capability: str, expected_keywords: list[str] | None = None) -> None:
        self._examples.append(TrainingExample(question, expected_capability, expected_keywords))

    def add_examples(self, examples: list[dict]) -> None:
        for ex in examples:
            self.add_example(
                ex["question"],
                ex["expected_capability"],
                ex.get("expected_keywords"),
            )

    def export_golden(self, output_path: str | Path) -> int:
        """导出为 eval golden.jsonl 格式。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("w", encoding="utf-8") as f:
            for i, ex in enumerate(self._examples, 1):
                item = {
                    "id": i,
                    "question": ex.question,
                    "expected_capability": ex.expected_capability,
                    "expected_keywords": ex.expected_keywords,
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        logger.info("exported %d examples to %s", count, path)
        return count

    def load_golden(self, input_path: str | Path) -> int:
        """从 golden.jsonl 加载训练数据。"""
        path = Path(input_path)
        count = 0
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                self.add_example(
                    item["question"],
                    item["expected_capability"],
                    item.get("expected_keywords"),
                )
                count += 1
        logger.info("loaded %d examples from %s", count, path)
        return count

    async def train(self, model_name: str = "default") -> dict:
        """训练模型（MVP：存储训练数据为模型产物）。"""
        logger.info("training model: %s, examples=%d", model_name, len(self._examples))
        model_data = {
            "model_name": model_name,
            "examples": [
                {
                    "question": ex.question,
                    "expected_capability": ex.expected_capability,
                    "expected_keywords": ex.expected_keywords,
                }
                for ex in self._examples
            ],
        }
        self._storage.save(model_name, model_data)
        logger.info("model saved: %s", model_name)
        return {"model_name": model_name, "example_count": len(self._examples)}

    @property
    def examples(self) -> list[TrainingExample]:
        return list(self._examples)
