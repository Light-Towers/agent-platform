# Agent Platform 本地/CI 工程门禁
# 统一任务入口，避免各脚本分散调用；所有目标零业务副作用。

.PHONY: install lint format type test eval eval-llm-required eval-llm-memory eval-rag eval-rag-routes eval-rag-retrieval eval-rag-e2e eval-rag-gate eval-rag-baseline eval-rag-meta-ui ci compose-smoke

install:
	uv sync --all-packages --extra dev

lint:
	uv run --with ruff ruff check .
	uv run python scripts/lint_architecture.py

format:
	uv run --with ruff ruff format .

type:
	uv run --with ruff ruff check . --select ALL 2>/dev/null || uv run --with ruff ruff check .

# 单测门禁：根套件（tests/ + agent-core/tests/）走默认 conftest；
# agent_federation/kefu/exhibition-agent 套件各自独立 pytest session，
# 避免跨目录 conftest 插件名冲突（importlib 模式下均注册为 tests.conftest）。
# agent_federation 收集整目录 tests/（含根级 test_auth/test_semantic_memory_typed，2026-09-21 F-S0-03 修复，
# 原先只跑 tests/unit 导致根级 2 文件漏出门禁）。
# agent-runtime/tests（零 conftest）与 knowledge-service/tests（tests/unit/conftest，
# integration 层有 ZHIKU_INTEGRATION=1 守卫、缺环境自动 skip）同样独立 session，2026-09-21 纳入门禁（F-S0-01/F-S0-02）。
# agent_server/tests（GraphPlanner 等应用层集成测试，2026-09-21 F-S1-01 由 agent-runtime/tests 迁入，
# 消除红线 1 反向依赖）同样独立 session。
# 根套件排除 requires_pg（2026-09-25）：tests/ha 属 HA 重型门禁（agent-platform-ha
# workflow 以 -m requires_pg + 真实 PG service 强制执行，CI=true 下环境不满足即 FAIL），
# 普通 CI 无 PG service，混入会导致 skip 掩盖或 FAIL 误报。
# 10 个 session 任一失败即中断，确保 #2 审查项（防回归测试纳入 CI）真正落地。
# 注：本地目录原名 deepagents/（与 PyPI 依赖包同名），2026-08-19 重命名为
# agent_federation/ 彻底消除遮蔽；test_tool_registry 已回归门禁（75 passed）。
test:
	uv run pytest -q -m "not requires_pg"
	uv run pytest packages/shared-schemas/tests -q
	uv run pytest packages/agent-runtime/tests -q
	uv run pytest applications/agent_server/tests -q
	uv run pytest applications/agent_federation/tests -q
	uv run pytest applications/kefu-service/tests -q
	uv run pytest applications/exhibition-agent/tests -q
	uv run pytest applications/knowledge-service/tests -q
	uv run pytest applications/nl2sql-service/tests -q

# 评测门禁：默认启发式（确定性，CI 可达），阈值 0.8；LLM_API_KEY 缺失时回退启发式并 WARN。
# 注：历史上 agent_federation 曾有同名顶层 eval 包（workspace 命名冲突，已于
# 2026-09-25 重命名为 evaluation 根除，见 lint_architecture P5 门禁防复发）。
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

# knowledge-service 检索路线消融（RRF 混合排名 vs 单路召回 + embedding 内 dense/sparse 向量级）。
# 非 hermetic（依赖真实 Milvus + embedding，另可选 Neo4j/LLM/rerank）→ 不进 make ci，手动/nightly。
# 流程：先 seed（写专用集合 eval_rag_routes + 回填真实 chunk_id 生成 labeled golden），再跑消融。
# 缺环境时脚本清晰报错并 return 1，不吞异常、不预填数字。cd 进子目录以加载其 .env。
eval-rag-routes:
	cd applications/knowledge-service && uv run python eval/seed_synthetic_corpus.py
	cd applications/knowledge-service && uv run python eval/run_route_ablation.py --golden eval/golden_queries.labeled.jsonl

# RAG 可持续评测体系（分层，非 hermetic → 不进 make ci，手动/nightly）。
# 依赖真实 Milvus/Neo4j/LLM；缺环境由脚本清晰报错并 return 1（不吞异常、不预填数字）。
# 前置用真实语料自举 golden（gen_golden.py，写 eval/golden_queries.real.jsonl，含难负例打破 Recall 饱和）。

# Phase B：真实语料自举 golden + 多路召回数据源贡献归因（LOO/add-one per-bucket + bootstrap 显著性）
#          + 参数敏感度扫描。需 Milvus(+可选 Neo4j/rerank)。
eval-rag-retrieval:
	cd applications/knowledge-service && uv run python eval/gen_golden.py
	cd applications/knowledge-service && uv run python eval/run_route_ablation.py --golden eval/golden_queries.real.jsonl --with-contrib --param-scan

# Phase C：端到端答案质量（检索层/生成层归因分离，faithfulness/relevance/correctness）。需 LLM。
eval-rag-e2e:
	cd applications/knowledge-service && uv run python eval/run_e2e_eval.py --golden eval/golden_queries.real.jsonl --scorer judge

# Phase D：baseline vs candidate 配对 bootstrap 回归门禁；任一核心指标显著回归即非 0 退出。
# BASELINE 缺省指向已冻结的脱敏锚点（eval/baselines/…，仅含 qid/tags/指标数值、无正文）；
# 只需给 CANDIDATE（改动后新跑的 run）。要临时对比两个 run 也可显式传 BASELINE 覆盖。
# 用法：CANDIDATE=eval/runs/<tsB_hashB> make eval-rag-gate
#       [BASELINE=eval/runs/<tsA_hashA>] 覆盖默认锚点
BASELINE ?= eval/baselines/e2e_post_sparse_fix_2026-09-29
eval-rag-gate:
	@test -n "$(CANDIDATE)" || { echo "用法: CANDIDATE=<runB> [BASELINE=<runA>] make eval-rag-gate（BASELINE 缺省=已冻结锚点）"; exit 2; }
	cd applications/knowledge-service && uv run python eval/compare_runs.py --baseline "$(BASELINE)" --candidate "$(CANDIDATE)" --fail-on-regression

# 把一次已验证的 e2e run 冻结为脱敏回归基准锚点（写入 eval/baselines/<LABEL>/，剥正文、可入库）。
# 确认某次改动为净提升后 re-freeze，作为后续回归对比的新基准。
# 用法：RUN=eval/runs/<ts_hash> LABEL=e2e_<主题>_<日期> make eval-rag-baseline
eval-rag-baseline:
	@test -n "$(RUN)" -a -n "$(LABEL)" || { echo "用法: RUN=<run目录> LABEL=<基准名> make eval-rag-baseline"; exit 2; }
	cd applications/knowledge-service && uv run python eval/make_baseline.py --run "$(RUN)" --label "$(LABEL)"

# Phase C2：把待人工标注的 adjudication_template.jsonl 渲染成离线单文件标注页（录入辅助）。
# 页面逐条卡片呈现 query/context/answer/reference + 两组 0/1/2 单选，自动存 localStorage。
# 产物含语料明文→不入库（见 .gitignore）；只做录入辅助，金标准判断仍由人给出。
# 用法：make eval-rag-meta-ui  后双击 applications/knowledge-service/eval/adjudication_ui.html；
#       标完点「导出 adjudication.jsonl」存回 eval/，再跑：
#       cd applications/knowledge-service && uv run python eval/meta_eval_judge.py --adjudication eval/adjudication.jsonl --candidates self
eval-rag-meta-ui:
	cd applications/knowledge-service && uv run python eval/make_adjudication_ui.py

# CI 串联：lock 校验 + lint + 单测 + 评测门禁；任一失败即中断。
ci: lint test eval
	uv lock --check

# TB-7 端到端冒烟：需本机 Docker 守护进程可用。启动 pgvector + agent-platform，
# 等待两服务 healthcheck 变 healthy，再探测 /health 返回，最后清理。
# 无 Docker 的环境用 `uv run python scripts/smoke_memory.py` 做等价内存模式预热冒烟。
# 若本机 8000 被其他服务占用，用 `HOST_PORT=18000 make compose-smoke` 临时切换宿主端口
# （探测走容器内 127.0.0.1:8000，与宿主端口无关，故切换不影响冒烟语义）。
compose-smoke:
	docker compose up -d --build --wait
	@echo "== agent-platform /health =="; docker compose exec -T agent-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
	docker compose down -v
