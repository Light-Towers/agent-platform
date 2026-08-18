# Agent Platform 本地/CI 工程门禁
# 统一任务入口，避免各脚本分散调用；所有目标零业务副作用。

.PHONY: install lint format type test eval eval-llm-required eval-llm-memory ci compose-smoke

install:
	uv sync --all-packages --extra dev

lint:
	uv run --with ruff ruff check .

format:
	uv run --with ruff ruff format .

type:
	uv run --with ruff ruff check . --select ALL 2>/dev/null || uv run --with ruff ruff check .

# 单测门禁：根套件（tests/ + agent-core/tests/）走默认 conftest；
# deepagents/kefu 套件各自独立 pytest session，避免跨目录 conftest 插件名冲突
# （两者都含 tests/conftest，importlib 模式下均注册为 tests.conftest）。
# 三套件任一失败即中断，确保 #2 审查项（防回归测试纳入 CI）真正落地。
test:
	uv run pytest -q
	uv run pytest deepagents/tests/unit -q --ignore=deepagents/tests/unit/test_tool_registry.py
	uv run pytest kefu-service/tests -q

# 评测门禁：默认启发式（确定性，CI 可达），阈值 0.8；LLM_API_KEY 缺失时回退启发式并 WARN。
# 注意：必须用直接路径 `eval/run_eval.py` 而非 `-m eval.run_eval`，
# 否则会命中 deepagents 包内同名模块（workspace 命名冲突）。
# CI 完整 LLM 评测用 `make eval-llm-required`（环境不可达时 SKIP 退出码 2，不假装通过）。
eval:
	uv run python eval/run_eval.py --fail-below 0.8

eval-llm-required:
	uv run python eval/run_eval.py --require-llm --fail-below 0.8

# 跨轮记忆复用 LLM 雷达（ADR-0004 候选B）：验证 typed 记忆跨轮复用 + workspace 隔离。
# 依赖 LLM_API_KEY + DATABASE_URL；缺失时显式 SKIP(2)，不阻塞 CI。
eval-llm-memory:
	uv run python eval/memory_reuse_llm.py

# 检索回归评测：用 FlashRAG 的 retrieval_recall@k 对照「关 rerank」vs「开 rerank」。
# 需 pgvector 容器（见 docs/opencode-llm-setup.md §1.1）与真实 embedding/rerank 可达。
# 两次结果差值 Δ 即 rerank 带来的准确率变化；基线见文档 §8。
# 注意：必须在项目根运行（不 cd 进子目录），否则 pydantic-settings 找不到 .env
# 导致走内存模式、init_pool 返回 None。
eval-rag:
	RERANK_ENABLED=false uv run --extra eval python scripts/flashrag_eval/run_eval.py
	RERANK_ENABLED=true  uv run --extra eval python scripts/flashrag_eval/run_eval.py

# CI 串联：lint + 单测 + 评测门禁；任一失败即中断。
ci: lint test eval

# TB-7 端到端冒烟：需本机 Docker 守护进程可用。启动 pgvector + agent-platform，
# 等待两服务 healthcheck 变 healthy，再探测 /health 返回，最后清理。
# 无 Docker 的环境用 `uv run python scripts/smoke_memory.py` 做等价内存模式预热冒烟。
# 若本机 8000 被其他服务占用，用 `HOST_PORT=18000 make compose-smoke` 临时切换宿主端口
# （探测走容器内 127.0.0.1:8000，与宿主端口无关，故切换不影响冒烟语义）。
compose-smoke:
	docker compose up -d --build --wait
	@echo "== agent-platform /health =="; docker compose exec -T agent-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
	docker compose down -v
