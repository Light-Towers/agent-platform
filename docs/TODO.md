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
- [x] CodeQL Batch 6（已执行，方案 `docs/plans/plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md` §9）：kernel `agent_core/guardrails/fs.py` 的 `safe_join`/`resolve_within`/`safe_filename` 不被 CodeQL 内建模型识别为 sanitizer，主干重扫报出 `#23`/`#40`/`#41`/`#42`。已新增仓内模型包 `.github/codeql/extensions/agent-platform-python/`（`barrierModel` + `barrierGuardModel`）。**两个原预设已被推翻**：（一）无需从 default setup 切 advanced setup——仓级包放 `.github/codeql/extensions/` 即被自动加载，“只接受已发布包”的限制只适用组织级扩展；（二）`#43`/`#44`（`py/clear-text-logging-sensitive-data`）**不在可自定义的 sink kind 清单内**，无 barrier 可写，“保留取证 + dismiss”是技术上唯一选项（非风格偏好）。待验：合入后主干重扫确认 `#23` 闭合。——**已验收（PR #36 合入 `0bc5175`，主干重扫 open 9 → 6）**：`#23`/`#40`/`#41` 均 `state=fixed` 自动闭合（反证模型包真被 default setup 加载）；`#42` 仍 open 且经分析为结构不可消除（`resolve()` 必须在 containment 检查之前，guard 建模无法覆盖），详见方案 §9.1。剩余待做：模型包非空转自证（删 barrier 行→重扫必复报 `#23`）。
- [ ] R19（GitHub issue #23）：FastAPI ≥ 0.142 **原生 telemetry 默认开启**，与 kernel `TracingMiddleware` 对同一请求各建一个同名 SERVER span（互为兄弟），且框架自行 `trace.set_tracer_provider()`——属本仓「第二状态机/双实现」反模式在框架层重现。默认取最小改动：`build_api_app` 内 `FastAPI(telemetry={"tracing": False})` + `scripts/lint_architecture.py` 新增门禁（裸 `FastAPI(` 未关 telemetry 即 CI 失败）；动工前需确认框架无其它自配 provider 残留路径，并做真集群端到端复验（见 `docs/plans/plan-observability-global-remediation-2026-09-29.md` §18）

## 7. 检索 / 存储增强

- [ ] LightRAG 式图谱增强检索
- [ ] MySQL 业务库支持（当前仅 pgvector/PostgreSQL 单栈）
- [ ] 多租户（当前仅 `TENANT_ID` 环境变量粗粒度区分，缺租户级配额/隔离/计费）

## 8. 外部条件依赖项（非代码缺口）

- [ ] agent_federation R1 漂移门禁真实基线（`evaluation/fed_latest.jsonl`）：本地开发环境无 LLM API key，无法生成；需在有 key 的环境执行一次 `uv run python -m agent_federation.evaluation.run_eval --baseline evaluation/fed_latest.jsonl` 锁定基线，之后 `--compare --fail-below` 才能作为 CI 门禁生效（比对逻辑本身已通过单测覆盖，无缺口）
- [ ] Code Scanning 存量（**已取消 dismiss 通道，逐条真修**；约束与逐条定性见 `docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md`）：
  - **已真修并自动闭合**（`state=fixed` 且 `dismissed_at=None`，未人工点过任何 dismiss）：`#34`（灰度分桶 MD5 → SHA-256）、`#43`/`#44`（`fs.py` 拒绝日志不落任何路径文本）、`#47`（`fs.py` `py/path-injection`，Batch 7c 按官方形状真修：`os.path.normpath` 词法定形 → `startswith` 带分隔符边界守卫 → 才 `resolve()`；PR #39 合入 `bb46dd3` 后主干重扫确认**真消失且无新号重开**）。教训已入库：`#42` 当时只是**位移重开**（同一语句换行号），`state=fixed` 不等于已修，必须比对 sink 语句本身。
  - **已真修并自动闭合**（`#48`，`.github/workflows/ha-assembly.yml:30-56`，`actions/missing-workflow-permissions`）：v3 合流新增的 workflow 未声明顶层 `permissions:`，GITHUB_TOKEN 回落组织默认读写。已按三层齐备真修：workflow 补齐 `contents: read`（仓库既有约定，其余 3 个根 workflow 均已在位）+ 新增 **P11 lint 不变量** + 17 条治理用例（含「剥掉权限块必须立刻红」的回归锁）。方案见同文档 §7。**主干复验已达成**：PR #42 合入 `9ee0000`@13:41:19Z 后，`refs/heads/main` 实跑为 **open 2 / fixed 44 / dismissed 0**，`#48` `state=fixed` 且 `fixed_at=13:42:00Z`、`dismissed_at`/`dismissed_by` 全 `None`（自动闭合），最大告警号仍 48、合入后新建 0；主干 push 的 `ci`（含 P11）success。
  - **未解・`#38`/`#39`**（kernel `guardrails/auth.py`）：不是算法选错，而是「把 API Key 摘要成会话标识」这个模式本身（持 key+pepper 即可推出 thread id、换钥断会话），与 ADR-0007「服务端断言租户身份」冲突。`py/weak-sensitive-data-hashing` 不在可建模 sink kind 清单 → **只能改契约**。**已拍板走 principal_id 化**（认证后用服务端签发/存储的不透明主体 id 派生 thread id，密钥不再进哈希）；**前置已就位**：v3 身份层（`agent_runtime/identity.py` + `IdentityMiddleware`，ADR-0007）已于 PR #41 合入 main。**但『直接落在已断言主体上』这句乐观，已取证订正为两处硬约束**：`server_user_id()` 全仓**零生产消费者**（能力存在但从未接线），且联邦 `api/identity_bridge.py:16-18` **显式丢弃 user**。【进度的更新：链② 已由 B7b-2 拆除、链③ 已由 B7b-1 拆除，上述两硬约束只卡链①（B7b-4）。】
  - **B7b 方案已立、三项已拍板，B7b-1 / B7b-2 已实施**：`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md`。强制前置（拉 CodeQL 上游源码定触发条件）**已完成**：`#38`/`#39` 触发当且仅当「一个 `password` 分类的值流入摘要的被摘要位」（`sha256` 属 strong 算法，只在 `ComputationallyExpensive` 分支成汇）⇒ **三条链都得拆**（会话身份 / 限流桶 / LLM provider 缓存键），只改会话身份不够；`#39` 改为**枚举现存 `thread_id`** 而非从密钥复算。三项拍板（2026-10-01）：Q1 租户级 / Q2 复用身份层三态 / Q3 链③纳入 ⇒ 本批只需 B7b-1/2/4/5 四个 PR。**B7b-1（链③）已实施（2026-10-02）**：`llm/registry.py` 的缓存键改进程内不透明 slot id，删 `_hash_api_key` 及其对 `fingerprint` 的 import ⇒ `#38` 三源去其一；**单独合入不会消 `#38`（预期中间态，非失败）**，剩下链①（B7b-4）与链②（B7b-2）。已开 PR **#45**；该批初版自引入一条真告警（`py/clear-text-logging-sensitive-data` high：把 slot id 写进了 `logger.debug` 实参，而 slot 由凭据数据流而来；只在 PR 面，未进主干），已按「不 dismiss、拆 sink + 加守门」真修（PR 的 CodeQL check 已 fail → pass），并补了凭据不入日志 sink 的 AST 守门用例（详见 `CHANGELOG.md` B7b-1 自纠 5）。**B7b-2（链②）已实施（2026-10-02，PR #46）**：`resolve_client_key` 删 `key:{fingerprint(provided)}` 分支**并连 `headers`/`auth_enabled` 两个形参一并删**（新签名 `(client_host, subject=None)`）⇒ 凭据类型层面进不了限流桶；桶键改「服务端断言主体优先 → IP 兜底」，主体因红线 1 不能由 kernel 自取 ⇒ `SecurityGuardsMiddleware` 新增 `subject_provider` 注入，**取证后只 ks 接得上**（其 `TenantHeaderMiddleware` 比 guards 更外层；联邦接线序对调归 B7b-4，`agent_server` 不用该中间件）。行为代价已写破：同密钥客户端不再共桶（按 IP 独立），但**换 IP 可重置配额**（旧实现不可）⇒ 限流强度实质下降，**已拍板不恢复「每密钥配额」语义**（方案 §8 Q4，2026-10-02；将来若运维确需，用服务端可验证的密钥 id 而非凭据摘要另开子项）。新增 AST 语义门禁：`auth.py` 内调 `fingerprint` 的函数集合必恰为 `{derive_thread_id}`（B7b-4 拆完链①应改 `== set()`）。⇒ `#38` 三条链已拆两条，**剩链①（B7b-4）未拆即不闭合**（预期中间态）。本批 PR 面告警闭环已实取（check-run `110690703578`：“No new alerts in code changed by this pull request” + annotations 空），`ci`/`ha`/`assembly` 均 pass。**PR #46 已合入（merge `76589c4`）并已过主干复验 PASS**（`refs/heads/main` 实取：链② 具名节点所在通路 **1 → 0**、`#39` 未受影响、`dismissed` 0、最大告警号 48 不增、合入后新建 0；脚本 `.codeartsdoer/temp/verify_main_b7b2.py`）。【口径订正】原写「password 分类源从 2 降为 1」不可用：实测同一 sink 上单条链就被枚举成多个源节点，拆掉整条链后**通路总数不变**（4 → 4）⇒ 逐 PR 判据改用「链的具名节点集合」，见方案 §7.7。详见 `CHANGELOG.md` B7b-2 段。
  - **B7b-4 前置取证受阻（2026-10-02 登记，未跑通）**：方案 §9 的「部署侧前置核实」两条命令（枚举 `checkpoints` 里存量 `user-*` thread_id + 核 `updated/`、`output/` 目录）**至今未实跑**，故「兼容窗口要不要迁移」仍是未知，**B7b-4 不得当作可开工**。现象：`root@192.168.100.126` TCP 22 可达但连接在 **banner 交换前**被关闭（`kex_exchange_identification: Connection closed by remote host`），发生在任何认证之前 ⇒ 与本地密钥/`authorized_keys` 无关，属服务端侧限制（fail2ban / `hosts.deny` / `MaxStartups` 一类）；跨约 25 分钟含 220s 与 8min 冷却共 4 次同签名，按已入库经验停止硬连。本机替代路径同样不通：主 `docker-compose.yml` 不发布 5432、HA compose 只绑 `127.0.0.1:5433`，且本机无 docker 无 `.env`。⇒ 需部署侧代跑或在服务器上恢复 sshd 通路。（2026-10-02 本批次收尾时再试 1 次，同签名 `Connection closed by 192.168.100.126 port 22`，仍未跑通 ⇒ 结论不变：B7b-4 不可开工。）
  - **主干告警面最近一次复验取证（2026-10-02，闭合于 tip `a53cf29` = PR #56 第三轮登记合入后，同脚本在新 tip 重跑仍 PASS）**：**open 恰 `#38`/`#39`**（`auth.py:103` col 47-69 / `:128` col 29-60，行号相对旧文档的 `:92`/`:117` 已位移 +11，由 PR #49 那批加 docstring 造成，与本批无因果）、`fixed` 44 / `dismissed` **0**、最大告警号 **48** 不增、合入时刻后新建 **0**、两条告警的实例 sha 均 = `a53cf29c…`（重扫确已发生在新 tip，两条 analyses 落 `12:37:46Z` / `12:38:35Z`）、Dependabot `state=open` = **0**。取证脚本 `.codeartsdoer/temp/verify_main_rescan_54.py <merge_sha> <pr_number>`（含「门禁预期集按本批 changed paths 派生」与 Dependabot 面两条判据），详情入台账 `docs/plans/plan-branch-disposition-2026-10-01.md` **§9.6 / §9.7**（含合入后 6 秒就复验会得到假 FAIL 的时序教训）。【**指针语义订正，本节为闭合态**】本行（及 CHANGELOG 同批条目）里出现的 sha 一律只代表**取证时刻的 tip**，不构成「主干至今无漂移」的持续断言——任何一次合入都会使它失去时效，而**登记动作自身被合入的那一刻，就把自己写下的 tip 变成了旧值**（§9.6 写 `10c8629`，它自己经 PR #56 入主干后主干即 `a53cf29`）。⇒ 结论：此类指针不随每次合入追改，判据必须在待验证的 tip 上重跑脚本才算成立。
  - 提醒：告警处理**按 ref 生效**，只在 PR 上做过不算，必须在 `refs/heads/main` 重扫后复验。
- [ ] 依赖安全告警（Dependabot alerts）**不在仓内任何门禁的覆盖面内**（新盲区，2026-10-02 登记）：`make ci` 只看 CodeQL，`ci` 也不读 Dependabot alerts API ⇒ 这类信号目前只能靠 `git push` 的远端回显带出（本批 8 条 high 就是这么发现的）。已完成：8 条全为 `pypdf`（direct，解析上传件时的资源耗尽类，消费面 `agent_server/api/import_router.py:59` 与 `agent_federation/tools/upload_file_read_tool.py:16`），**PR #51**（6.16.1 → 6.19.0）合入 `baa965f`@11:28:03Z 后实测 `state=open` 归零、8 条均 `state=fixed` 且 `dismissal_data=null`（未走 dismiss）；PR #54 合入后的 `10c8629` 上再验仍为 0（未回退）。待评估（需先定方案）：是否新增一条夜间/PR 门禁查 `dependabot/alerts?state=open` 并在非零时失败（属「三层齐备」的强制门禁层缺位）。另：minor-and-patch 组更新被本仓 **L-4 连续如实拦下两次**——原 **PR #52**（14 项）ci 红后由 **dependabot[bot] 自行关闭**（`timeline` closed 事件 actor=`dependabot[bot]`/type=Bot，`closed_at=11:59:36Z`，`merged=false`），同一时刻它重算组集开出替代 **PR #55**（13 项，分支 `minor-and-patch-f18118ef2b`），ci 于 12:01:16Z 以同一条 L-4 消息再红（`ha`/`assembly` pass）。根因都是它把根 `pyproject.toml` 的 `opentelemetry-api` 抬到 `>=1.45.0` 而 `packages/agent-core` 仍 `>=1.24`（主干当前两处一致均 `>=1.24`）⇒ 待办不是「等哪个 PR 变绿」，而是本仓先按 `plan-observability §3.3` 归一下界（独立决策面，需先定方案）。
- [ ] 部署侧安全项：设置 `AGENT_PLATFORM_SECURITY_PEPPER`（一经使用勿再变更，否则会话身份整体漂移），并先 dry-run `scripts/migrate_thread_identity.py` 再决定是否 `--apply`。
- [ ] GitHub 侧 Copilot「Code scanning AI findings」工作流恒失败（非本仓代码问题，只登记）：Actions 列表里每条 PR 的 push 都会多出一个 `GitHub Advanced Security / Code scanning AI findings on PR #N` 红 X，日志根因为 `CAPIError: 400 The requested model is not supported`（autofind 请求模型被拒，平台侧）。与 diff 内容无关：最近 60 次运行窗口内共 7 条同名失败（PR #33 上 6 次 + PR #34 上 1 次），而同一窗口的 `Push on main` 与 Dependabot dynamic 运行均 success。（取证 check-run `110254555532`，annotations 仅“Process completed with exit code 1”，无代码告警）。该 check 未挂为 PR 状态检查，不阻塞合并；但看到红 X 时勿误读为“安全扫描发现漏洞”。若要消掉：在 GHAS 设置关 AI findings 分析，或等平台侧模型可用。
