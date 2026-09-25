# TODO / 待办清单

> 从 `README.md`「路线图」章节拆分独立维护：README 只保留阶段性摘要与指向本文件的链接，本文件是当前仓库**所有已识别但未落地的待办项**的唯一真相源，按来源分组。
>
> 除标注「非阻塞，可随日常改动顺带处理」外，均遵循红线「所有代码优化/重构必须先制定方案」（见 `AGENTS.md`），动工前需先出独立方案文档。

## 1. 前端界面（缺口最大项）

现状盘点（本仓库未追踪任何 `package.json` / Vue / React 工程，`courses/zhanggui-wenda/data-agent-fronted` 仅为课程脚手架，本地未入库）：

| 应用 | 当前形态 | 待办 |
|------|---------|------|
| `agent_server` | ❌ 无独立前端代码；`config.py` CORS 默认允许 `http://127.0.0.1:5173`（Vite 开发服务器），但仓库内无对应工程 | 需新建 SSE 流式对话控制台，复用 `/query`（SSE）+ `/history` + `/session/revert` 现有接口 |
| `agent_federation` | ❌ 无前端；`docs/plans/skill-consolidation-inventory.md` 标注「保留 HTTP 壳（WS + 文件上传/下载）供前端直连」，但直连方尚无实现 | 需基于已就绪的 `serialize_stream_event` 统一 schema（见 `CHANGELOG.md`「WS 出口统一收尾」）做多 Agent 会话界面 |
| `exhibition-agent` | 🟡 已有 `static/index.html`（235 行单文件暗色控制台，仅覆盖 skill 调试） | 需产品化；且依赖第 3 节 `skill_router` 接线后才能展示统一门禁/route 拦截反馈 |
| `kefu-service` | ❌ 无前端 | 需接入联邦 `/invoke`（Agent Protocol）的客服会话窗口 |
| `nl2sql-service` | ❌ 无前端 | 需自建问答式 SQL 数据面板（查询构建 + 结果可视化）；课程脚手架仅作参考，不直接引入 |
| `knowledge-service` | 🟡 已有 2 个静态页（`import_process/page/import.html` + `query_process/page/chat.html`），未组件化 | 需补：知识库列表 / 生命周期状态机可视化 / 多租户 ACL 管理页 |

待办拆解（需独立方案）：
- [ ] 前端技术栈选型（未定，需按 `AGENTS.md`「框架选型规则」评估成熟度，不预先绑定 Vue/React）
- [ ] 各应用前端 ↔ 后端错误契约对齐审计：`{detail}` 语义码目前是前端要解析的形状，须先于 `docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md` 的 D-2/D-4 后端收敛决策落地，避免后端改契约打破前端
- [ ] 若引入前端工程，需同步补 CI 门禁（当前 `make lint`/pytest 仅覆盖 Python 侧，前端代码漂移将无人拦截）

## 2. V3 企业执行平台验收缺口

来源：`docs/plans/plan-v3-execution-platform-final-architecture-2026-09-22.md` §6 缺口清单（架构真相源，此处仅索引优先级，不重复展开）：

| 缺口 | 内容 | 优先级 |
|------|------|--------|
| 1 | 严格 Fencing Generation：fencing 边界需覆盖 5 类 durable write（checkpoint / execution status / external task receipt / side effect receipt / scheduler ownership），当前仅防 checkpoint stale write | High |
| 2 | Effect Contract：`SideEffectStore` ≠ 语义契约，缺 delivery/retry/recover 分类 | High |
| 3 | External Task + Receipt：未独立持久化，crash recovery 无法查询外部系统真实状态 | High |
| 4 | Execution Scheduler：仅有 Admission 容量门控，缺 priority / fairness / backpressure / stuck / reschedule | High |
| 5 | Durable Execution Status State Machine | High |
| 6 | State Schema Version / Migration（V3-6 Layer B） | Medium |
| 7 | Large Payload Externalization（V3-6 Layer B） | Medium |
| 8 | Control Plane：底层数据/Replay 已有，缺 pause/resume/cancel/retry/requeue/recover/inspect/terminate 可操作面 | Medium |
| 9 | Replay Forensic / Reproducibility：Trajectory 未记录 model/prompt/skill/policy version | Medium |
| 10 | Skill Version / Lifecycle / Compatibility：Skill 热更新会破坏 Runtime Replay / Checkpoint Recovery / Workflow | Medium |

- [ ] 端到端双实例物理故障转移验收：`scheduler_enabled` 默认 `False`（渐进式开启，见 `AGENTS.md` V3 口径），缺口 1~5 未闭合前不得翻转为已上线能力声明

## 3. 未接线半成品转正（P1-7 已标注，同「未接线≠死代码」教训，禁止直接删除）

- [ ] `human_task` / `execution_recovery` / `state_migration` / `payload_externalization`（`agent-runtime`，代码完整但主链路未接线）
- [ ] `skill_router`（exhibition-agent）：已实现 Skill→Tool 统一路由 + scope 校验 + readiness 拦截，但当前各 Skill 内部直连 `WarehouseClient` 绕过门禁链；接线方向：`run_skill → route(skill_name, ctx, **params) → 执行`
- [ ] `agent_server` `/health` 端点（`api/health_router.py`）未上报 V3 组件状态（scheduler / control_plane / cost_governance / forensic），现有字段仅覆盖 Phase 1/2；属小范围可读性补齐，非阻塞

## 4. 会展 Agent 业务功能骨架 TODO

来源：`docs/tech-debt/tech-debt-audit-2026-09-22.md`（约 15 处 `TODO(...)` 标记，均为未落地功能占位，非技术债）：

- [ ] F1-D：Vault/KMS 凭证后端接入（`execution_context.py`）
- [ ] F2：真实 LLM 连接接入（`model_router.py` / `data_egress.py`）——数据分级出域模型路由，需产品决策输入
- [ ] F01：`enforce_scope_filter` 落地（`evaluation.py`）
- [ ] F02：READY 数据源连接（`production_readiness_gate.py`）
- [ ] F03：同具体性不同租户样本规则
- [ ] nl2sql-service 通用化后填充具体端点（`skills/data_analysis/skill.py`）

## 5. 技术债 Low 优先级跳过项（非阻塞，可随日常改动顺带处理）

来源：`docs/plans/plan-tech-debt-followup-2026-09-22.md`（D2/D3/D6/D9/D10 已完成，不列此）：

- [ ] D1：产品代码单字母变量改语义名（全仓散布，纯可读性，风险高于收益，仅随包内其它改动顺带）
- [ ] D4：ruff `ignore` 存量基线逐包收窄（需逐条评估删除后是否仍违规）
- [ ] D5：`agent_core` 历史溯源注释泛化改写（81 处中多数有档案价值，需人工逐条判断）
- [ ] D7：裸 `except Exception:` 存量按 ratchet 基线逐文件烧除（门禁已常驻防新增，见 `docs/plans/plan-p0-4-blind-except-ratchet-2026-09-24.md`；不追求逐点清零）
- [ ] D8：`zhanggui-zhiku/core/config.py` 评估迁移 pydantic-settings

## 6. 待评估架构决策（未立项，动工前须先出方案，红线：禁止直接动手改代码）

- [ ] `ExecutionContext` 是否迁移到 PyJWT + 标准 JWT（契约变更，需先审计下游消费者）
- [ ] Milvus 与 pgvector 双向量库长期是否统一（当前 knowledge-service 用 Milvus，agent-core/agent-runtime 默认 pgvector，见 P1-6 双库现状说明）
- [ ] U-1：`QueryRequest` 入站字段名（`query`/`question`、`session_id`/`thread_id`）双写兼容层能否移除（见 `README.md`「已知待拍板项（技术债）」）

## 7. 检索 / 存储增强

- [ ] LightRAG 式图谱增强检索
- [ ] MySQL 业务库支持（当前仅 pgvector/PostgreSQL 单栈）
- [ ] 多租户（当前仅 `TENANT_ID` 环境变量粗粒度区分，缺租户级配额/隔离/计费）

## 8. 外部条件依赖项（非代码缺口）

- [ ] agent_federation R1 漂移门禁真实基线（`evaluation/fed_latest.jsonl`）：本地开发环境无 LLM API key，无法生成；需在有 key 的环境执行一次 `uv run python -m agent_federation.evaluation.run_eval --baseline evaluation/fed_latest.jsonl` 锁定基线，之后 `--compare --fail-below` 才能作为 CI 门禁生效（比对逻辑本身已通过单测覆盖，无缺口）
