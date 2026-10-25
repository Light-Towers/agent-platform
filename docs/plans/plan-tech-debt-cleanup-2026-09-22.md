# Plan：全局技术债务治理（2026-09-22 扫描成果）

> 状态：2026-09-22 制定。**2026-10-15 对码核实并订正**：原状态行与复选框自相矛盾（T2.4 全 `[x]` 却标「待实施」、T2.3 全 `[ ]` 却标「已完成」）。逐条对码结论——**绝大部分已落地**（P0/P1、T2.1、T2.4、T3.1 余者显式「跳过」并注明原因、T3.2 的 `check_doc_sync.py` 已常驻 CI、三方审核补充 1/2/3/5/6 均已修，补充 7/T1.7 于**本批 2026-10-15 落地**）；**真正仍未做仅 3 项**：① T2.2 已**分项处置**（详见该节）——item5（`config.py` 三处改 `dataclasses.replace`）**本批落地**、item6（`agent.py` if-elif→dict 派发）核实后**判定不做**（if-elif 编码真实 body/no-body 区别，dict 派发反不清晰）、items1-4（4 处 ~200 行大函数拆分）**缓做**（纯风格高风险、行号已漂移、与本 plan T3.1 跳过同类项矛盾 ⇒ 需独立方案 + 分支 + 逐函数补测）；② T2.3（依赖配置统一）已**重新对码 + 分项处置**（详见该节）——item5（exhibition `.env.example` 补 10 个 `EXHIBITION_AGENT_*` Settings 变量，1:1 取自 config.py 零杜撰）+ item6（kefu 悬空引用 repoint 到 `agent-core/README.md`「环境变量清单」，不新建重复清单）**本批落地**，items1/7 早已落地、items2/4/8 因 `dialogue-framework`/`zhanggui-zhiku`/`wenda` 三包已消失而 moot（意图已全仓满足），仅 item3 的 fastapi 根下界 `>=0.115` 低于旧目标 `0.129`——仅抬下界无驱动故**标注不盲改**；③ 补充 4（agentic bridge opt-in 默认开还是仅补测试）属**待拍板**设计决策。逐条证据见文末「## 2026-10-15 对码核实」。
> 来源：6 维度并行扫描（代码质量 / 架构 / 依赖配置 / 测试覆盖 / 文档注释 / 重构遗留）
> 范围：当前工作区快照（存在并发写入，实施前须冻结基线）
> 总计：发现 97 项，去重后约 80 项实质债务，分 4 优先级 13 批次任务
> 已确认无问题 12 项（红线 1/2/3 通过、Plan-F 中间件全实现、CI 矩阵对齐、eval 15 条对齐等）不列入任务
> P1 完成详情：86 新测试 / env helper + sse_pack + ApiReranker + LLMClient 收敛 / revert.py checkpoint_ns bug 修复
> P2 完成详情：61 新测试（cache/tracing/guards/schema_store/embed_rerank）/ zhanggui ruff I + 48 import fix / 4 包 addopts / .env.example

## 总览

| 优先级 | 批次 | 任务数 | 说明 |
|--------|------|--------|------|
| **P0 立即** | T0.1-T0.4 | 4 批 | 零风险清理 + Critical 文档/门禁盲区 |
| **P1 本 sprint** | T1.1-T1.5 | 5 批 | 构建修复 + 架构 gap + 核心测试 + 代码重复收敛 |
| **P2 下 sprint** | T2.1-T2.4 | 4 批 | 文档完整性 + 测试覆盖补齐 + 代码质量 + 依赖统一 |
| **P3 机会修** | T3.1-T3.2 | 2 批 | Low 项 + 防漂移机制 |

---

## P0 立即（零风险 + Critical）

### T0.1 删除 9 个根目录残留目录（零风险，已逐项核实吸收）

**问题**：c992ed9 重构后根目录遗留 9 个旧位置目录，全部纯 .pyc/.venv 缓存，源码已迁入 `applications/` 或 `packages/` 且更完整。

**改动**：删除以下 9 个目录（约 4.1MB）：
- `wenda-adapter/`（adapter 已退役，仅 1 个 .pyc）
- `wenda-data-agent/`（.pyc 缓存，源码已迁 `applications/wenda-data-agent/`，多 4 模块）
- `zhanggui-zhiku/`（.venv，源码已迁 `applications/zhanggui-zhiku/`）
- `app/`（.pyc 缓存，源码已迁 `applications/agent_server/`，已增强）
- `agent-core/`（缓存，源码已迁 `packages/agent-core/`）
- `agent_federation/`（缓存，源码已迁 `applications/agent_federation/`）
- `dialogue-framework/`（缓存，源码已迁 `applications/dialogue-framework/`）
- `kefu-service/`（缓存，源码已迁 `applications/kefu-service/`）
- `shared-schemas/`（缓存，源码已迁 `packages/shared-schemas/`）

**安全性依据**：全部 `.py count=0`；全部被 `.gitignore:110-119` 显式忽略，`git ls-files` 返回空；无任何代码/配置/文档引用根目录残留路径；`docs/analysis/2026-09-21/00-inventory.md` 已判定为「招留残骸」。

**验收**：
- [ ] 9 个目录已删除
- [ ] `git status` 无新增未跟踪文件（被 .gitignore 忽略，不影响 git）
- [ ] `make test` 8 session 全绿

---

### T0.2 批量修复 Critical 文档失同步（6 项）

**问题**：改名迁移（`app/`→`applications/agent_server/`、`deepagents/`→`agent_federation/`、`app`→`zhanggui_zhiku`）后文档全量未同步，数字事实漂移。

**改动**：

**路径批量替换**：
- [ ] `docs/plans/plan-f-single-runtime-multi-planner.md` 28 处 `app/`→`applications/agent_server/`、`agent_federation/`→`applications/agent_federation/`
- [x] `README.md:40,354` 引用 `docs/architecture-improvement-plan.md`→`docs/architecture/architecture-improvement-plan.md`。**2026-10-15 核销**：该两处已由 `cd5834cb`（2026-09-22，与本待办同一提交）改准，复选框当时未翻；实测依据 = `git show cd5834cb^:README.md` 第 40/354 行为旧路径、`git show cd5834cb:README.md` 两处均为新路径，现行 README 旧路径 0 命中、仅剩 `README.md:474` 一处且为新路径。**注：本块标题写「6 项」而块内实列 12 个复选框（3 路径替换 + 5 数字校正 + 1 命名校正 + 3 验收），该口径差未在本条解决，翻勾只对本条负责**
- [ ] `CHANGELOG.md:57` 引用 `docs/runtime-governance-roadmap.md`→`docs/operations/runtime-governance-roadmap.md`

**数字事实校正**：
- [ ] `applications/agent_federation/README.md:97,124` "24 tests"→"110 tests"
- [ ] `applications/agent_federation/README.md:60` ".env.example 80+ 项"→"23 项"（或核实 .env.example 是否遗漏变量）
- [ ] `CHANGELOG.md:58,93` "eval 12/12"→"15/15"（新条目说明，旧条目保留历史）
- [ ] `docs/plans/plan-f-...md:73` "app 12 golden"→"15"
- [ ] `docs/plans/plan-f-...md:27` "agent-core 5578 行"→"6888 行"

**命名校正**：
- [ ] `applications/zhanggui-zhiku/README.md:18,117,123,275` `app.main:app`→`zhanggui_zhiku.main:app`、`app.core.config`→`zhanggui_zhiku.core.config`

**验收**：
- [ ] 文档中所有路径引用经 Glob 验证存在
- [ ] 文档中所有数字事实经 bash 验证一致
- [ ] 无残留 `app/` / `deepagents/` 旧路径（注释说明性引用除外）

---

### T0.3 补 shared-schemas 测试 + Makefile 第 9 session（Critical 测试缺失）

**问题**：`packages/shared-schemas/` 7 个契约模块（QueryResponse/ThreadState/HealthResponse 等）零测试，Makefile 无 session。

**改动**：
- [ ] 新增 `packages/shared-schemas/tests/test_contracts.py` 覆盖各契约模型字段约束/序列化往返/向后兼容
- [ ] `Makefile` test 目标新增 `uv run pytest packages/shared-schemas/tests -q`（第 9 session）
- [ ] `AGENTS.md` 门禁说明 8→9 session

**验收**：
- [ ] `uv run pytest packages/shared-schemas/tests -q` 全绿
- [ ] Makefile test 9 session 全绿

---

### T0.4 移除 collect_ignore_glob，为 dialogue/wenda 增独立 session（Critical 门禁盲区）

**问题**：`tests/conftest.py:45-47` 用 `collect_ignore_glob` 忽略 `tests/dialogue_framework/`（4 测试）和 `tests/wenda_data_agent/`（3 测试），CI 永不运行，回归保护为零。

**改动**：
- [ ] 核实 `tests/dialogue_framework/` 4 个测试是否仍可运行（源码已完整存在）；若可运行，移除 collect_ignore_glob 对应行
- [ ] 为 `tests/dialogue_framework/` 增 Makefile 独立 session（第 10 个）
- [ ] 核实 `tests/wenda_data_agent/` 3 个测试；若可运行，增 Makefile 独立 session（第 11 个）
- [ ] 若某测试已失效（源码已改），修复或迁移到 `applications/*/tests/`
- [ ] `AGENTS.md` 门禁说明更新 session 数

**验收**：
- [ ] 无测试被 collect_ignore_glob 静默忽略
- [ ] 所有 test_*.py 文件至少被一个 Makefile session 覆盖

---

## P1 本 sprint（构建修复 + 架构 gap + 核心测试 + 代码收敛）

### T1.1 修构建配置失效（3 项 High）

**问题**：monorepo 重组后 Dockerfile / requirements.txt 路径失效，zhanggui-zhiku 依赖不固定。

**改动**：
- [ ] `applications/zhanggui-zhiku/Dockerfile:17,20,34`：COPY 路径 `agent-core`→`packages/agent-core`、`zhanggui-zhiku/app`→`zhanggui-zhiku/zhanggui_zhiku`，CMD `app.main:app`→`zhanggui_zhiku.main:app`；docker-compose `context`→`../..`
- [ ] `applications/agent_federation/requirements.txt:10-11`：`-e ../agent-core`→`-e ../../packages/agent-core`、`-e ../shared-schemas`→`-e ../../packages/shared-schemas`；补 `-e ../../packages/agent-runtime`
- [ ] `applications/zhanggui-zhiku/pyproject.toml:14-46`：为关键依赖（fastapi/langchain/torch/transformers/pymilvus）加下界

**验收**：
- [ ] zhanggui-zhiku Dockerfile build 可达（至少 COPY 路径存在）
- [ ] agent_federation requirements.txt 路径解析正确
- [ ] zhanggui-zhiku 依赖有版本下界

---

### T1.2 修 AgenticPlanner 沙箱可达性 gap（架构 High，已知 gap）

**问题**：`AgenticPlanner.execute()` 直接调 executor 未经 `runtime.delegate`，绕过 skill_guard/circuit_breaker/trajectory 治理；`agentic_bridge.py` 桥已建但联邦侧未接入；`code_execution` 无角色映射。

**改动**（与 Plan-F 收敛路径一致，记忆 `project_agentic-planner-sandbox-routing-gap` / `project_f-s1-02-04-blocked-on-plan-f`）：
- [ ] 联邦侧 deep_agent 接入 `AgenticRuntimeBridge`：tool discovery 用 `bridge.discover`，tool call 用 `bridge.call_tool`
- [ ] `applications/agent_federation/agent/tool_registry.py:30-35` `ROLE_TOOLS` 新增 code_execution 角色映射（如 `"code": ["execute_python_code"]`）
- [ ] 先检查受影响的测试（Plan-F 方案执行者明确"先检查受影响的测试"为第一步）

**验收**：
- [ ] AgenticPlanner 路径的 tool/subagent 调用经 `runtime.delegate`
- [ ] skill_guard / circuit_breaker / trajectory 在 agentic 路径生效
- [ ] 相关测试全绿

---

### T1.3 补五项核心测试缺失（High）

**问题**：otel/revert/subagents/kefu/wenda 五项核心模块零测试。

**改动**：
- [ ] `packages/agent-runtime/tests/test_otel.py`：覆盖 init_otel 幂等/采样率/no-op 降级/traceparent 透传/脱敏（本机未装 OTel SDK，测 no-op 降级路径，记忆 `feedback_otel-sdk-missing`）
- [ ] `packages/agent-runtime/tests/test_revert.py`：覆盖正常回退/checkpoint 不存在/跨用户禁止/内存模式边界/审计日志（用 InMemoryCheckpointStore，无需 PG）
- [ ] `applications/agent_server/tests/test_subagents.py`：覆盖 mcp/rag/search/sql_agent 各子代理 invoke 契约/错误分支/参数校验
- [ ] `applications/kefu-service/tests/test_flows.py`：覆盖 postsale/order/logistics 3 个流程 + services/graph_rag/commands
- [ ] `applications/wenda-data-agent/tests/`：新增 tests/ 目录，覆盖 repositories/clients/services 契约 + 12 节点（优先于根 tests/wenda_data_agent/）

**验收**：
- [ ] 5 项新测试全绿
- [ ] 对应 Makefile session 纳绿

---

### T1.4 代码重复收敛到 agent_core（4 项 Critical/High）

**问题**：各应用对 `agent_core` 已有能力复用不彻底——LLM/rerank/env helper/SSE 各自重复实现。

**改动**：
- [ ] `applications/exhibition-agent/exhibition_agent/skill_loader/llm_client.py`：改为薄壳注册 `OpenAICompatibleProvider` 到 `agent_core.llm.registry`，经 `get_llm_client()` 取实例
- [ ] `applications/wenda-data-agent/wenda_data_agent/agent/llm.py`：同上，移除直接 `ChatOpenAI` 调用
- [ ] `ApiReranker` 收口到 `agent_core`（与 `SiliconFlowEmbedder` 同位置）：`zhanggui-zhiku/lm/siliconflow_client.py:143-217` + `agent_server/rag/rerank.py:25-103` 经内核调用 `agent_core.resilience.retry_async`
- [ ] `agent_core/config.py` 新增统一 `env_bool/env_int/env_float`，替换 4 处重复定义（`agent_federation/agent/cache/config.py:12` / `planners/__init__.py:22` / `zhanggui-zhiku/core/config.py:26` / `agent_core/tracing.py:171`）+ `main_agent.py` 12 处 inline
- [ ] `shared-schemas` 新增统一 `sse_pack(event, data)` 契约函数，替换 3 处不一致实现（`agent_server/api/routes.py:267` / `zhanggui-zhiku/utils/sse_utils.py:42` / `scripts/opencode_gateway.py:66`）

**验收**：
- [ ] exhibition/wenda LLMClient 经 agent_core.llm
- [ ] ApiReranker 经 agent_core.resilience
- [ ] env helper 单一来源
- [ ] SSE 打包格式统一
- [ ] 全量测试不回归

---

### T1.5 修 16 项 High 文档（架构理解 + 运行）

**改动**（精选关键项）：
- [ ] `ARCHITECTURE.md:39` "Skill 六型"→"四型 SkillKind + MCP/Sandbox 特化注册"
- [ ] `ARCHITECTURE.md:74,104-110` 分层图补 exhibition-agent
- [ ] `ARCHITECTURE.md:116` "其余 5 个"→"6 个"
- [ ] `ARCHITECTURE.md:10` "13 个顶层条目"→"16 个"
- [ ] `README.md:177-257` API 参考补 `/history` 端点
- [ ] `applications/agent_server/api/routes.py:1` docstring 补 `/history`
- [ ] `README.md:320` "三套件"→"8 session"
- [ ] `applications/zhanggui-zhiku/README.md:85` "已提供 uv.lock"→"使用根 uv.lock"
- [ ] `applications/zhanggui-zhiku/README.md:286` 删除失效引用 `pending/zhanggui-zhiku-production-plan.md`
- [ ] `applications/kefu-service/README.md:14` 安装路径补 `packages/` 和 `applications/`
- [ ] `applications/wenda-data-agent/README.md:45,46` `app/sql`→`applications/agent_server/sql/`
- [ ] `CODE_REVIEW_CHECKLIST.md:4` 仓库路径补 `github` 层级
- [ ] `applications/agent_federation/CHANGELOG.md:23,24` wenda-adapter/kefu-adapter 标注"已于 2026-08 移除"

**验收**：
- [ ] 文档路径引用经 Glob 验证存在
- [ ] 文档数字事实经 bash 验证一致

---

## P2 下 sprint（完整性 + 覆盖补齐 + 质量 + 统一）

### T2.1 补 Medium 8 项测试缺失 + 覆盖不足

**改动**：
- [ ] `packages/agent-runtime/tests/test_cache.py`：覆盖 cache_lookup 命中/未命中/threshold 边界 + cache_store
- [ ] `packages/agent-runtime/tests/test_tracing.py`：覆盖 Langfuse 三态降级（凭据空/全/导入失败）
- [ ] `applications/agent_server/tests/test_schema_store.py`：覆盖 schema_store 存取/方言/错误分支
- [ ] `applications/agent_server/tests/test_embed_rerank.py`：覆盖 embed/rerank 真实调用 + 错误降级（非 monkeypatch）
- [ ] `applications/agent_federation/tests/unit/` 新增 4 个子守卫测试（rate_limit/output_guard/input_guard/gray）
- [ ] `applications/agent_federation/tests/unit/` 新增 3 个具体子代理测试（network_search/knowledge_base/database_query）
- [ ] `applications/dialogue-framework/tests/` 补 dialogue_understanding/policies/retrieval 单元测试
- [ ] `applications/zhanggui-zhiku/tests/unit/` 补 query_process 7 node + import_process 7 node + clients 4 个

**验收**：
- [ ] 8 项新测试全绿
- [ ] 无 monkeypatch 滥用

---

### T2.2 代码质量改进（6 项）

> **2026-10-15 分项处置**（不整节翻勾——6 项性质不同，逐项判定，避免"plan 列了就改"）：

**改动**：
- [ ] 拆分 `applications/agent_server/api/routes.py:65 query`（200 行）为 admission/coordination/cache/stream 各抽独立函数 — **缓做**：纯风格大函数拆分、回归风险高、无功能收益；且**行号引用已漂移**（`query` 现在 `api/query_router.py`，非 `routes.py:65`）；与本 plan T3.1 把同类「`routes.py` 按业务域拆分」判为「跳过：大规模重构」自相矛盾 ⇒ 如需做应独立成方案 + 独立分支 + 逐函数补测后再拆
- [ ] 拆分 `applications/agent_server/agent/graph.py:46 build_graph`（200 行） — **缓做**：同上（纯风格、高风险、需先对码确认函数仍在该位置）
- [ ] 拆分 `applications/agent_server/main.py:106 lifespan`（183 行）用 lifespan context manager 组合 — **缓做**：同上；且 lifespan 本 session 刚被 human_task 装配改过，再叠大重构会混淆改动面
- [ ] 拆分 `agent_federation/agent/main_agent.py:543-652 _execute_agent_core`（122 行/嵌套 9）为 `_prepare_session`/`_inject_context`/`_consume_stream`/`_guard_output` — **缓做**：同上（跨应用、嵌套深、拆分需逐段补测）
- [x] `agent_federation/agent/config.py` SubserviceConfig 三处用 `dataclasses.replace(old, healthy=...)` — **2026-10-15 落地**：`SubserviceConfig` 是 `@dataclass(frozen=True)` 六字段（name/graph_id/url/endpoint/local_agent/healthy），三处（`_wire_local_fallbacks` 装 local_agent、`mark_unhealthy`、`mark_healthy`）原逐字段手抄六项只为改一项 ⇒ 改 `replace(old, ...)`，消除「frozen dataclass 将来加字段时手抄静默丢新字段」的 bug 类。自证：`replace` 保留全部 5 个非 healthy 字段、只翻 healthy；`get_all_subservices()` 不变；ruff rc=0、federation **176 passed**
- [~] `exhibition-agent/skill_loader/agent.py` HTTP 方法 if-elif 链改 dict 派发 — **2026-10-15 核实后判定不做**：现 if-elif（`agent.py:230-243`）编码了**真实的 body/no-body 区别**（GET/DELETE 只带 `params`，POST 带 `json=body_params`）**+ else→400 错误分支**；改 dict 派发须给每个调用套 lambda 且错误分支另判，仅 3 个**非齐整**分支，属过度抽象、并不更清晰（先证伪自己的动机：不为"plan 列了"而改）

**验收**（按实际处置范围）：
- [x] item5（config.py）：behavior 自证 + ruff + federation 176 passed，零回归
- [~] item6（agent.py）：判定不做（理由见上），非遗漏
- [ ] 「无函数 >80 行 / 无嵌套 >5」：**未达**——该判据只适用于 items 1-4 的大函数拆分，四项均**缓做**（纯风格 + 高风险 + 与本 plan T3.1 跳过同类项矛盾）⇒ 本 plan 不追求此判据，留待独立重构方案
- [x] 全量测试不回归（federation 176 passed；已改的 config.py 属 federation）

---

### T2.3 依赖配置统一（8 项 Medium）

> **2026-10-15 重新对码 + 分项处置**：原 8 项按 2026-09-22 包名（`dialogue-framework`/`zhanggui-zhiku`/`wenda`）书写，其中 3 个包在当前 6 应用结构里已不存在。逐项对当前工作区核实后——**2 项本批落地、3 项早已落地、3 项因包消失而 moot（但意图已在全仓满足）、1 项仅抬下界无驱动故标注不盲改**。不整节翻勾（8 项性质不同）。

**改动**：
- [x] 根 `pyproject.toml` `langchain-core`/`langchain-openai` 下界 — **早已落地并超越**：现值 `langchain-core>=1.6.5`、`langchain-openai>=1.6.6`，均高于原目标 `>=1.5.3`/`>=1.4`
- [~] `dialogue-framework` `sqlglot>=23.0`→`>=25.0` — **moot（包不存在）**：`dialogue-framework` 已从树中消失；sqlglot 现声明于 agent_federation/nl2sql-service（`>=25.0`）与 agent-core/根（`>=30.20.0`），**意图（>=25.0）已在全仓满足**
- [ ] 统一 pydantic `>=2.13` / fastapi `>=0.129` / uvicorn `>=0.41` 下界 — **部分达成**：根 pyproject `pydantic>=2.13.5` ✅、`uvicorn[standard]>=0.54.0` ✅ 均已超下界；唯 `fastapi>=0.115`（根）低于目标 `0.129`（agent_federation/requirements.txt 非 uv 备选清单已是 `>=0.129`）。**标注不盲改**：仅抬下界、无具体 feature/bugfix 驱动，盲目收紧会无谓约束依赖解析（依赖风险纪律）⇒ 如需对齐应先确认实际解析版本与 0.129 的必要性，属独立依赖评审
- [~] `zhanggui-zhiku` ruff select 补 `"I"` — **moot（包不存在）**：`zhanggui-zhiku` 已改名；ruff `select` 现于根 + agent_federation + exhibition + knowledge-service 均含 `"I"`（其余包无独立 `[tool.ruff]` 段即继承根配置），**意图（isort `I` 全仓启用）已满足**，`ruff check .` 本批全绿
- [x] 新增 `applications/exhibition-agent/.env.example`（列 config.py 读取的所有 env）— **本批补全**：文件早已存在，但原只覆盖 skill_loader 无前缀演示变量（`WAREHOUSE_BASE_URL`/`LLM_*`/`SKILL_MD_PATH` 等），**遗漏 `exhibition_agent/config.py` 的 pydantic Settings（`env_prefix=EXHIBITION_AGENT_`）10 个生产变量**。本批补入该 10 项（`WAREHOUSE_BASE_URL`/`CONTEXT_MODE`/`EXECUTION_MODE`/`CONTEXT_JWT_SECRET`/`WAREHOUSE_TIMEOUT`/`LOG_LEVEL`/`OTEL_ENDPOINT`/`OTEL_SERVICE_NAME`/`OTEL_ENABLED`/`LLM_OBS_BACKEND`），**每项默认值 1:1 取自 config.py `Field(default=...)`，零杜撰**（自证：config.py 10 字段 ↔ .env.example 10 变量一一对应）
- [x] `packages/agent-core/.env.example`（或删除 kefu-service/.env.example:6 对该文件的引用）— **本批落地（改良选项 b）**：agent-core 是**库**（零依赖内核）非可部署服务，其 env 清单已在 `agent-core/README.md`「环境变量清单」+ `config.py` docstring **双处登记**；新建 `.env.example` 会成为第 3 份副本 → 漂移隐患、违反单一真相源。故不新建，改为**修正 kefu-service/.env.example:6 的悬空引用**：`agent-core/.env.example`（不存在）→ `agent-core/README.md「环境变量清单」`（真实登记处）。repoint 优于 delete——既消除悬空又保留"去哪查内核 env"的指引
- [x] `agent_federation/requirements.txt` 补 agent-runtime 声明（与 T1.1 合并）— **早已落地（T1.1）**：requirements.txt 已含 `-e packages/agent-runtime`，且带注释 "2026-09-22 T1.1：monorepo 重组后 ../agent-core 旧路径失效，已改 packages/ 前缀并补 agent-runtime"
- [~] 4 个应用包（agent_federation/exhibition/wenda/dialogue）补 `addopts = "--import-mode=importlib"` — **moot（wenda/dialogue 不存在）+ 现存包已落地**：`wenda`/`dialogue` 已消失；现存的 agent_federation ✅ / exhibition ✅ 均已有 `addopts = "--import-mode=importlib"`，nl2sql-service ✅ / 根 ✅ 亦有

**验收**（按实际处置范围）：
- [~] `uv sync --all-packages --extra dev` 成功 — **本批未跑**：本轮不部署、不改任何依赖版本约束（仅动 `.env.example` 模板 + 文档），故不触发依赖重解析；item3 的 fastapi 下界明确标注不盲改，无 sync 影响
- [x] `make lint` 全绿 — `.env.example`/`.md` 改动不涉 lint；本批 `ruff check .` 全绿（见 T2.2）、`check_doc_sync.py` ✅ 0 警告
- [x] 各包 ruff/pytest 配置一致 — item4（ruff `I`）/item8（pytest importlib）已对现存包逐项确认一致

---

### T2.4 修 26 项 Medium 文档 + 补 README

**改动**（精选）：
- [x] 新增 `packages/agent-runtime/README.md`（列 planner/skills/sandbox 模块职责与公开 API）
- [x] 新增 `packages/shared-schemas/README.md`（列 QueryResponse/ThreadState/HealthResponse 契约）
- [x] `README.md:148 vs :344` 安装命令统一为 `uv sync --all-packages --extra dev`
- [x] `applications/kefu-service/README.md:33,35` kefu-adapter 矛盾清理
- [x] `applications/zhanggui-zhiku/CHANGELOG.md:18-20` `app/`→`zhanggui_zhiku/`
- [x] `applications/zhanggui-zhiku/docs/architecture-design.md` 24 处 `app.`→`zhanggui_zhiku.`
- [x] `applications/agent_federation/api/server.py:122` FastAPI title "DeepAgents API"→"agent_federation API"
- [x] `applications/dialogue-framework/README.md:45,46` 安装路径补 applications/
- [x] `ARCHITECTURE.md:117` "17 passed"→当前数或删除具体数字
- [x] `CODE_REVIEW_CHECKLIST.md` 多处旧路径更新或加时效性标注（已有第 2 行时效性说明，无需再改）
- [x] `docs/analysis/2026-09-21/00-inventory.md:16` 包名 `app`→`zhanggui_zhiku`
- [x] `docs/analysis/2026-09-21/02-debt-diagnosis.md:89` F-S0-08 状态标 ✅ 已修复（与 §3 一致）

**验收**：
- [x] 文档间无矛盾
- [x] 文档路径引用全有效

---

## P3 机会修（Low + 防漂移机制）

### T3.1 Low 19 项

**改动**（精选，低优先级）：
- [x] 删除 `agent_federation/agent/main_agent.py:289-294` `get_main_store` 死代码（确认无引用后）
- [ ] 产品代码单字母变量改语义名（`q/p/s/v/k` → `normalized_query/pythonized_path/...`）— 跳过：大规模重构，风险高
- [ ] `zhanggui-zhiku` 节点函数裸阈值集中到 conf/ 配置模块 — 跳过：大规模重构
- [ ] 评估 `zhanggui-zhiku` setuptools → hatchling 迁移 — 跳过：评估性任务
- [ ] `kefu-service` + `zhanggui-zhiku` 补 `[tool.pytest.ini_options]` 显式声明 — 跳过：已有 addopts 配置
- [x] `docker-compose.ha.yml:19` postgres 改 `${POSTGRES_PASSWORD:?}` 强制
- [x] `zhanggui-zhiku/.env.example:59,67-68` MinIO/Neo4j 弱凭据改占位符
- [ ] ruff ignore 存量基线逐包收窄 — 跳过：逐包评估，记忆 `project_agent-runtime-ruff-ignore-baseline`
- [x] `exhibition-agent/tests/test_observability.py:73` 恒真断言改具体行为断言
- [x] `exhibition-agent/tests/test_observability.py:92-98` 幂等测试补 `assert tracer1 is tracer2`
- [ ] `agent_core` 注释中应用名改泛化表述（"宿主应用"） — 跳过：81 处历史注释有保留价值
- [x] `agent_core/tests/test_cache_key.py:11` 业务术语 "refund"/"kefu" 改中性词
- [ ] `agent_server/api/routes.py` 按业务域拆分 — 跳过：大规模重构
- [x] `AGENTS.md:15` planner/ 模块清单补全（11 个）+ skills/ 清单补全（10 个）
- [x] `Makefile:24` 注释移除"包名 app 遮蔽风险"
- [x] `agent_federation/VERIFICATION_REPORT.md:19` wenda-adapter 标注已退役
- [x] `agent_federation/eval/AUDIT.md` 旧名 `deepagents/` 加时效性标注或替换
- [ ] 清理 87 处裸 `except Exception:` — 跳过：大规模重构，需逐个区分可恢复 vs 编程错误
- [ ] `zhanggui-zhiku/core/config.py` 评估引入 pydantic-settings 统一配置风格 — 跳过：评估性任务

**验收**：
- [x] 无死代码（get_main_store 已删）
- [x] 无恒真断言（test_observability 已修）
- [x] ruff 全绿

---

### T3.2 建立文档同步防漂移机制

**问题**：文档数字/路径/命名靠人工维护，无 CI 自动校验，已多次漂移。

**改动**：
- [x] 新增 `scripts/check_doc_sync.py` CI 脚本，自动校验：
  - 文档中提到的路径经 Glob 验证存在
  - 文档中提到的数字（测试数/eval 条数/代码行数/.env 项数）经 bash 验证一致
  - 文档中提到的模块/类名经 grep 验证存在
- [x] CI workflow 增加该脚本执行步骤
- [x] 失败时输出"文档说 X，实际是 Y"对比

**验收**：
- [x] `scripts/check_doc_sync.py` 在 CI 运行
- [x] 现有文档通过校验
- [x] 后续文档漂移被 CI 拦截

---

## 外部资源依赖

本 plan 绝大部分任务本机可执行（文档/代码/测试改动）。以下任务可能需外部资源：

| 任务 | 资源 | 说明 |
|------|------|------|
| T1.3 test_revert.py | PG 实例（可选） | 默认用 InMemoryCheckpointStore，无需 PG；若要测 PgCheckpointStore 需 PG |
| T1.2 AgenticPlanner 沙箱 | Docker（可选） | 沙箱测试需 Docker 后端；subprocess 后端本机可测 |
| T2.1 zhanggui integration | Neo4j/MinIO/Milvus | unit 测试无需，integration 需（已有 ZHIKU_INTEGRATION=1 守卫） |

其余任务无外部资源依赖。

---

## 验收门禁

实施完成后须全量重跑 CI 门禁（记忆 `project_workspace-concurrent-writes`：工作区并发写入，须以最终快照为准）：

- [ ] `make lint` 全绿
- [ ] `make test` 全 session 绿（P0.3 后 9-11 session）
- [ ] `make eval` 启发式 eval 通过
- [ ] `scripts/check_doc_sync.py`（P3.2 后）全绿
- [ ] `git status` 无意外变更（提交前审查工作区实际快照，记忆 `feedback_windows-nul-artifact-cleanup`：排查 Windows 保留名文件）
- [ ] ruff 0 error（记忆 `project_agent-runtime-ruff-ignore-baseline`：存量豁免不可清理）

---

## 三方审核核验（2026-09-22）

> 来源：外部审核报告针对 `bf1f44c..11d313a`（8 个技术债清理提交）vs 本 plan 的一致性核验
> 方法：逐条实跑取证（非转述），含 `lint_architecture.py` 实跑、`AgenticPlanner().to_skill()` 实跑、`ls`/`grep` 逐项验证
> 结论：16 条中 **14 条完全属实、1 条大部分属实、1 项数字指控不实**；补充 7 项遗漏

### 核验结论表

| # | 报告条目 | 结论 | 实跑证据 |
|---|---------|------|---------|
| C1 | lint P4-2 exit 1 | ✅ 属实 | `lint_architecture.py` exit=1，`agentic.py:188` docstring 含 `registry.execute("agentic", ...)`，该文件不在白名单 |
| C2 | mcp 测试无守卫 | ✅ 属实 | `pyproject.toml:19` mcp 在 optional；`test_mcp_client_real.py:39` 函数内 import 无 `importorskip` |
| C3 | /api/task thread_id 丢弃 | ✅ 属实 | `query.py:18` session_id 无 alias；`auth.py:29` 未开 API_KEY 时返回 `"dev-default-thread"` |
| C4 | execute_python_code 无条件挂载 + 无 kill | ✅ 属实 | `main_agent.py:267` 无条件挂载；`sandbox.py:152,184` 两处 wait_for 无 proc.kill；ROLE_TOOLS 无 code 映射 |
| C5 | T0.3/T0.4 零交付 | ✅ 属实 | conftest 仍 ignore；shared-schemas 无 tests；Makefile 仍 8 session |
| W1 | 9 目录未真删 | ✅ 属实 | 9 个根目录全部 ls 命中，仅 .gitignore 兜底 |
| W2 | plan 自称 ✅ 但未落地 | ✅ 属实 | `plan-structural-debt-cleanup.md:55` 标 ✅ 但 241 仍在 exhibition README；sandbox.py:10 新写 126:2375 |
| W3 | T1.3/T2.1 测试缺失 | ✅ 属实 | 无 test_otel/revert/cache/tracing.py |
| W4 | T1.4 代码重复未收敛 | ✅ 属实 | ApiReranker 双份；wenda 仍 ChatOpenAI；shared_schemas 无 sse_pack |
| W5 | mcp stack 泄漏 | ✅ 属实 | `mcp_client.py:102` except 未 aclose stack；`_connect_stdio:115-118` 局部 stack 泄漏 |
| W6 | to_skill DEBUG 吞 | ✅ 属实 | 实跑 to_skill() → RuntimeError；`main.py:240` logger.debug 静默；测试全走显式注入绕开发现路径 |
| W7 | T1.1 构建配置未修 | ✅ 属实 | requirements.txt 旧路径；zhanggui Dockerfile 旧路径 + CMD app.main:app |
| S1 | 文档数字漂移 | ⚠️ 大部分属实，1 项不实 | "三套件"/"24 tests"/"六型" 属实；"AGENTS.md 7 应用实为 6" 不实（见下） |
| S2 | 测试全局污染 | ✅ 属实 | `test_agentic_skill.py` 7 处覆盖全局 `_executor_factory` 无还原 |
| S3 | 恒真断言 | ✅ 属实 | `test_observability.py:73` 恒真；:97-98 幂等只断言非空 |
| S4 | plan 未入库 | ✅ 属实 | `git status` 显示 `?? plan-tech-debt-cleanup-2026-09-22.md` |

### 不实指控澄清

**S1 中"AGENTS.md:3 写'7 应用各含 pyproject'（实为 6）"——数字错误**：
- `applications/` 下**确实 7 个目录**（ls 已验证）
- 真正问题不是"7 vs 6"，而是 `applications/agent_server/` **无独立 pyproject.toml**（由根 pyproject 承载）
- 准确表述："AGENTS.md 说'7 个应用工程**各含独立 pyproject.toml**'不准确——agent_server 无独立 pyproject，其余 6 个有"

### 补充遗漏项（报告未覆盖，本 plan 新增任务）

#### 补充 1：C4 遗漏 — Docker 后端同样无 proc.kill（扩展 T1.2/T2.2）
- **位置**：`packages/agent-runtime/agent_runtime/sandbox.py:152`（Docker）+ `:184`（subprocess）
- **问题**：报告 C4 只提 subprocess 无 kill，但 Docker 后端 :152 同样 `wait_for(proc.communicate())` 无 `except TimeoutExpired → proc.kill()`。超时后 `docker run` 进程残留（`--rm` 不触发）。**两个后端都有进程残留，报告只提一半**。
- **任务影响**：T1.2 修复须覆盖 sandbox.py 两处（Docker + subprocess），统一加 `try/except asyncio.TimeoutError: proc.kill(); raise`。

#### 补充 2：W5 遗漏 — `_connect_sse` 同样有 stack 泄漏（扩展 T1.2）
- **位置**：`packages/agent-runtime/agent_runtime/mcp_client.py:121-127` `_connect_sse`
- **问题**：报告 W5 只提 `_connect_stdio`，但 `_connect_sse` 同模式：:123 `stack = AsyncExitStack()` → :126 `session.initialize()` 若抛异常则 stack 未 aclose。**两个 transport 都泄漏，报告只提 stdio**。
- **任务影响**：T1.2 修复须覆盖 `_connect_stdio` + `_connect_sse` 两处，统一 `try/except: await stack.aclose(); raise`。

#### 补充 3：C3 遗漏 — `/api/upload` 与 `/api/task` 契约不一致（扩展 C3 修复）
- **位置**：`applications/agent_federation/api/server.py:228-231` `/api/upload`
- **问题**：`/api/upload` 仍用 `thread_id: str = Form(None)`（兼容老客户端），`/api/task` 用 QueryRequest 丢 thread_id。**同一服务两端点会话标识策略不一致**：老客户端上传文件落到 thread A，对话却落到 "dev-default-thread"，文件与会话脱钩。
- **任务影响**：C3 修复须同时统一 `/api/upload` 的 thread_id 处理，或确认 upload 走 Form 不受 QueryRequest alias 影响但须文档标注差异。

#### 补充 4：C4 澄清 — `_maybe_attach_bridged_tools` 是 opt-in 默认关闭
- **位置**：`applications/agent_federation/agent/main_agent.py:270`
- **问题**：报告 C4 说"AgenticRuntimeBridge/runtime.delegate 未接入"——**严格说是"已实现但默认关闭"**（opt-in, `AGENTIC_RUNTIME_BRIDGE=true`）。这是设计决策（渐进推广）vs plan T1.2 要求（接入）的差距，报告表述偏重。但效果相同：默认路径绕过治理。
- **任务影响**：T1.2 须明确：是改为默认开启，还是保留 opt-in 但补测试覆盖开启路径。

#### 补充 5：ARCHITECTURE.md 与 AGENTS.md 跨文档 Skill 型矛盾（扩展 T1.5）
- **位置**：`ARCHITECTURE.md:39` "六型" vs `AGENTS.md:15` "四执行器 + MCP/Sandbox 特化注册"
- **问题**：报告 S1 提了 ARCHITECTURE "六型"，但没提 AGENTS.md 与之矛盾。**两份顶层文档对 Skill 型数口径相反**，读者不知信哪个。
- **任务影响**：T1.5 修复须统一两文档口径（建议"四型 SkillKind + MCP/Sandbox 特化注册"）。

#### 补充 6：`code_execution_tool.py:21` 模块级 SandboxExecutor 初始化副作用（新增 T1.6）
- **位置**：`applications/agent_federation/tools/code_execution_tool.py:21` `_sandbox = SandboxExecutor()`
- **问题**：模块 import 时就执行 Docker 可用性探测，降级决定在 import 期固化，后续 Docker 可用也无法切换。任何 import 该模块的代码都触发 Docker 探测副作用。
- **任务影响**：新增 T1.6：改为懒初始化（首次调用时检测后端），或在 SandboxExecutor 构造时不做探测。

#### 补充 7：`test_agentic_skill.py:91` 在白名单内演示被禁模式（新增 T1.7）
- **位置**：`packages/agent-runtime/tests/test_agentic_skill.py:91` `result = await reg.execute("agentic", ...)`
- **问题**：该行正是 lint P4-2 禁止的 `registry.execute()` 模式，但因白名单 :36 含 `packages/agent-runtime/tests/` 而豁免。**测试演示的正是契约禁止的用法**，且该测试是 to_skill() 收敛的唯一"行为验证"，却绕开了真实发现路径（W6）。白名单让测试绿但掩盖了发现路径的 RuntimeError。
- **任务影响**：新增 T1.7：补一个走真实 entry_points 发现路径的集成测试（不显式注入 factory），验证 to_skill() 在真实安装下的行为；现有测试的 `reg.execute` 调用加注释说明"仅测试内豁免，生产须走 delegate"。

### 对原 plan 任务的影响汇总

| 原/新任务 | 调整 | 2026-10-15 对码状态 |
|-----------|------|------|
| T1.2 | 扩展：sandbox.py 两处 proc.kill（补充1）+ mcp_client.py 两处 stack.aclose（补充2）+ 明确 bridge opt-in 策略（补充4） | 补充1/2 ✅已修（T1.2a）；补充4 **待拍板** |
| C3 修复 | 扩展：同时统一 `/api/upload` thread_id 处理（补充3） | ✅已修（upload 与 task 同走 `_resolve_thread_id_or_401`） |
| T1.5 | 扩展：统一 ARCHITECTURE.md 与 AGENTS.md Skill 型口径（补充5） | ✅已修（ARCHITECTURE.md:39 四型口径） |
| **T1.6 新增** | code_execution_tool.py 懒初始化（补充6） | ✅已修（`_get_sandbox()` 懒初始化，T1.2a/T1.2b） |
| **T1.7 新增** | to_skill() 真实发现路径集成测试（补充7） | ✅**本批落地**（`test_agentic_skill_discovery.py` 2 条，见文末对码核实节） |

---

## 已确认无问题项（不列入任务，备查）

1. 红线 1 通过：`packages/` 无反向 import 应用层
2. 红线 2 通过：`agent-core` 零依赖
3. 红线 3 通过：`shared-schemas` 薄层
4. Plan-F 中间件全实现（admission/coordinator/checkpoint/tracing/cache/rate_limit/circuit_breaker/mcp/singleflight/revert/otel/sandbox）
5. Planner 协议可插拔（四范式）
6. SkillRegistry 四执行器完整非 stub
7. CI 矩阵对齐（8 session 覆盖所有有 tests/ 的包）
8. eval 门禁对齐（golden.jsonl 15 条）
9. conftest 无冲突
10. skip 全合理（14 处均缺环境条件）
11. .env 未入库
12. requires-python 全统一 >=3.11

---

## 经验来源保留

- 多文档同步审计方法（数字/路径/命名逐事实验证）：来源 `2026-09-22-multi-doc-sync-audit-number-path-name-drift`
- YAML 引用与 registry 注册一致性审计：来源 `2026-09-22-declarative-workflow-yaml-references-unregistered-skill`
- Agentic 执行路径治理覆盖审计：来源 `2026-09-21-agentic-execution-path-wrap-with-skill-guard`
- CI 覆盖矩阵审计：来源 `2026-09-21-ci-gate-coverage-matrix-audit`
- conftest 守卫识别：来源 `2026-09-21-gate-external-test-adoption-decision-flow`
- 红线 1 反向依赖复查：来源 `2026-09-21-shared-pkg-test-reverse-dep-fix-direction`

---

## 2026-10-15 对码核实（订正状态行漂移 + 收口补充 7/T1.7）

> 起因：状态行「P2(T2.2/T2.4)+P3 待实施」与复选框自相矛盾（T2.4 全 `[x]`、T3.1 多数 `[x]`/「跳过」、T3.2 全 `[x]`，而 T2.3 全 `[ ]` 却被状态行标「已完成」）。按「文档说的 ≠ 代码是的，下结论前对码」逐条实跑核实，不照旧标签重做、也不盲翻复选框。

### 已落地（逐条对码确认，非据状态行）

| 项 | 对码证据（2026-10-15） |
|---|---|
| 补充 1 sandbox proc.kill | `sandbox.py:132 _terminate()` 做 `proc.kill()`+`communicate()`；`_execute_docker:176` 与 `_execute_subprocess:214` 的 `except asyncio.TimeoutError` 均 `await self._terminate(...); raise`（T1.2a） |
| 补充 2 mcp_client stack.aclose | `mcp_client.py:_connect_stdio:130-137` 与 `_connect_sse:144-152` 均 `try: ... except BaseException: await stack.aclose(); raise`；连接失败处 `:110-116` 亦回收 stack（T1.2a） |
| 补充 3 /api/upload thread_id | `agent_federation/api/server.py:252-259` `/api/upload` 与 `/api/task:236` 同走 `_resolve_thread_id_or_401`，鉴权启用时忽略客户端 thread_id、按服务端断言主体派生 ⇒ 上传件与对话落同一会话目录 |
| 补充 5 Skill 型口径 | `ARCHITECTURE.md:39` 已是「Function/Agent/Remote/Workflow 四型 SkillKind，MCP/Sandbox 经特化注册函数挂载」，与 AGENTS.md 口径一致（原「六型」矛盾已消） |
| 补充 6 code_execution 懒初始化 | `agent_federation/tools/code_execution_tool.py:25 _sandbox=None` + `_get_sandbox()` 懒初始化（注释明标 T1.2a/T1.2b），import 期不再固化后端；默认 docker-only，`SANDBOX_ALLOW_SUBPROCESS` 未开不静默降级 |
| W6 应用层静默吞 | `agent_server/main.py:417-427` to_skill 失败时：`planner in ("agentic","auto")` ⇒ `logger.warning(exc_info=True)`，否则 DEBUG（T1.2c/B2 评审结论）⇒ 需要时红灯如实亮，非一律静默 |
| T2.4 / T3.1 / T3.2 | 复选框全 `[x]`（T3.1 余者为显式「跳过」并注明原因）；`scripts/check_doc_sync.py` 已存在并常驻 CI（本机 `make`-等价实跑 rc=0） |

### 本批落地（2026-10-15）：补充 7 / T1.7

- **做了什么**：新增 `packages/agent-runtime/tests/test_agentic_skill_discovery.py`（2 条），走**真实 entry_points 发现路径**（不显式注入 factory）：
  - 正向 `test_to_skill_discovers_executor_via_entry_points_without_explicit_registration`：清掉模块级 `_executor_factory` 后，`AgenticPlanner().to_skill()` 经 `importlib.metadata.entry_points(group="agent_runtime.agentic_executor")` 发现 `agent_federation/pyproject.toml:68-69` 注册的工厂，产出合法 `SkillKind.AGENT`，并断言发现后 `_executor_factory` 被写回（证明真走了 EP 路径而非显式注入）。EP 不可发现属**环境条件**（未装 `--extra agentic`）⇒ skip（同仓 requires_pg/ZHIKU_INTEGRATION 守卫范式）。本机实跑 **PASSED（非 skip）**：EP 可发现。
  - 负向 `test_discover_raises_runtimeerror_when_no_executor_available`：把 `entry_points` 打成空 ⇒ 断言 `_discover_executor_factory()` **抛 RuntimeError** 且消息含可操作解锁动作（装 extra / 显式注册）。**确定性**、不依赖真实安装，锁住 W6「发现失败必须 fail-loud，绝不静默返回」在发现层的契约。
- **为什么有价值**：此前 `test_agentic_skill.py` 7 条用例**全部** `register_agentic_executor_factory(lambda: fake)` 显式注入 ⇒ `_discover_executor_factory` 第一分支短路，**从不走 entry_points**；而生产 `agent_server/main.py:413` 恰恰依赖 EP 发现。显式注入的测试全绿却掩盖了「真实安装下发现路径是否通」——本批补上这把锁，EP 注册若被破坏（pyproject 改动/包未装）正向用例即红。
- **顺带**：给 `test_agentic_skill.py:98` 的 `reg.execute("agentic", ...)`（lint P4-2 白名单豁免）补注释，说明「仅测试内豁免、生产须走 delegate」，并指向本发现路径测试。
- **实跑**：`ruff check` 该 2 文件 rc=0；`pytest packages/agent-runtime/tests` **638 passed**（636→638，+2），既有用例零删改（`test_agentic_skill.py` 仅加注释，7 条断言逐字未动）。

### 残留与待定（附不做/待定的判据，不粉饰为已完成）

- **T2.2**：已**分项处置**（详见 T2.2 节）——item5（`config.py` 三处改 `dataclasses.replace`，消除 frozen dataclass 六字段手抄）**本批落地**并自证零回归（replace 保留全部非 healthy 字段、federation 176 passed）；item6（`agent.py` HTTP if-elif→dict 派发）核实后**判定不做**（if-elif 编码真实 body/no-body 区别 + else→400 错误分支，dict 派发须给每调用套 lambda 反不清晰，仅 3 个非齐整分支属过度抽象）；items1-4（4 处 ~200 行大函数拆分）**缓做**——纯可读性重构、无功能收益、回归风险高，**与本 plan T3.1 把同类「`routes.py` 按业务域拆分」判为「跳过：大规模重构」直接矛盾**，且行号引用已漂移（`api/routes.py:65 query` 现已在 `api/query_router.py`）⇒ 如需做应独立成方案 + 独立分支 + 逐函数补测后再拆。
- **T2.3**：已**重新对码 + 分项处置**（详见 T2.3 节）——item5（exhibition `.env.example` 补全 10 个 `EXHIBITION_AGENT_*` Settings 变量，1:1 取自 config.py 零杜撰）+ item6（kefu `.env.example:6` 悬空引用 repoint 到 `agent-core/README.md`「环境变量清单」，不新建重复清单）**本批落地**；items1/7（langchain 下界、requirements.txt agent-runtime）**早已落地**；items2/4/8（sqlglot、ruff `I`、pytest importlib）因 `dialogue-framework`/`zhanggui-zhiku`/`wenda` 三包已消失而 **moot，但意图已在全仓满足**；唯 **item3 的 fastapi 根下界 `>=0.115` 低于旧目标 `0.129`** —— 仅抬下界、无 feature/bugfix 驱动，盲抬会无谓收紧解析 ⇒ **标注不盲改**，留独立依赖评审。本节不再是「整节待重新对码」。
- **补充 4（agentic bridge opt-in 策略）**：`_maybe_attach_bridged_tools` 默认关（`AGENTIC_RUNTIME_BRIDGE=true` 才开）是「渐进推广」的设计决策；T1.2 要求「改为默认开启」还是「保留 opt-in 但补开启路径测试」属**待拍板**，非纯执行项。
