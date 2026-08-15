# agent-platform 代码审核 — 问题清单与事实依据（最终核对版）

> 整理目的：供其他模型独立复核。所有结论均基于逐文件精确查证，已剔除检索误报，并吸收后续复核对根报告过时项的纠正。
> 审核时间：2026-08-15｜仓库路径：`D:\Study\agent-platform`
> 配套说明：根 `code-review-final-report.md` 为更早代码快照、部分结论已过时，其顶部已加时效性警告；本报告为最新逐行核实版，引用旧报告行号时须重新核对。

---

## 一、架构与文档一致性（高优先级）

### 问题 1：README / AGENTS.md 只描述 `app/`，完全遗漏 9 个 sibling 包
- **事实依据**：
  - `README.md` "目录结构"章节（约 296–340 行）仅列 `app/`、`tests/`、`eval/`、`docs/`。
  - 仓库实际含：`deepagents/`、`dialogue-framework/`、`kefu-adapter/`、`kefu-service/`、`wenda-adapter/`、`wenda-data-agent/`、`zhanggui-zhiku/`、`agent-core/`、`shared-schemas/`（共 9 个独立包）。
  - `AGENTS.md` 同样只提 `app/`、`tests/`、`eval/`、`docs/`。
- **影响**：文档与 monorepo 现实严重脱节，新读者无法理解整体拓扑。
- **处理状态**：✅ 已修复。`README.md` 目录结构已分层（单进程平台 / 联邦网关 / 共享内核 / 业务适配包 / 测试评测）；`AGENTS.md` 目录表已列全部 13 项（10 包 + tests/eval/docs），并声明 monorepo 与 `app/` `deepagents/` 并行关系。

### 问题 2：kefu-service 已实现且 CI 通过，但联邦网关未接入（且迁移需升级协议，非简单改 URL）
- **事实依据**：
  - 网关接线 `deepagents/agent/config.py:46-50`：`customer_service` 子服务 `url=_env("KEFU_ADAPTER_URL", "http://localhost:8002")`，**仅指向 kefu-adapter，无 KEFU_SERVICE_URL 配置项**。
  - 全仓搜索 `kefu-service` / `localhost:8003`：运行期引用为 0，仅 CI 路径触发（`.github/workflows/agent-platform-ci.yml:24,45`）与文档引用。
  - 评测脚本 `deepagents/eval/run-all.py:165` 同样走 `KEFU_ADAPTER_URL`（`:8002`）。
  - `kefu-service/main.py:6` 注释写明运行端口 `8003`，`build_kefu_graph` 已实现，验收报告 `deepagents/VERIFICATION_REPORT.md:22` 显示 M7 测试 10/10 + Flow 3/3 + GraphRAG 5/5 通过。
  - **关键修正（迁移深度）**：网关远程模式走 `AsyncSubAgent`（Agent Protocol，`graph_id` + `url`），见 `deepagents/agent/async_subagents.py:8-9,23-28`；该文件注释 `:8` 自承 "M2 阶段子服务尚未升级为 Agent Protocol server"。当前 `kefu-service`/`kefu-adapter` 均为普通 FastAPI REST，**直接把 `config.py` 的 URL 指向 `kefu-service:8003` 大概率不可行**。且 `kefu-service` 返回 `list-of-{text}`（`main.py:53-66`）而非 `QueryResponse`，adapter 的转换层暂不能移除。
- **影响**：新实现写完未上线；迁移到 kefu-service **不只是改 URL**，需先把 kefu-service 升级为 Agent Protocol server（或改网关调用方式）并补齐 `QueryResponse` 契约，否则 adapter 不可删。
- **处理状态**：✅ 已完成（代码侧，提交 `1e86bf8`）。`kefu-service` 已升级为 Agent Protocol 兼容 server（新增 `POST /invoke`，返回 `QueryResponse`，依赖 `shared-schemas`；旧 `/api/messages` 保留为 atguigu_ai 兼容入口）；网关 `deepagents/agent/config.py` 新增 `KEFU_SERVICE_URL` + `KEFU_USE_ADAPTER` 开关（默认 `false` 直连 `kefu-service:8003`）；`async_subagents.py` 增加 httpx 远程回退（外部 `deepagents` 包未安装时直连 `/invoke`）；`kefu-adapter` 已加 `DeprecationWarning` 弃用标记。⏳ 剩余运维动作：外部 `atguigu_ai` 退役后删除 `kefu-adapter/` 包（无代码阻塞）。

### 问题 3：迁移计划要求"废弃 kefu-adapter"，但从未执行
- **事实依据**：
  - `deepagents/docs/refactor-plan.md:258` 明确写："④ kefu-adapter 废弃，新 kefu-service 直接是 FastAPI + LangGraph"。
  - 但 `deepagents/agent/config.py:49` 至今仍指向 `kefu-adapter`（`:8002`）。
- **影响**：计划与实现脱节，技术债未清理。
- **处理状态**：✅ 已完成代码侧准备（提交 `1e86bf8`）。`kefu-service` 已可经网关 `KEFU_USE_ADAPTER=false` 直连，无需 `kefu-adapter` 转换层；`kefu-adapter` 已加 `DeprecationWarning` 弃用标记，`refactor-plan.md` 执行状态注记已更新为"待运维执行"。⏳ 剩余：外部 `atguigu_ai` 退役后删 `kefu-adapter/` 包。

### 问题 4：老客服系统 `atguigu_ai` 未退役，且不在仓库内
- **事实依据**：
  - 名为 `atguigu_ai/` 的目录或 `atguigu_ai.py` 文件：全仓 `search_file` glob `*atguigu*` → **0 个**（老系统代码确实不在仓库内，为外部遗留服务）。
  - 字符串 `atguigu_ai` 在仓库内有 56 处引用，均为注释/文档说明迁移来源（如 `kefu-service/main.py:1`、`kefu-service/agent/graph_rag.py:1`、`kefu-adapter/main.py:1`），**不构成代码耦合**。
  - `kefu-adapter/main.py:24` `KEFU_API_URL` 默认 `http://localhost:5005` → 当前生产流量实际打到外部 `atguigu_ai:5005`。
- **影响**：迁移未完成；adapter 不能直接删除（删则客服链路断）。
- **处理状态**：⚠️ 待实施（外部系统动作，非仓库代码可解）。`kefu-service` 已可直连（无需 adapter）；`kefu-adapter` 已弃用标记。`atguigu_ai` 退役为外部运维动作，退役后删 `kefu-adapter/` 包即可（无代码阻塞）。`kefu-adapter/main.py:1-7` 顶部已加"外部依赖声明"注释。

---

## 二、契约与配置（中优先级）

### 问题 5：U-1 QueryRequest 字段名不统一（HealthResponse 部分已修复）
- **事实依据**：
  - `QueryRequest` 字段不统一仍属实：`app/schemas.py:41-54` 用 `AliasChoices("query","question")` / `AliasChoices("session_id","thread_id")` 双写兼容，证明入站字段名 `query` vs `question`、`session_id` vs `thread_id` 不统一，需手动兼容层。
  - **HealthResponse 部分已过时（原报告误判）**：`app/schemas.py:80-86` 已 `class HealthResponse(BaseHealthResponse)`；`shared-schemas/health.py:25-40` 已含 storage/llm/search/sql_backend/coordination/admission/revert/otel/mcp 全部能力标志。故 "HealthResponse 字段集完全不同" 已不成立。
  - 调用方字段使用：`app` 内部 state 用 `question`（如 `app/agent/graph.py:37,49,83`），DB 列名亦为 `question`（`app/sql/schema_store.py:27,31`）。**移除 `AliasChoices` 兼容层前需确认全部入站/出站边界已统一用 `query`/`session_id`**。
- **影响**：入站字段名仍不统一，属架构决策待拍板；但 HealthResponse 已对齐，无需再处理。
- **处理状态**：⚠️ 待拍板（架构决策，不擅自移除兼容层）。已在 `README.md`「已知待拍板项」U-1 中标注现状与 HealthResponse 已对齐，避免误判。

### 问题 6：kefu-service / kefu-adapter 缺失 `.env.example`
- **事实依据**：
  - 全仓 `.env.example` 共 5 份：根 / `deepagents/` / `dialogue-framework/` / `wenda-data-agent/` / `zhanggui-zhiku/`。
  - `kefu-adapter/`、`kefu-service/` 目录均无 `.env.example`，环境变量（`KEFU_API_URL` / `KEFU_ADAPTER_URL`）仅在代码 `os.getenv` 中给默认值。
  - `deepagents/docs/production-action-plan.md:147` 声称 `Test-Path "kefu-service/.env.example"` 应通过，但实际文件不存在 → **计划声称的完整性核查未兑现**。
- **影响**：部署缺文档，环境变量无据可查。
- **处理状态**：✅ 已修复。已新建 `kefu-adapter/.env.example`（含 `KEFU_API_URL` 默认 `:5005` + 端口）与 `kefu-service/.env.example`（标注配置继承自 `agent-core`，列端口锚点）。生产计划 `Test-Path` 现可通过。

### 问题 7：Python 版本声明冲突（实质成立，原行号有误）
- **事实依据**：
  - `pyproject.toml:6`（根）`requires-python = ">=3.11"`；`deepagents/pyproject.toml:10` 亦为 `>=3.11`。
  - `README.md:8` 徽章与 `dialogue-framework/README.md:21` 均称 "Python 3.10+"。**原清单称 "README.md:26 也称 3.10+" 有误**——`:26` 为"可复位降级"无关行。
- **影响**：安装约束与文档不一致（实际应以 `>=3.11` 为准）。
- **处理状态**：✅ 已修复。全仓 10 个 `pyproject.toml` 的 `requires-python` 均为 `>=3.11`；`README.md:8` 徽章、`AGENTS.md` 技术栈、`dialogue-framework/README.md:21`、`deepagents/docs/refactor-plan.md:431` 均已改为 `3.11+`。全仓 `*.md` 中 "3.10" 残留已清零。

### 问题 8：README 配置表缺漏大量实际变量
- **事实依据**：
  - `README.md` "核心配置 / Phase 2 配置"两表未含 `.env.example` 实际存在的：`LLM_BASE_URL`、`LLM_TIMEOUT`、`EMBEDDING_*`（4 项）、`LANGFUSE_*`（3 项）、`VECTOR_DIM`、`CACHE_*`、`MEMORY_ENABLED`、`BREAKER_*`、`RAG_TOP_K`、`SQL_MAX_ROWS`。
  - `docker-compose.yml:29-39` 实际注入 `LLM_BASE_URL` / `EMBEDDING_*` / `LANGFUSE_*`，README 配置表找不到。
- **影响**：文档不可作为部署依据。
- **处理状态**：✅ 已修复。`README.md`「核心配置」表补 15 项、「Phase 2 配置」表补 5 项，与 `.env.example` 及 `docker-compose.yml` 实际注入变量零遗漏。

---

## 三、代码质量（已据最新代码复核，多项已修复）

| 项 | 位置 | 原报告状态 | 最新核实状态 | 证据 |
|----|------|-----------|------------|------|
| U-2 | `app/agent/graph.py:94` | 未修复 | **❌ 误报（已复核）** | `graph.py:93-94` 重试分支返回 `{"iterations":..., "evidence":[]}` 缺 `answer` 键，但 `StateGraph` 节点返回值为 **reducer 合并语义**（合并进 `AgentState`，非整体替换），旧 `answer` 保留；重试判定靠 `iterations < max_iterations`（`:93`），不跳过重试。原报告"可能跳过重试"系对 reducer 语义的误读。无需代码改动。 |
| U-3 | `app/infra/db.py:191-197` | 未修复 | **部分过时（已修复大半）** | 已新增 `_IDENT` 正则白名单（table/cols 非法即 `ValueError`）；残余风险仅 `where` 子句 `:199` 仍 f-string 拼接，但值已参数化（`:202` `params`） |
| U-4 | `app/infra/coordinator.py:159-167` | 未修复 | **❌ 已修复** | release 时清理 `_active/_queues/_conditions`，注释 `:162-164` 明确覆盖 "q is None 原被跳过" 场景 |
| U-5 | `app/api/routes.py:124` | 未修复 | **❌ 已修复** | 现有显式 `nonlocal decision`（带 F823 解释注释） |
| U-6 | `app/infra/otel.py:109-114` | 未修复 | **❌ 已修复** | jaeger exporter 在 OTel 1.x 后弃用；已将 `exporter="jaeger"` 自动映射为 OTLP（`OTLPSpanExporter`，复用 endpoint），移除归档的 `JaegerExporter` 导入，旧配置仍兼容（见 `app/infra/otel.py:109-120`） |
| U-7 | `deepagents/pyproject.toml:13-54` | 未修复 | **❌ 已修复** | 硬依赖完整（`:13-36`）；observability/cache/docs/excel 四个 optional（`:39-54`）；requirements.txt 23 包均已在 pyproject 声明 |
| U-8 | `app/rag/store.py:48-75` | 未修复 | **❌ 已修复** | BM25 每次查询全量重建 + 逐条 INSERT → 已改为批量 `executemany` 插入 + BM25 索引按 `(COUNT(*), MAX(id))` 签名缓存（`_BM25_CACHE`），语料变更即失效；空表保护（见 `app/rag/store.py`） |

> 注：根 `code-review-final-report.md` 的 U-4/U-5/U-7 已修复，说明该报告基于更早代码，引用其行号时须重新核对。本报告第三、四节均已逐行重验。

---

## 四、已澄清的误报（供复核时排除）

| 前序误报 | 精确复核结论 | 依据 |
|---------|------------|------|
| "wenda-data-agent 重实现 `validate_sql` 守卫" | **否**，直接复用 `agent_core.sql.guard.validate_sql` | `wenda-data-agent/wenda_data_agent/agent/nodes/validate_sql.py:6,15` |
| "app/ 有 76 个 .pyc 污染（git 跟踪）" | **git 跟踪为 0 成立，但磁盘存在残留** | `git ls-files '*.pyc'` = 0（`.gitignore` 生效）；排除虚拟环境后磁盘仍有约 224 个 `.pyc`（`app/` 约 100 个），为本地构建缓存，非 git 污染 |
| "code-review 报告 U-1 已修复" | **否**，U-1 的 QueryRequest 字段不统一仍属开放项（仅 HealthResponse 已对齐） | `code-review-final-report.md:71` + `app/schemas.py:41-54` |
| 原清单 "README.md:26 称 3.10+" | **行号有误** | `:26` 为"可复位降级"无关行；实际见 `README.md:8` 徽章 |
| "U-2 重试缺 answer 键会跳过重试" | **否**，为 LangGraph reducer 合并语义误读（见第三节 U-2） | `app/agent/graph.py:93-94` + `StateGraph` 合并语义 |

---

## 五、已确认无问题项

- `shared-schemas` / `agent-core`：被 `app/` 正确复用，非死代码。
- `app/` 内部命名：全 snake_case，一致。
- 安全扫描（根报告第六节）：无硬编码密钥 / 裸 except / eval-exec-pickle / 路径遍历。
- `validate_sql` 守卫逻辑：全仓唯一实现（`agent-core`）。
- `.gitignore`：已正确忽略 `.env` / `__pycache__` / `*.pyc`，**git 无编译产物污染**。

---

## 六、建议复核模型重点验证

1. **问题 2 的修复深度（已完成，供验证）**：提交 `1e86bf8` 已将 `kefu-service` 升级为 Agent Protocol 兼容 server（新增 `POST /invoke` 返回 `QueryResponse`，依赖 `shared-schemas`），网关 `config.py` 新增 `KEFU_USE_ADAPTER` 开关（默认 `false` 直连 `kefu-service:8003`），`async_subagents.py` 增加 httpx 远程回退。请验证：直连路径下 `customer_service` 子服务经 `KEFU_SERVICE_URL/invoke` 返回 `QueryResponse` 是否正常；以及 `KEFU_USE_ADAPTER=true` 时仍走 `kefu-adapter:8002` 的兼容路径。
2. **问题 5（U-1）的取舍**：`schemas.py:41-54` 已用 `AliasChoices` 双写兼容；移除兼容层需确认所有调用方（尤其 `app/api/routes.py` 入站解析）及 DB 列名（`question`，`app/sql/schema_store.py:27`）已统一用标准名。HealthResponse 已对齐，无需处理。
3. **根 `code-review-final-report.md` 时效**：`:4` 路径确为旧 `D:\Study\github\agent-platform`，`:60` 自承部分结论基于旧代码失真——其 U-4/U-5/U-7 已修复、U-3 已加白名单均证明此点；本报告第三、四节已逐行重验，引用该报告行号时务必重新核对。
