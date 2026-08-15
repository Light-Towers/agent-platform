# Agent Platform 本地/CI 工程门禁
# 统一任务入口，避免各脚本分散调用；所有目标零业务副作用。

.PHONY: install lint format type test eval ci

install:
	uv sync --all-extras

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run ruff check . --select ALL 2>/dev/null || uv run ruff check .

test:
	uv run pytest -q

eval:
	uv run python -m eval.run_eval

# CI 串联：lint + 单测 + 评测门禁；任一失败即中断。
ci: lint test eval
