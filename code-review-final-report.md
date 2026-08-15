# agent-platform 代码审核最终报告

> 生成时间：2026-08-15 00:49
> 审核范围：`D:\Study\github\agent-platform` 全量代码
> 审核维度：架构设计 / 代码质量 / 功能正确性 / 安全性 / 性能与扩展性
> 方法：两轮独立审核 + 跨 agent 交叉核验（逐文件逐行读真实代码）

> ⚠️ **时效性与准确性警告（2026-08-15 复核追加）**：本报告基于**更早代码快照**生成，部分结论已过时，引用其行号前**务必重新核对真实代码**：
> - 路径已迁移：原 `D:\Study\github\agent-platform` → 现 `D:\Study\agent-platform`。
> - 已修复项（本报告曾判定"未修复"）：**U-4** `app/infra/coordinator.py` release 已清理 `_active/_queues/_conditions`；**U-5** `app/api/routes.py:124` 已显式 `nonlocal decision`；**U-7** `deepagents/pyproject.toml` 硬依赖完整 + 四个 optional 分组，requirements.txt 23 包均已声明。
> - **U-3** `app/infra/db.py:191-197` 已新增 `_IDENT` 正则白名单（table/cols 非法即 `ValueError`），残余仅 `where` 子句值已参数化。
> - **U-1** 仅 `HealthResponse` 已对齐联邦契约；`QueryRequest` 字段不统一（`AliasChoices` 双写兼容）仍属开放项，本报告"U-1 已修复"系误报。
> - 误报澄清：wenda-data-agent 复用 `agent_core` 守卫（非重实现）；`app/` git 跟踪 `.pyc` 为 0（磁盘残留为本地构建缓存，非 git 污染）；**U-2** `app/agent/graph.py:94` 重试分支返回缺 `answer` 键属**误报**——LangGraph `StateGraph` 节点返回值为 reducer 合并语义（非整体替换），旧 `answer` 保留、`iterations` 自增触发回路由重跑，不跳过重试。
> - 已知权衡（仍成立但非紧急，不改）：**U-6** `app/infra/otel.py` jaeger exporter 在 OTel 1.x 后弃用，已有降级不崩；**U-8** `app/rag/store.py` BM25 每次查询全量重建 + 逐条 INSERT，为可接受的简单实现权衡。
> - 文档脱节（README/AGENTS 仅描述 `app/` 遗漏 9 包、配置表缺漏变量、Python 版本冲突等）已在 `README.md` / `AGENTS.md` / 各包 `.env.example` 中修正；kefu 迁移技术债（未接入网关、adapter 待废弃、atguigu_ai 未退役）已集中记录于 `README.md`「已知待拍板项」。
> - 最新逐行核实结论见随附评审清单（问题 1–8 及 U-2/U-6/U-8 仍成立项），以**最新代码**为准。

---

## 一、项目概况

| 项 | 值 |
|---|---|
| 技术栈 | Python 3.11+ · FastAPI · LangGraph · pgvector · sqlglot · pydantic v2 |
| 架构模式 | LangGraph Supervisor 单进程多节点隔离 |
| 仓库结构 | monorepo：`app/` + `agent-core/` + `shared-schemas/` + `tests/` + `eval/` + 子项目 |
| 测试覆盖 | 40 单元用例 |
| 安全基线 | 无硬编码密钥 / 无裸 except / 无不安全 eval-exec-pickle / 无路径遍历 ✅ |

---

## 二、已修复项（15 项）

### 2.1 正确性修复

| # | 文件 | 问题 | 修复状态 |
|---|------|------|---------|
| 1 | `Dockerfile` | COPY 未包含子包 | ✅ 已修 |
| 2 | `pyproject.toml` | target-version 配置 | ✅ 已修 |
| 10 | `app/infra/admission.py` | admission 死代码（enqueue 满时返回 rejected） | ✅ 已修：真正排队闭环，enqueue 满时返回 queued，wait_for_admit 真阻塞，mark_completed 用 `FOR UPDATE SKIP LOCKED` 补位 |
| 11 | `app/sql/pipeline.py` | PG 只读缺双保险 | ✅ 已修 |
| 12 | `app/infra/revert.py` | parent_config None 处理 | ✅ 已修 |
| 14 | `app/rag/embed.py` | KeyError 未处理 | ✅ 已修 |
| 16 | `app/infra/admission.py` | hasattr 守卫缺失 | ✅ 已修 |
| 17 | `app/sql/guard.py` | PG 只读双保险 | ✅ 已修 |

### 2.2 安全性修复

| # | 文件 | 问题 | 修复状态 |
|---|------|------|---------|
| 7 | `zhanggui-zhiku/.../node_*.py` | Milvus filter 表达式未 escape（5 处） | ✅ 全部已修：`node_search_embedding.py:79`、`node_search_embedding_hyde.py:117`、`node_import_milvus.py:297`、`node_item_name_recognition.py:373,520` 均使用 `escape_milvus_string` |
| 19 | `Dockerfile` | 以 root 运行 | ✅ 已修：非 root 用户 |
| 20 | `app/main.py` | CORS 配置过宽 | ✅ 已修 |

### 2.3 工程规范修复

| # | 文件 | 问题 | 修复状态 |
|---|------|------|---------|
| 4 | `app/infra/admission.py` | acquire 竞态 | ✅ 已修（拆分为可读性建议，非正确性 bug） |
| 6 | `app/infra/mcp_client.py` | TODO 未标注 | ✅ 已修 |
| 13 | `app/sql/pipeline.py` | coalesce 注释缺失 | ✅ 已修 |
| 25 | `app/config.py` | db_pool_max_size 不可配置 | ✅ 已修 |

---

## 三、交叉核验结论（4 项非共识）

| 项 | 我方原始结论 | 对方结论 | 核验结果 |
|---|------------|---------|---------|
| #10 admission 死代码 | 存在死代码 | 已修复 | **对方正确**。我方原始报告基于旧版代码失真。最新代码已实现真正排队闭环。 |
| #26 coordinator 字典泄漏 | 完全泄漏 | 已修复 | **部分修复**。有队列的 session 清理完整；无队列的 session 的 `_conditions` 条目不清理（轻微泄漏）。 |
| #4 acquire 拆分 | 竞态 bug | 可读性建议 | **对方合理**。竞态已修，拆分是可读性优化。 |
| `routes.py:129` nonlocal | 缺失会报错 | 能运行 | **能运行**。`decision` 在 `query.__code__.co_cellvars` 中（cell variable），赋值用 `STORE_DEREF` 修改外层闭包变量。但缺 `nonlocal` 显式声明，意图不明确。 |

---

## 四、未修复项（8 项，按严重度分级）

### 4.1 🔴 架构决策（1 项）

#### U-1. `app/schemas.py` 与 `shared-schemas` 契约不兼容

| 项 | 值 |
|---|---|
| 文件 | `app/schemas.py` vs `shared-schemas/` |
| 问题 | `QueryRequest`：`question` vs `query`、`thread_id` vs `session_id`；`HealthResponse` 字段集完全不同 |
| 影响 | 跨包 API 契约不一致，集成时需手动转换 |
| 建议 | 需用户拍板是否让 `app` 改用 `shared-schemas` |

### 4.2 🟡 低危（5 项）

#### U-2. `graph.py` synthesize 重试缺 `answer` 键

| 项 | 值 |
|---|---|
| 位置 | `app/agent/graph.py:94` |
| 问题 | 重试返回 `{"iterations": iterations + 1, "evidence": []}` 不含 `"answer"` 键 |
| 影响 | checkpoint 拆留可能导致跳过重试 |

#### U-3. `db.py` vector_search f-string 拼接

| 项 | 值 |
|---|---|
| 位置 | `app/infra/db.py:187` |
| 问题 | f-string 拼接 table/cols/where |
| 影响 | 当前调用方都硬编码，安全；但接口允许任意字符串，存在误用风险 |

#### U-4. `coordinator.py` `_conditions` 泄漏

| 项 | 值 |
|---|---|
| 位置 | `app/infra/coordinator.py` |
| 问题 | 无队列 session 的 `_conditions` 条目不清理 |
| 影响 | 轻微内存泄漏 |

#### U-5. `routes.py` 缺 `nonlocal decision`

| 项 | 值 |
|---|---|
| 位置 | `app/api/routes.py:129` |
| 问题 | 缺 `nonlocal decision` 显式声明 |
| 影响 | 依赖 Python 隐式闭包赋值（cell variable + STORE_DEREF），能运行但意图不明确 |

#### U-6. `otel.py` jaeger exporter 弃用

| 项 | 值 |
|---|---|
| 位置 | `app/infra/otel.py:109-114` |
| 问题 | jaeger exporter 在 OTel SDK 1.x 后已弃用 |
| 影响 | 有降级处理，不会崩溃；建议迁移至 OTLP exporter |

### 4.3 🟢 工程规范（1 项）

#### U-7. deepagents pyproject 缺 optional dependencies

| 项 | 值 |
|---|---|
| 位置 | `deepagents/pyproject.toml` |
| 问题 | 21 个包在 requirements.txt 但不在 pyproject.toml（langfuse/pandas/aiosqlite/tiktoken 等） |
| 影响 | 所有缺失包都有 try/except ImportError 降级处理，不会崩溃；但 best practice 是声明为 `[project.optional-dependencies]` |

### 4.4 🔵 性能（1 项，已知设计权衡）

#### U-8. `rag/store.py` BM25 全量重建 + 逐条 INSERT

| 项 | 值 |
|---|---|
| 位置 | `app/rag/store.py:48-54, 63-75` |
| 问题 | BM25 每次查询全量重建索引；逐条 INSERT |
| 影响 | 数据量大时性能下降 |
| 备注 | 已知设计权衡，非 bug |

---

## 五、建议优先级

| 优先级 | 项 | 理由 |
|--------|-----|------|
| P0 | U-1 契约对齐 | 架构决策，影响跨包集成，需用户拍板 |
| P1 | U-2 graph.py answer 键 | 可能导致重试逻辑失效 |
| P1 | U-5 routes.py nonlocal | 代码意图不明确，一行修复 |
| P2 | U-3 db.py f-string | 当前安全，建议加参数校验 |
| P2 | U-4 coordinator 泄漏 | 轻微，长运行场景才显现 |
| P2 | U-6 otel jaeger | 有降级，择机迁移 |
| P3 | U-7 deepagents deps | 工程规范，不影响运行 |
| P3 | U-8 BM25 性能 | 已知设计权衡 |

---

## 六、安全扫描结论

| 扫描项 | 结果 |
|--------|------|
| 硬编码密钥 | ✅ 无 |
| 裸 except | ✅ 无 |
| eval / exec / pickle / os.system | ✅ 无 |
| 文件路径遍历 | ✅ 无 |
| create_task 引用持有 | ✅ 正确 |
| SQL f-string | ⚠️ 仅 `vector_search`（见 U-3） |
| TODO 标注 | ✅ 仅 `mcp_client.py`（已标注） |

---

## 七、附录：交叉核验方法论

本轮审核采用两轮独立审核 + 跨 agent 交叉核验。核验时发现旧结论/行号易因重构过时，故采用**逐文件逐行读真实代码**的方式复核所有非共识项，确保结论基于最新代码状态。

核验关键发现：
- `routes.py:129` 的 `nonlocal` 问题通过 `query.__code__.co_cellvars` 检查确认 `decision` 是 cell variable，赋值用 `STORE_DEREF`，实际能正确运行（Python 3.14 测试通过）。
- `#10 admission` 我方原始报告基于旧版代码失真，证明交叉核验的必要性。

---

**审核闭环。** 待用户决策项：U-1 契约对齐方案。
