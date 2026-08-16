# Agent Platform 本地/CI 工程门禁
# 统一任务入口，避免各脚本分散调用；所有目标零业务副作用。

.PHONY: install lint format type test eval eval-llm-required ci

install:
	uv sync --all-packages --extra dev

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run ruff check . --select ALL 2>/dev/null || uv run ruff check .

test:
	uv run pytest -q

# 评测门禁：默认启发式（确定性，CI 可达），阈值 0.8；LLM_API_KEY 缺失时回退启发式并 WARN。
# 注意：必须用直接路径 `eval/run_eval.py` 而非 `-m eval.run_eval`，
# 否则会命中 deepagents 包内同名模块（workspace 命名冲突）。
# CI 完整 LLM 评测用 `make eval-llm-required`（环境不可达时 SKIP 退出码 2，不假装通过）。
eval:
	uv run python eval/run_eval.py --fail-below 0.8

eval-llm-required:
	uv run python eval/run_eval.py --require-llm --fail-below 0.8

# CI 串联：lint + 单测 + 评测门禁；任一失败即中断。
ci: lint test eval
