# agent-platform 架构与技术债审计报告

> **审计日期**：2026-09-24
> **审计范围**：`packages/`（3 包）+ `applications/`（6 应用）+ 根包，只读审计，未改动任何代码
> **基线提交**：`5207365`（分支 `v3`，工作区干净）
> **审计方法**：9 路并行静态核查（依赖方向 / 死代码 / 中间件接线度 / 占位实现 / 数据层 / 契约一致性 / 配置漂移 / 异常吞噬 / 仓库卫生）+ 关键项人工读码复核
> **文档基线核对**：`docs/plans/plan-tech-debt-followup-2026-09-22.md`、`docs/plans/tech-debt-multi-agent-2026-09-23.md`、`skill-consolidation-inventory.md`、`AGENTS.md`

---

## 结论摘要

**项目整体工程质量处于较高水平**：核心架构红线未被破坏，门禁全绿，无硬编码密钥，无仓库污染。但存在 **4 项 P0 级问题**，其中 2 项属于**「声明已完成、实际不成立」的架构失真**——这类问题比单纯的未完成更危险，因为它会误导后续所有基于文档的决策。

| 级别 | 数量 | 核心特征 |
|------|------|---------|
| **P0** | 4 | 架构声明失真（Scheduler 假接线）、计费/状态静默丢失、配置分裂致运行期故障、lint 豁免倒退 |
| **P1** | 10 | 契约未统一、隐式跨应用依赖、DDL 无迁移、租户隔离缺口、双库不一致、V3 半成品、评测假绿 |
| **P2** | 7（含 1 项复核撤销 → 有效 6） | 死代码、竞态未根治、WS 未接中间件、文档口径矛盾 |

**最需要立刻处理的两件事**：
1. `Scheduler` 不是执行门控链路的一环，且会错标他人任务状态（P0-1）——修正 AGENTS.md 的架构声明，或修复接线。
2. `D7` 声称的「211 处逐处 noqa + 注释」已被反转成全局 `ignore = ["BLE001", "S110"]`（P0-4）——文档失真 + 门禁倒退。

**关键补充（详见第六节）**：P0-1 与 P0-2 **不是外围技术债，而正是项目自己在 `plan-v3-execution-platform-final-architecture-2026-09-22.md:381` 定义的 "P0 五项"验收标准**——「这五项闭环后 V3 才算 Execution Platform 而非 Agent Framework」。当前 Phase 2-4 闭环的是 Medium 级的 ControlPlane/Forensic，而 5 项 High/P0 级能力均未真正闭环，却被 `AGENTS.md` 声明为「已完成」，构成**优先级倒挂 + 进度声明超前于验收达成度**。

---

## 一、先说好消息（已验证无问题的部分）

审计中主动核查并**排除**的假设，避免后续重复投入：

| 检查项 | 结论 | 证据 |
|--------|------|------|
| **红线 1：共享包反向 import 应用层** | ✅ **未发现** | `packages/agent-core`、`packages/agent-runtime` 全量 import 扫描零命中；唯一命中为 docstring（`agent_runtime/planner/agentic.py:9`）。依赖倒置通过 `importlib.metadata.entry_points`（`agentic.py:62`）+ `agent_federation/pyproject.toml:67` 注册实现，合规 |
| **包间循环依赖** | ✅ **无环** | `agent-core`（零依赖）→ `shared-schemas`（仅 pydantic）→ `agent-runtime`（agent-core + shared-schemas），单向 |
| **硬编码密钥** | ✅ **未发现** | 全仓正则扫描（sk-* / password= / secret= / api_key=）排除测试与示例后零命中 |
| **仓库卫生** | ✅ **良好** | `.pyc` 入库数 = 0；`.log`/`.tmp`/`.bak` 入库数 = 0；无 >5MB 大文件；`.gitignore` 覆盖 `__pycache__`/`*.pyc`/`.env`/`.venv` |
| **静态门禁** | ✅ **全绿** | `ruff check .` → All checks passed；`scripts/check_doc_sync.py` → 0 警告 |
| **CI 单一真相** | ✅ **合规** | `.github/workflows/agent-platform-ci.yml:59` 直接 `make ci`，未手写重复命令 |
| **超长文件** | ✅ **可控** | 最大 `planner/protocol.py` 779 行，无 2000 行级巨物 |
| **临时调试文件** | ✅ **未入库** | 根目录 `pr9_ci.log` / `pr9_ci_fail.log` 存在于工作区但未 git 追踪 |
| **Admission 门控真实性** | ✅ **真门控** | `query_router.py:96` 429/503 拒绝、`:122-128` coordinator reject 409、`:168` `wait_for_admit` 阻塞 |

---

## 二、P0 级问题（4 项）

### P0-1　Scheduler 是「记账式旁路」而非执行门控，且会错标他人任务

**这是本次审计最重要的发现。**

**声明**：`AGENTS.md` 称「V3 企业执行平台：执行链路升级为 `Admission → Scheduler Queue → Dispatch → Planner → Execute → Forensic/CostGov`」。

**实际**：Scheduler 不在执行链路的关键路径上，只做旁路记账，且记错账。

证据链（`applications/agent_server/api/query_router.py`）：

| 行号 | 代码 | 问题 |
|------|------|------|
| `:66-73` | `await scheduler.submit(ExecutionRequest(execution_id=request_id, ...))` | 仅入队记账。**不检查并发上限**（`submit` 只校验 `queue_capacity`），无论是否 admit 都继续往下执行 |
| `:261` | `await scheduler.dispatch_next()` | **无参数**，返回值被丢弃 |
| `:317-319` | `await scheduler.complete(request_id)` | 意图标记`本人`任务为终态，**但实为 broken**：`complete()` 签名为 `(execution_id, status)`（`execution_scheduler.py:506`，`status` 无默认值），此处仅传 1 参 → 运行期 `TypeError`，被 `:320-321` 的 `logger.debug` 静默吞掉（见 P0-2），终态标记从未成功 |

`dispatch_next()` 的实际语义（`packages/agent-runtime/agent_runtime/execution_scheduler.py:498-500` → `PgSchedulerStore.dequeue:299-359`）：

```sql
SELECT ... FROM execution_queue eq
LEFT JOIN LATERAL (SELECT count(*) ... WHERE tenant_id = eq.tenant_id ...) tr ON true
WHERE eq.status = 'QUEUED' AND tr.tenant_running < %s
ORDER BY priority DESC, tr.tenant_running ASC, eq.created_at ASC
LIMIT 1 FOR UPDATE SKIP LOCKED
```

即：**按优先级/公平性取队首任意任务**，不认领调用者自己的任务。

**三重后果**：

1. **`max_concurrent` / `max_concurrent_per_tenant` 完全失效**
   入队不检查并发；`dispatch_next` 返回 `None`（队列满/超并发）时**不阻断**当前请求执行。真实并发只受 uvicorn 限制。`scheduler_max_concurrent=10`（`config.py:144`）是死配置。

2. **队列状态机与业务请求解耦 → 错标他人**
   请求 A 处理中调用 `dispatch_next()`，弹出并标记为 `DISPATCHED` 的很可能是并发的请求 B。`query_router.py` **从不调用 `scheduler.mark_running()`**（全文件无此调用），因此被标记的行永远停在 `DISPATCHED`，无从推进到 `RUNNING`。

3. **产生伪造的失败记录，污染下游**
   滞留 `DISPATCHED` 的行由 `SchedulerReaper` 标记 `FAILED`（`execution_scheduler.py:573-579`）：`list_overdue` 对 DISPATCHED 用 `dispatch_timeout`（默认 **60s**；`running_timeout` 才是 300s），再过一道 lease 门控 `ownership.get_owner(...) is None` 后才 `complete(..., FAILED)`。这些**从未失败**的任务被写成失败，污染 `execution_status`、`ControlPlane`（`api/control.py`）的执行视图与 `CostGovernance` 统计口径。

**缓解因素**：`scheduler_enabled` 默认 `False`（`config.py:143`），故当前生产默认配置下不触发。但文档已声明「已完成」，属**开启即故障**。

**建议**（三选一，按推荐排序）：
- **A（推荐）**：改正文档口径 —— AGENTS.md 不应把 Scheduler 列入执行链路，改为「旁路记账 + 独立控制面」，同时把 `dispatch_next()` 的接线降级为明确的设计说明或临时移除。
- **B**：修复接线 —— `submit` 前置并发检查并在超限时返回 429/503（真门控）；`dispatch_next(execution_id=request_id)` 认领自己的任务并在成功后调 `mark_running`。
- **C**：若确为「延迟调度」意图，则必须让请求**先挂起等待被调度**再执行，而非边执行边记账。

---

### P0-2　计费与执行状态持久化全链路静默吞噬（debug 级）

**位置**：`applications/agent_server/api/query_router.py`

| 行号 | 被吞噬的操作 | 日志级别 |
|------|-------------|---------|
| `:263` | `scheduler.dispatch_next()` 失败 | `debug` |
| `:274` | `status_store.save(RUNNING)` 失败 | `debug` |
| `:293` | `status_store.save(WAITING_EXTERNAL)` 失败 | `debug` |
| `:320-321` | `scheduler.complete()` 失败 | `debug` |
| `:331` | `status_store.save(终态)` 失败 | `debug` |
| `:345-346` | **`cost_governance.record()` 失败（计费/配额记账）** | `debug` |

**影响**：
- 生产默认日志级别为 INFO 时，`logger.debug` **不输出**。计费丢单、配额漏记、任务状态与实际不一致，运维侧完全不可见。
- 更严重的是 `:307-310` 的顶层异常处理：

```python
except Exception as exc:
    _stream_failed = True
    yield _sse({"type": "error", "error": str(exc)})
    yield _sse({"type": "done", "thread_id": thread_id, "answer": ""})
```

此处**没有任何日志调用**——异常信息只发给了客户端。服务端日志不留痕，事后排查只能靠用户截图。与 C-4 修复（新增 error 事件）属于同一处代码，但只修了一半。

**建议**：计费与状态持久化失败应为 `warning` + `exc_info=True`；顶层异常补 `logger.exception`。

---

### P0-3　环境变量命名分裂，按 `.env.example` 配置会运行期失败

| 概念 | 变量名 A（根 `.env.example` 声明） | 变量名 B（代码实际读取） | 后果 |
|------|-----------------------------------|------------------------|------|
| LLM 密钥 | `LLM_API_KEY` | `OPENAI_API_KEY`（`agent_federation/agent/llm.py:19`、`knowledge_service/core/config.py:65`） | **按根 `.env.example` 配置后，federation 与 knowledge-service 的 LLM 调用无 key，运行期才暴露** |
| LLM Base URL | `LLM_BASE_URL` | `OPENAI_BASE_URL`（同上） | 同上 |
| Embedding 密钥 | `EMBEDDING_API_KEY`（根 `.env:50`） | `SILICONFLOW_API_KEY`（knowledge `.env`） | 检索链路静默降级 |
| 服务鉴权 | `API_KEY`（agent_server / federation） | `KNOWLEDGE_API_KEY`（knowledge） | 无法用一套配置打通 |

**影响面**：这是**部署/交付类缺陷**——新环境按文档配置后服务"能启动但不工作"，排查成本高。

**建议**：确立单一权威名（推荐全部收敛到 `LLM_API_KEY` / `LLM_BASE_URL`），旧名保留为兼容别名并在 `.env.example` 写明；同时把「读了但未声明」的变量补齐到 `.env.example`（`NL2SQL_SERVICE_URL`、`FED_TASK_TIMEOUT_S`、`SANDBOX_*` 等）。

---

### P0-4　lint 豁免从「逐处审查」倒退为「全局关闭」，且 D7 文档与此不符

**声明**（`plan-tech-debt-followup-2026-09-22.md` D7）：
> 「全仓 211 处 BLE001 违规已全部标注 `# noqa: BLE001` + 上下文注释」「每处 broad catch 有明确注释说明为何宽捕获，便于后续审查」

**实际**：
- 根 `pyproject.toml` 的 ruff 配置：`ignore = ["B008", "E402", "E731", "BLE001", "S110", "B017", "PERF102", "RUF059"]` —— **BLE001（盲捕获）与 S110（try-except-pass）被全局关闭**。
- 受管代码（`packages/`、`applications/`、`tests/`、`scripts/`、`eval/`）中的 `# noqa: BLE001` 数量 = **0 处**。（复核：未入库的 `courses/` 亦为 0 处 BLE001；D7 记录的原始 211 处 noqa 已随提交 `92ba46f` 全量删除，仓内已无该规则的 noqa 残留可归属。）
- 提交 `92ba46f` 标题自述：「清理 **358 处** BLE001 死代码 noqa」——即**主动删除**了 noqa 留痕，转由全局 ignore 兜底。

**为什么这是倒退**：
D7 的原始价值在于「211 处宽捕获每处留痕、可审查」。改为全局 `ignore` 后：
- 仓内**不再有任何痕迹**表明哪些位置做了宽捕获、为什么 —— 后续审查只能 `grep "except Exception"`，且丢失了原始的「为何宽捕获」上下文注释。
- **新写的裸 except 不再被任何门禁拦截**，同类问题可无限复发。
- 这与 D4「ruff ignore 存量基线逐包收窄」的方向**完全相反**（D4 想收紧豁免，此处却在扩大）。

**建议**：
- 短期：修正 D7 文档记录，明确「已由逐处 noqa 改为全局豁免」，避免后人误信。
- 中期：**恢复 BLE001 为启用状态**，对存量做一次真正的逐处分类（真宽捕获 → 收窄为具体异常；确需宽捕获 → noqa + 注释）。可参考已完成的 `agent-federation` 侧做法。这项工作量可控（受管代码规模有限）。

---

## 三、P1 级问题（10 项）

### P1-1　跨服务契约未统一，版本号三值并存

| 服务 | shared_schemas 接入情况 | 证据 |
|------|------------------------|------|
| agent_server | ✅ 继承扩展 | `schemas.py:32-40, 60` |
| kefu-service | ✅ 完整使用 | `__main__.py:24-25` |
| nl2sql-service | ⚠️ 继承但新增非契约字段 | `api/schemas/query_schema.py:4,9,19`（新增 `sql`/`error`） |
| knowledge-service | ⚠️ 仅请求侧，响应侧自建 dict | `api/query_router.py:21,55` |
| agent_federation | ⚠️ 仅入站校验 + 形状断言 | `api/server.py:16`、`agent/async_subagents.py:64,92` |
| **exhibition-agent** | ❌ **完全绕过** | 无任何 `shared_schemas` 导入；自建 `ChatRequest`/`InvokeRequest`（`skill_loader/app.py:55,59`） |

**契约版本号冲突**：共享 `CONTRACT_VERSION = "1.0"`（`shared_schemas/query.py:11`）vs exhibition 自带 `"1.1"`（`middleware/execution_context_middleware.py:27`）与 `"1.2"`（`client/warehouse_client.py:37`）。

**同名模型不同形状**：`HistoryItem` 在 `agent_server/schemas.py:133`（`index/role/content/id/created_at`）与 `knowledge-service/api/query_router.py:48`（`role/text`）定义不同。

**`query` 长度上限三处不一致**：无限制（base）/ `max_length=2000`（`agent_server/schemas.py:77`）/ `max_length=512`（`knowledge/query_router.py:63`）—— 联邦网关放行的请求可能在 knowledge 侧被拒。

### P1-2　HTTP 错误响应格式：5 种并存，federation 服务内自相矛盾

| 服务 | 格式 |
|------|------|
| agent_server | `{"detail": ...}`（FastAPI 默认，`api/auth.py:21` 等） |
| agent_federation | **混用** `{"detail":...}`（`api/server.py:169,176`）与 `{"error":...}`（`:263-295`） |
| knowledge-service | `{code, msg, request_id}`（`utils/error_response_utils.py:39-41`） |
| exhibition-agent | skill_loader `{"error":...}`（`skill_loader/app.py:97`）/ 主 server `detail={"code":"INTERNAL",...}`（`server.py:187-189`）—— 两种 |
| nl2sql-service | **异常仍返回 HTTP 200**，错误塞进响应体（`api/routers/query_router.py:31-39`，全文仅 40 行） |

**SSE error 事件跨服务不一致**：
- knowledge：`event: error\ndata: {"error": ...}`（`utils/sse_utils.py:16,95`）
- agent_server：`data: {"type": "error", "error": ...}`，**无 `event:` 行**（`api/query_router.py:309`，因 `sse_pack("", payload)` 传空事件名）

`shared_schemas/sse.py` 已提供统一 `sse_pack`，但两服务传参语义不同（事件名 vs payload.type），**统一能力未被一致使用**。客户端需为每个服务写不同解析分支。

### P1-3　跨应用隐式依赖（依赖声明缺失）

```
applications/knowledge-service/knowledge_service/core/knowledge_lifecycle_integration.py:18:
    from exhibition_agent.foundation.knowledge_lifecycle import (...)
```

knowledge-service **生产代码 import 了 exhibition-agent**，但 `applications/knowledge-service/pyproject.toml` 的 `dependencies` 中**未声明** exhibition-agent。该文件 docstring 自述为「单向依赖」，但依赖未声明 → 独立安装/构建时 `ImportError`，且破坏了「应用间不横向依赖」的架构约定。

**建议**：把 `knowledge_lifecycle` 下沉到 `packages/agent-runtime` 或 shared-schemas（若确为通用能力），否则补声明依赖并评估是否应改为 HTTP 调用。

### P1-4　DDL 无迁移机制

- 全仓**无 Alembic / 无 `migrations/` 目录 / 无 `.sql` 文件**。
- 表结构以 `SCHEMA_TEMPLATE` 内联在 `packages/agent-runtime/agent_runtime/db.py:17`（`db.py` 内含 **24** 处 `CREATE TABLE`，另有 federation/vector_backend 少量内联）；`ensure_schema`（`db.py:394-442`）以「`CREATE TABLE IF NOT EXISTS` + 裸 `ALTER TABLE ... ADD COLUMN`」随进程启动执行，且异常被静默：
  ```python
  except Exception: pass   # duplicate_column 幂等失败忽略
  ```
- 其他内联点：`applications/agent_federation/agent/db.py:28-88`、`packages/agent-core/agent_core/memory/vector_backend.py:256-296`。

**缺口**：改列类型、加约束、删列、加索引**完全无机制**；无版本号、无执行顺序保证、无回滚。多实例并发启动同时 `ALTER` 依赖 `IF NOT EXISTS` 兜底。

`state_migration.py` 仅做 checkpoint JSONB 版本迁移，**不是** DDL 迁移。

### P1-5　多租户隔离缺口

| 位置 | 问题 |
|------|------|
| `db.py:29-36` `memories` 表 | **无 `tenant_id` 列**；`typed.py:159/270/286/304` 仅按 `user_id` 过滤 |
| `db.py:81-92` `admission_queue` 表 | **无 `tenant_id` 列**；`admission.py:99/243` 仅按 `status`/`request_id` |
| `db.py:514` + `agent_server/sql/schema_store.py:44-50` | `workspace_id` 为空时退化为 `WHERE embedding IS NOT NULL`（无过滤）；调用方 `sql/pipeline.py:90 fetch_context(pool, question)` **未传 workspace** → **跨工作空间召回 `sql_ddl`/`sql_docs`/`sql_examples`**（SQL 元知识泄漏） |
| `cache.py:56-61` | `tenant_id` 为空时无 `WHERE` 条件（`query_router.py:139/295` 传 `req.tenant_id or ""`） |
| `memory_pg.py` episodic/procedural | 无 tenant 列，全局主键 |

**注**：C-7/P1-3/C-8 的修复已核实为真（`schema_store.py:44-49` 有 `workspace_id = %s`、`cache.py:49-55/91-93` 有 `tenant_id = %s`、knowledge `milvus_filter_utils.py:37-38` 有 `tenant_id == "..."`）。上表是新发现的**残留缺口**，非已修项回归。

### P1-6　Milvus 与 pgvector 双知识库，删除/GC 不互通

- knowledge-service：唯一 Milvus（`milvus_utils.py:26` 单例），删除只作用于 Milvus（`node_import_milvus.py:316`）。
- agent_server：pgvector（`rag/store.py:69` chunks + sql 元知识 + memories）。**全仓无 `DELETE FROM chunks`** —— 即**没有任何删除/GC 路径**（仅评测脚本 `scripts/flashrag_eval/run_eval.py:173` 清空）。
- `vector_backend.py:386-396` 按 `VECTOR_BACKEND` 二选一（非双写），但默认值为 Milvus（`agent_core/config.py:137`），而 typed memory 落 pgvector `memories` → **同一平台的语义记忆分裂在两套存储**，无一致性校验、无同步。

**影响**：知识删除后残留、检索结果不一致、无容量回收机制。

### P1-7　4 个 V3 模块为「半成品」（有单测、生产零调用）

| 模块 | 生产调用 | 判定 |
|------|---------|------|
| `execution_scheduler.py` | `main.py:380` + `query_router.py:66/261/319` | ✅ 已接线（但见 P0-1） |
| `execution_status.py` | `main.py:376/379`、`query_router.py:269/288/326`、`callback.py:120/180` | ✅ 已接线 |
| `awaitable_task.py` | `main.py:332/336/353`、`protocol.py:653/662`、`callback.py:43/63` | ✅ 已接线（需 Skill 返回 `__awaitable__` 才触发） |
| `control_plane.py` | `main.py:403`、`api/control.py:28-118` | ✅ 已接线（独立控制面 API，非 /query 主链） |
| `cost_governance.py` | `main.py:449`、`query_router.py:84/338-344` | ✅ 已接线 |
| `forensic.py` | `protocol.py:622`、`execution_graph.py:58` | ✅ 已接线 |
| `effect_contract.py` | `execution_graph.py:337/368/377` | ⚠️ 仅 graph/workflow planner 路径（默认 deterministic 不经过） |
| **`human_task.py`** | **`applications/` 零命中** | ❌ 半成品 |
| **`execution_recovery.py`** | **仅自身 + 单测** | ❌ 半成品 |
| **`state_migration.py`** | **仅自身 + 单测** | ❌ 半成品 |
| **`payload_externalization.py`** | **`applications/` 零命中** | ❌ 半成品 |

`tech-debt-multi-agent-2026-09-23.md` 的 B-5b 只披露豁免了 `ExecutionRecovery`，**未披露** `human_task` / `state_migration` / `payload_externalization` 同样是未接线状态。

**建议**：明确这 4 个模块的归属——要么排期接线，要么标记为「设计就绪、待集成」并计入文档，避免被误认为已上线能力。

### P1-8　`execution_context` 凭证管理为 fail-open 形态（潜在 P0）

`applications/exhibition-agent/exhibition_agent/foundation/execution_context.py:267-279`：

```python
return ServiceCredential(
    system=system,
    credential_ref="placeholder",
    permissions=[],
    expires_at=None,
)
```

该对象是**真值**（truthy），perms 为空、无过期时间。若任何调用方以 `if cred:` 判定放行，本应拒绝的机器通道会被放行 —— **fail-open**。

**当前状态**：全仓 grep 显示该函数**仅被 tests 引用**，未接入任何鉴权路径 → 属于「尚未生效的隐患」。但一旦接线，即成为 P0 级越权漏洞。

**建议**：改为 `raise NotImplementedError`（fail-close），或返回 `None` 并强制调用方显式处理缺失凭证。

### P1-9　评测自洽失效（跨租户隔离「假绿」）

`applications/exhibition-agent/exhibition_agent/foundation/evaluation.py`：

- `_mock_scope_filter`（`:56-67`）为静默 mock；
- `_evaluate_cross_tenant_negative`（`:110-124`）用**同一个 mock 过滤后的 `scoped` 集合**统计越权项 —— 而 mock 已剔除全部跨租户非 PUBLIC 项 → **`violations` 恒为 0、负样本恒 PASS**。
- `:146` 另缺「同具体性、不同租户」类样本。

**影响**：跨租户隔离的「评测证明」**不可信**——它证明的是 mock 的行为，不是真实 `enforce_scope_filter` 的行为。（注：真实 `enforce_scope_filter` 在 `execution_context.py:156-186` 是**真实现**，问题只在评测未使用它。）

**建议**：评测必须针对真实实现（或至少让 mock 与真实实现行为对齐并单独验证），并补充「同具体性不同租户」样本。

### P1-10　DB 连接管理与参数默认值不一致

| 问题 | 位置 |
|------|------|
| 每次只读查询**新建连接**、无池 | `agent_server/sql/pipeline.py:75` `await psycopg.AsyncConnection.connect(...)` |
| 类定义重复 | `nl2sql` 有 `dependencies.py:35/58`（lifespan 双池）与 `postgres_client_manager.py:19` 两套 |
| `sql_max_rows` 默认值 10 倍差 | agent_server `100`（`config.py:36`）/ nl2sql `1000`（`settings.py:40`）/ federation `100`（`tools/sql_guard.py:25`） |
| `top_k` 三值不一致 | agent_server `4` / nl2sql `10` / knowledge `5` |
| 端口默认值与文档不符 | knowledge 代码默认 `8900`（`core/config.py:47`）但自身 `.env.example` 写 `8000`；nl2sql 代码 `8000` 但 `.env.example` 写 `8002` |

---

## 四、P2 级问题（7 项，其中 P2-4 经复核撤销）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| P2-1 | **死代码**：`skill_router.py` 全仓零引用 | `exhibition-agent/exhibition_agent/foundation/skill_router.py` | 内部实现真实（`_check_scope:134-158` 真校验），但无任何 import；仅 docstring/文档提及。文档 C-6 曾提「评估接线或删除」，未闭环。**删除不丢运行时功能** |
| P2-2 | **singleflight 竞态未结构性消除** | `agent_runtime/singleflight.py:52-57` | 原始「立即 pop 导致双跑」已修（结果缓存与锁同窗口保留）。但 `pop` 仍是按 key 无条件删除、**无引用计数/身份校验**。异常路径 + 执行超过 300s 时，先前调度的 `call_later` 会删掉正在使用的锁，同类竞态可复现——只是被 300s 延迟收窄，非根治 |
| P2-3 | **WS 路径未接 admission/coordinator** | `agent_federation/api/server.py:349,362-364` | `start_span` + 异常日志已补（B-4 属实），但异常仅记日志 + 断连，**不向客户端发 error 帧**，且无排队/背压。WS 语义差异已知，但当前无兜底设计文档 |
| ~~P2-4~~ **（复核撤销：假阳性）** | ~~DDL 加列无法确认~~ → 已找到 | `schema_store` 的 `workspace_id` 列 | C-7 的 WHERE 过滤属实。经复核，该列 DDL **就在仓内**：`packages/agent-runtime/agent_runtime/db.py` 的 `CREATE TABLE sql_ddl/sql_docs/sql_examples (... workspace_id ...)`@`:54/64/75` + 幂等 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS workspace_id`@`:57/67/78`（`chunks` 亦见 `ensure_schema`@`:423`）。原「本仓未找到」表述有误——schema 真相源**在代码**；真正缺口已由 P1-4（无版本化/回滚迁移机制）覆盖 |
| P2-5 | **`.env.example` 与代码读取不匹配** | 多处 | exhibition 未声明 `NL2SQL_SERVICE_URL`（`skills/data_analysis/skill.py:33` 读，默认 `localhost:8000`）；federation 的 `FED_*`/`SANDBOX_*`/`GRAY_PCT` 未全声明；根 `.env.example` 的 `OTEL_*`/`MCP_*`/`ADMISSION_*` 在 knowledge/federation 侧无对应读取 |
| P2-6 | **文档口径矛盾** | `AGENTS.md:85` vs `plan-tech-debt-followup-2026-09-22.md` | AGENTS.md 称「D1-D10 全部闭合」，但追踪文档明确 D1/D4/D5/D8 四项为「跳过/未做」（Low，附跳过原因与建议推进）。「全部闭合」与「4 项 Low 待办」是不同口径 |
| P2-7 | 宽捕获样本（次危险） | `knowledge-service/api/import_router.py:243-245` | MinIO 上传失败仅 `warning` 后继续本地流程 → 对象存储与本地状态可能不一致 |

---

## 五、修复优先级建议

### 第一批（本周，低成本高收益）
1. **修正文档失真**（P0-1 口径、P0-4 的 D7 记录、P1-7 的 4 个半成品披露、P2-6 口径）—— 不改代码，只让文档与事实对齐。这是所有后续决策的地基。
2. **补日志**（P0-2）：计费/状态持久化失败 → `warning` + `exc_info`；顶层异常补 `logger.exception`。改动约 7 处。
3. **修配置分裂**（P0-3）：统一 `LLM_API_KEY`/`LLM_BASE_URL`，旧名保留兼容别名；补齐 `.env.example`。这是「交付即踩坑」类问题，必须先解。

### 第二批（下次迭代）
4. **决策 Scheduler 去留**（P0-1）：推荐方案 A（降级为旁路 + 改文档）或 B（补 `submit` 并发门控 + `dispatch_next(execution_id)` 认领语义）。**在决策前建议先关闭 `scheduler_enabled` 并加注释注明「状态标记不可信」**。
5. **恢复 BLE001 门禁**（P0-4）：受管代码规模可控，做一次真正的逐处分类。
6. **补租户过滤缺口**（P1-5）：`memories` / `admission_queue` 加 tenant 列；`sql/pipeline.py:90` 传 workspace_id。
7. **下沉 `knowledge_lifecycle`**（P1-3）或补依赖声明。

### 第三批（排期）
8. DDL 迁移机制（P1-4）—— 引入 Alembic 或轻量版本表，工作量中等但收益长期。
9. 契约收敛（P1-1/P1-2）—— 统一错误格式与 SSE 事件、exhibition 接入 shared_schemas、收敛 CONTRACT_VERSION。
10. 向量库 GC（P1-6）+ 评测修复（P1-9）+ 凭证 fail-close（P1-8）。

---

## 六、这些发现与项目最终目标的对齐度

> 本节回答一个比"有什么问题"更上位的问题：**上述发现是否服务于项目的最终目标？**
> 结论：**核心发现不是外围洁癖，而恰好落在项目自己定义的验收标准上。真正与目标不一致的不是这些发现，而是项目当前的进度声明。**

### 6.1 项目对"最终目标"的权威定义

`docs/plans/plan-v3-execution-platform-final-architecture-2026-09-22.md:381`：

> 3. **P0 五项先做**：fencing generation → Effect Contract → ExternalTask → Scheduler Dispatch → status state machine。**这五项闭环后 V3 才算 "Execution Platform" 而非 "Agent Framework"。**

`docs/architecture/agent-execution-platform.md:64`（V3 架构基线 §1）：

> Agent Platform V3 **不以"提供一个 Agent 框架"为主要目标**，而是提供一个能够承载企业 Agent 长期运行的 **Execution Platform**。

即：**项目自己声明，"是不是 Execution Platform"由 P0 五项是否闭环来判定**，而非由模块数量或 Phase 编号判定。

### 6.2 对齐矩阵：P0 五项缺口 vs 实际状态

| # | 项目定义的 P0 缺口 | 实际实现状态 | 对应本次发现 | 对齐判定 |
|---|-------------------|-------------|-------------|---------|
| 1 | **严格 Fencing Generation**（验收：5 类 durable write 均带 `WHERE generation = ?`） | 🟡 **部分**：已见 `execution_checkpoints.generation`（`db.py:135-136`）、`execution_leases.generation`（`db.py:151-153`）、status 写入带 generation 守卫（`execution_state_pg.py:91`）。5 类中 checkpoint/status 已覆盖，external receipt / effect receipt / scheduler ownership 三类未验证 | 本次未完整验证 | 🟡 部分闭环 |
| 2 | **Effect Contract**（6 字段 + 失败分类） | 🟡 **部分**：仅 graph/workflow planner 路径生效（`execution_graph.py:337/368/377`），**默认 deterministic planner 绕过**（`config.py:104`）；总纲现状表 `:124` 自标「❌ Effect Contract 未形成」 | **P1-7** | 🟡 部分闭环 |
| 3 | **External Task + Receipt** | 🟡 **部分**：`awaitable_task` 已接线但需 Skill 主动返回 `__awaitable__` 才触发；`human_task`（External Task 的 Human 子类）**生产零调用** | **P1-7** | 🟡 部分闭环 |
| 4 | **Execution Scheduler（完整 Dispatch/Queue/Worker）** | ❌ **未闭环**：不 gate 执行（`max_concurrent` 失效）、`dispatch_next()` 无参数错标他人任务、从不 `mark_running`、伪造 FAILED 记录 | **P0-1** | ❌ 未闭环 |
| 5 | **Durable Execution Status State Machine** | ❌ **未闭环**：状态写失败全链路 `logger.debug` 静默，顶层异常无日志 → 状态机"可持久"但**不可观测、不可信** | **P0-2** | ❌ 未闭环 |

### 6.3 真正的不一致在哪里：优先级倒挂

对照 Phase 2-4 的实际交付内容与缺口严重级别：

| 已闭环 | 总纲严重级别 |
|--------|-------------|
| Control Plane（缺口 8） | **Medium** |
| Forensic / Replay（缺口 9） | **Medium** |

| 未真正闭环 | 总纲严重级别 |
|-----------|-------------|
| Fencing Generation（缺口 1） | **High / P0** |
| Effect Contract（缺口 2） | **High / P0** |
| External Task（缺口 3） | **High / P0** |
| Scheduler Dispatch（缺口 4） | **High / P0** |
| Status State Machine（缺口 5） | **High / P0** |

**Phase 2-4 优先闭环的是 Medium 级能力（ControlPane / Forensic），而 5 项 High/P0 级能力仍未真正闭环。** 这构成**优先级倒挂**：先做了容易的、可展示的，把决定"是 Execution Platform 还是 Agent Framework"的那 5 项留在了「已接线但未满足验收标准」的状态。

而 `AGENTS.md:5`（非 :3，:3 为 monorepo 行）的表述是：

> **V3 企业执行平台（Phase 2-4 + 3.4 已完成）**：执行链路升级为 `Admission → Scheduler Queue → Dispatch → Planner → Execute → Forensic/CostGov`

**这句话与项目自己的验收标准（总纲 §381）冲突**：Phase 编号推进 ≠ P0 五项闭环。按项目自己写的判定标准，当前状态仍是「Agent Framework + 大量 Execution Platform 组件」，尚未跨过 Execution Platform 的门槛。

### 6.4 分类：哪些发现与目标强相关，哪些可以降级

**A 类 — 与最终目标强一致（应当投入）**

| 发现 | 为什么与目标一致 |
|------|-----------------|
| **P0-1** Scheduler 假接线 | 直接就是 P0 缺口 4 的验收项 |
| **P0-2** 状态持久化静默 | 直接就是 P0 缺口 5 的验收项 |
| **P1-7** 4 个半成品模块 | 正是缺口 3（Human Task）/ 6（State Migration）/ 7（Payload Externalization）的待闭环部分 |
| **P0-4** lint 豁免倒退 + 文档失真 | "企业级"的前提是约束可执行、记录可信；豁免全局化使门禁失去意义 |
| **P0-3** LLM 配置分裂 | "承载企业长期运行"要求部署可复现；按文档配置即失败违反这一前提 |
| **P1-4** DDL 无迁移 | Execution Platform 的 Storage/Scale Plane（8 层第 ⑧ 层）前提 |
| **P1-5/P1-6** 租户与存储不一致 | 总纲第 9 条目标明列「统一 Tenant」 |

**B 类 — 与目标弱相关（可明确降级，不必投入）**

| 发现 | 降级理由 |
|------|---------|
| P2-6 / D1 / D5（文档口径、单字母变量、注释泛化） | 纯可读性，对"Execution Platform"叙事零贡献 |
| P1-1 契约版本号 1.0/1.1/1.2 | 属"多服务产品化"议题，非 Execution Platform 判定项 |
| P1-2 错误响应 5 种格式、SSE 事件不一致 | 同上；除非要做"多服务契约治理"叙事 |
| P2-3 WS 未接中间件、P2-2 singleflight 竞态 | 边缘路径，非核心验收项 |
| P1-10 参数默认值不一致 | 运维一致性，非架构门槛 |

**C 类 — 不是"我的发现"，而是我发现的「不一致」本身**

项目当前最大的风险不是任何一个技术缺陷，而是：**进度声明已超出验收标准的实际达成度，且该声明已写入 `AGENTS.md`（AI 与人都当作事实源）。** 这会导致：
- 后续所有规划基于错误的起点（例如继续推进 Phase 5，而 P0 五项未闭环）；
- 任何外部审视（面试、评审、协作者）在深挖执行链路时会撞上「声明与实现不符」。

### 6.5 对"最终目标"的修正建议

如果项目目标是成为**真正的 Execution Platform**（而非功能更多的 Agent Framework），建议调整投入方向：

1. **停止新增 Phase 能力**（Phase 3.4 的 4 个待接线模块已属此列），把资源转向前述 **5 项 P0 验收标准**；
2. **把 `AGENTS.md` 的 V3 状态表述改为按缺口维度描述**（如「缺口 4 已接线、验收标准未满足」），使进度声明与验收标准对齐；
3. **建立"缺口 → 验收标准 → 实测证据"的三段式追踪**，替代当前的「Phase 已完工」叙述——这也与项目已有的 `verification` 文化一致；
4. 若确需展示广度，把 B 类问题（契约/错误格式统一）作为「工程化治理」叙事单独承载，不挤占 P0 五项的资源。

---

## 七、审计方法学备注

- **未实跑全量测试**：本次以静态核查 + 定点读码为主。审计期间未执行 `make test`（10 个 pytest session），因此**未验证当前测试是否全绿**。建议在动手修复前先跑一次 `make ci` 建立基线。
- **两个已修项被复核为真**（避免误报回归）：C-12 sandbox 白名单（`sandbox.py:210`）、C-9 health_check fall-through（`health_check.py:28-35`）、B-3 子 agent 步数上限（`main_agent.py:629-634`）、C-4 SSE error 事件（`api/query_router.py:307-310`）、三处租户过滤（cache / schema_store / milvus）——**均属实**。
- **二次核查勘误（2026-09-24 复核，HEAD 仍为 `5207365`）**：① P0-1 Reaper 对 DISPATCHED 的超时实为 60s（`dispatch_timeout`）且带 lease 失效门控，非「300s」；② P0-4「courses 126 处 BLE001」经核实为 0（原始 noqa 已随 `92ba46f` 删除），受管代码 0 处的结论不变；③ P1-4「27 张表」按 `db.py` 实为 24 处 `CREATE TABLE`。三处均为数字/归因瑕疵，不影响任何定级与结论。④ 补充发现：`scheduler.complete(request_id)`（`query_router.py:319`）参数不足会抛 `TypeError` 被 debug 吞，使 P0-1/P0-2 更严重（已就地并入正文）。
- **第二批勘误（§6 代码引用复核）**：⑤ §6.3 引用执行链声明的行号应为 `AGENTS.md:5`（原写 :3，:3 为 monorepo 行）；⑥ P2 小节实为 **7 项**（P2-1…P2-7），原摘要表与小节标题写「6 项」已改；⑦ P1-2 nl2sql「异常返回 HTTP 200」行号由 `:39-44` 更正为 `:31-39`（该文件共 40 行）。另 §6.2 矩阵的代码引用经复核均成立：fencing generation（`db.py:136/153` + `execution_state_pg.py:91` status 写守卫）、Effect Contract 仅 graph 路径且默认 `planner="deterministic"`（`config.py:104`）、总纲 `:124` 自标「❌ Effect Contract 未形成」——「优先级倒挂」论点地基自洽。
- **第三批勘误（全仓穷尽式复核）**：⑧ **P2-4 为假阳性**——其声称「`workspace_id` 的 CREATE/ALTER 本仓未找到」不成立，实际就在 `db.py:54-79`（CREATE+ALTER）与 `:423`，已标为撤销（schema 真相源在代码，真正缺口归 P1-4）。其余全部代码引用项（好消息节 8 项：零依赖无环/密钥扫描 0/无大文件/.gitignore 覆盖/check_doc_sync 0 警告；P0-4 提交 `92ba46f` 标题；P1-1 HistoryItem与三值版本；P1-2 错误体与 SSE；P1-5 typed/admission/memory_pg/cache；P1-6 milvus 单例与删除/默认 backend；P1-7 接线行号与 B-5b 披露范围；P1-8 enforce_scope_filter；P1-9 mock；P1-10 双池/双客户端/端口 8900↔8000与8000↔8002；P2-1/2/3/5/6/7）经逐条核对**均属实**，行号精确命中。
- **`courses/` 目录未纳入审计**：该目录（209 文件）为第三方课程代码（尚硅谷），未被 git 追踪，不属本项目资产。本报告中所有统计均已排除该目录（例如 `noqa` 计数）。

---

## 八、修复执行记录（2026-09-24，工作树改动）

> 依 §五优先级执行。**严守 AGENTS.md「先方案后编码 + 不盲改公共契约/不擅自做产品决策」**：只落地审计已明确写清「目标/验收」的收敛项；决策门控项不盲改。

### 8.1 已完成并验证

| 审计项 | 改动 | 文件 | 验证 |
|--------|------|------|------|
| **P0-2** 补日志 | 6× `debug`→`warning`(+`exc_info`) + 顶层 `except` 补 `logger.exception` | `agent_server/api/query_router.py` | ruff / compile |
| **P0-3** 配置分裂 | `LLM_API_KEY`/`LLM_BASE_URL` 为权威名、`OPENAI_*` 保留为回退别名 + `.env.example` 注释 | `agent_federation/agent/llm.py`、`knowledge_service/core/config.py`、根 `.env.example` | ruff |
| **P1-8** 凭证 fail-close | `get_service_credential` 由 truthy 占位改为 `raise NotImplementedError` + 测试断言改为验 fail-close | `execution_context.py`、`test_execution_context_foundation.py` | pytest |
| **P1-9** 评测自洽 | 跨租户负样本改用**真实** `enforce_scope_filter` + 防空转守卫；测试改 patch 真实函数（保留越权断言） | `evaluation.py`、`test_evaluation_framework.py` | pytest |
| **P0-1** Scheduler 选 B（已拍板） | 新增请求驱动认领 `try_start(execution_id)`（InMemory+PG+门面，契约新增抽象方法）；`/query` 返回流前认领，超并发→**503**+撤销 QUEUED 行；删 `dispatch_next()` 误标；`complete(request_id, COMPLETED/FAILED)` 补终态修正 arity bug；cache-hit 早退 `cancel` 防 backpressure 虚增 | `execution_scheduler.py`、`query_router.py`、`test_execution_scheduler.py` | pytest **22 passed**（6 新）/ agent-runtime 全 **539 passed** / agent_server+api **57 passed** / ruff / compile |
| **P1-10 / P2-5** 配置文档 | knowledge `.env` `8000`→`8900`；nl2sql 端口加说明注释；exhibition 声明 `NL2SQL_SERVICE_URL` | 3× `.env.example` | check_doc_sync |
| **第一批#1** 文档失真 | AGENTS.md P0-1 口径 + P2-6 D1-D10；D7 记录 reopened；B-5b 补披露 3 个半成品 | `AGENTS.md`、`plan-tech-debt-followup`、`tech-debt-multi-agent` | check_doc_sync |

**验证汇总**：ruff 全绿；exhibition 全套 **343 passed / 1 skipped**；`query_router`/foundation `py_compile` OK；`check_doc_sync` **0 警告**。**P0-1 方案 B（产品拍板后实施）**：方案文档 `plan-p0-1-scheduler-gating-option-b-2026-09-24.md`；scheduler 全 **539 passed**（含 try_start 6 新用）、agent_server+api **57 passed**、ruff 全绿；`dispatch_next()` 仅剩注释无实调、`complete(request_id)` 单参无残留。

### 8.2 决策门控 / 需独立方案（未盲改，附就绪规格）

- ~~**P0-1 Scheduler 去留**~~：✅ **已选 B 并实现**（详见 8.1 P0-1 行 + 方案文档）。`dispatch_next()` 保留为 ControlPlane/Worker 拉取 API（语义不变）；`/query` 改用 `try_start` 请求驱动认领。
- **P0-4 恢复 BLE001 门禁**：✅ **M1 棘轮已落地**（2026-09-24）——6 份 ruff 配置均启用 `BLE001/S110`，存量入各包 `per-file-ignores` 基线，`ruff check .` 全绿且防回归探针验证生效（新盲捕获直接 fail）。方案与逐处清单：`plan-p0-4-blind-except-ratchet-2026-09-24.md` + `p0-4-blind-except-inventory.txt`。🔁 **M2 策略修订（2026-09-24，经用户复核）**：**放弃「逐点 `# noqa: BLE001` + 删文件基线」的烧法**，改回**整包 `per-file-ignores` 基线豁免 + 源码零逐点 noqa**——因逐点 noqa 的存废完全依附 `BLE001` 是否常驻 `select`，历史上被 `3ccc90e`（加）→ 移出 select → `92ba46f`（当死注释清除）反复开关，是加-删-加 churn 的根源。现态：**6 包全部源码干净 + 文件级基线豁免**（agent-core/agent-runtime 曾烧的逐点 noqa 已 `git restore` 回退、基线由 ruff 真值重建），仅保留**无 noqa 的安全窄化**（纯导入守卫 `except Exception`→`except ImportError`、`json.loads`→`except (ValueError, TypeError)`，agent-core 6 处）。agent-core `pytest 200 passed`、agent-runtime `539 passed`。D7 由「M2 烧除中」改标 **🟡 M1-only 稳态**（棘轮门禁常驻防新增，存量宽捕获为文件级豁免，不再追求逐点清零）。🔧 **真实降量轮次（2026-09-24，`plan-p0-4-blind-except-real-reduction-2026-09-24.md`）**：经用户逐站实地核查修正方案（1 处 P0 定性错 + 2 处行号/依据错）后执行——knowledge-service **桶 A 安全窄化** 5 文件 9 站点（requests/IO/import 探测/`int()`），locustfile/node_pdf_to_md/test_tracing **3 文件清零脱基线**（ks 基线 24→21），`pytest 41 passed/6 skipped`；**桶 B**（删冗余交全局 handler）实测会丢 session_id 日志上下文、收益边际→本轮跳过；**桶 C**（后台任务/SSE/探针/可选通道降级 + `import_exhibition_corpus:217` HTTP 批次降级）维持豁免。关键约束：全局脱敏 handler 实测仅 **1/6 应用**（knowledge-service）注册→仓库级大降量须先补各应用 handler（P2 独立方案）。
- **P1-5 多租户缺口**：`sql/pipeline.py:90 fetch_context` 未传 workspace_id 的调用链（`sql_agent.sql_query`→`text_to_sql`）当前**无 workspace 上下文可传**，需先把 tenant/workspace 下推到 skill 调用层；`memories`/`admission_queue` 加 tenant 列属 DDL+迁移（并入 P1-4）。
- **P1-3 knowledge_lifecycle**：knowledge→exhibition 隐式跨应用 import，收敛方向（下沉 agent-runtime / 改 HTTP / 显式声明可选依赖）是架构决策，未盲改。
- **P1-4 DDL 迁移（Alembic）**、**P1-1/P1-2 契约收敛（6 服务公共 API）**、**P1-6 向量库 GC**、**P2-2 singleflight 引用计数**、**P2-3 WS 中间件设计**、**P2-7 MinIO 出域一致性**：均需按批次走「先方案后编码」。
