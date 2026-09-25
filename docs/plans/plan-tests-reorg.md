# 方案：tests/ 根目录测试用例分门别类

> 状态：**Proposed**
> 目标：根 `tests/` 下 ~45 个扁平测试文件按平台架构域归类到子目录，提升可发现性与与
> `packages/*`、`applications/*` 分层一致的归属感；不增删测试、不改测试逻辑。

## 一、现状

- `tests/` 根目录有 ~45 个扁平 `test_*.py`，与已存在的 `dialogue_framework/`、`ha/`、`wenda_data_agent/` 三个子包混在一起，归属不清。
- 收集配置（`pyproject.toml:60`）：`testpaths = ["tests", "packages/agent-core/tests"]`，`addopts = "--import-mode=importlib"`。
- `tests/conftest.py` 为 session 级，对所有子目录生效；现有 `ha/`、`dialogue_framework/`、`wenda_data_agent/` 已是带相对导入的包（需 `__init__.py` 或 importlib 模式即可）。
- 根扁平文件之间**无互相 import**（已用 grep 确认），移动无跨文件引用破坏风险。

## 二、目标分类（架构对齐）

| 子目录 | 归属域 | 文件 |
|---|---|---|
| `planner/` | 规划 / 执行图 / 工作流 | `test_execution_graph` `test_graph_planner` `test_planner_protocol` `test_policy_validator` `test_unified_planner` `test_workflow_yaml` `test_execute_plan` |
| `skills/` | Skill 注册 / 委派 / 守卫中间件 | `test_skill_delegation` `test_skill_discovery` `test_guard_middleware` |
| `runtime/` | 运行时基础设施（熔断/协调/session/连接池） | `test_circuit_breaker` `test_coordinator` `test_session_lease` `test_db_pool_close` |
| `durability/` | 持久化 / checkpoint / 轨迹 | `test_pg_durability` `test_trajectory` `test_trajectory_replay` |
| `memory/` | 记忆 / 检索 / 上下文 / 压缩 | `test_memory_backend` `test_longterm_h` `test_recall_exact` `test_retrieval` `test_thread_persist` `test_context_manager` `test_context_assembler` `test_compact` `test_chunker` |
| `governance/` | 鉴权 / 护栏 / SQL / 计量 / 指纹 / 能力注册 | `test_auth` `test_input_guard_graph` `test_planner_governance` `test_p2_2_usage_metering` `test_p5_1_fingerprint` `test_capability_registry` `test_audit_fixes` `test_sql_guard` `test_sql_pipeline` `test_workspace_isolation` |
| `observability/` | 日志 / 后台任务 / 快照 | `test_logging_unification` `test_background_tasks` `test_snapshot_injection` |
| `api/` | 接口冒烟 / 生命周期 / 路由 | `test_api_smoke` `test_agent_state` `test_query_lifecycle` `test_router` |
| `llm/` | LLM 回退 | `test_llm_fallback` |
| `intent/` | 意图桥接 | `test_intent_bridge` |

已有子包保留：`dialogue_framework/`、`ha/`、`wenda_data_agent/`（不动）。
`tests/conftest.py` 保留在根（对所有子目录生效）。

## 三、迁移策略

1. 为每个新子目录 `git mv` 对应文件；子目录加 `__init__.py`（与现有 `ha/` 一致，保证 importlib 模式无歧义、避免同名 basename 潜在冲突）。
2. 不修改任何测试文件内容；根 `conftest.py` 不动。
3. 完成后：
   - `pytest tests/` 收集数应与移动前一致、全部通过（无 import/collection error）；
   - `ruff check .`、`scripts/lint_architecture.py` 不受影响；
   - 现有 `make test` / `make ci` 路径（`testpaths` 仍为 `tests`）递归收集新子目录，行为不变。
4. 若有个别文件归属模糊，临时归入最相近目录，不在本方案内新造 `misc/`。

## 四、验收标准

- `git mv` 后 `pytest tests/ -q`：收集用例数与移动前一致、全绿（无 error/warning collection）。
- `ruff check .` 与架构 lint 通过。
- 文档（本方案）记录分类映射，便于后续新增测试按域归位。

## 五、风险与边界

- 仅测试文件移动，零生产代码改动；CI 门禁（`testpaths`）无需改。
- `--import-mode=importlib` 下，若两个子目录出现同名 `test_*.py` 需靠包路径区分；本次移动后各子目录 basename 互不冲突（已核对）。
- 不触及 `packages/*/tests` 与 `applications/*/tests`（各自独立 session）。
