# 跨项目接口契约：mingyang-warehouse ⇄ agent-platform

> 🔗 **本文件是副本。**
> **主本**：`mingyang-warehouse/docs/superpowers/specs/2026-09-20-cross-project-interface-contract.md`（v1.0）
> 改动请**先提 PR 到主本**，再同步回此处。**请勿直接编辑本副本**（会与主本漂移，见 C-§2 版本策略与 D5）。

| 项 | 内容 |
| --- | --- |
| 契约版本 | **1.3**（v1.2 → v1.3：两项目边界纠正，知识平台/F01-F06 从 warehouse 迁到 agent-platform） |
| 甲方（Domain / Data） | `mingyang-warehouse`（本体 / DDL / 领域 API → 纯数据服务，不做 agent/AI） |
| 乙方（Foundation / Platform） | `agent-platform`（LangGraph Supervisor 编排、HITL、可观测、评测、Model Router、知识平台、Metric Registry、F01-F06 Foundation） |
| 状态 | 🟡 草案 · 待双方确认 |
| 依据 | 主方案 §2.2 三层责任边界 / §2.2.1 ExecutionContext / INV-3,6,8,10 / F01–F06 |
| 主本位置 | `mingyang-warehouse/docs/superpowers/specs/` |
| 副本 | **本文件**（`agent-platform/docs/architecture/`），两边以版本号对齐 |

---

## 0. 定位与红线

> 两项目**独立 repo、独立演进**。唯一的耦合点是本契约。
> **只有本契约变更才需要双方协调**；各自内部重构不得影响对方。

```
agent-platform（编排 / HITL / 评测 / Model Router / 知识平台 / Metric Registry / F01-F06 Foundation）
        │  ① ExecutionContext 下发   ④ HITL 回调 / trace 回传
        │  ② Skill 调用（HTTP / MCP）
        ▼
mingyang-warehouse（领域 API → 纯数据服务，不做 agent/AI）
```

### 🔴 红线（违反即视为架构事故）

1. **不直连库**（INV-6）——agent-platform 只能经**领域 API / MCP** 访问 warehouse，禁止拿到 MySQL 连接串。
2. **数仓不加 `tenant_id`**（§2.2 边界铁律 1）——租户/身份/权限全在平台侧（F01），warehouse 业务表不得新增身份列。
3. **不得用"拷贝代码"替代契约同步**——平台未成熟期靠本契约解耦，不得 vendor 快照。
4. **平台不得自选模型绕过数据分级**（F02 / §17.5）——`classification` 由 warehouse 标注，由平台 Model Router 消费。

---

## 0.5 v1.0 → v1.1 → v1.2 变更

### v1.0 → v1.1（澄清集，来自 exhibition-agent 骨架实现反馈）

> 本版为**草案澄清集**，不改变既有字段语义的破坏性变更，仅补全"未定义/待定"条款，使骨架实现可无歧义落地。

| # | 反馈点（来自执行 agent） | v1.1 结论 |
| --- | --- | --- |
| 1 | §2.1 目录布局 vs 参考实现（任务卡写 `src/exhibition_agent/`，参考实现 flat） | **采用 flat layout** 对齐 `wenda-data-agent`（任务卡 §2.1 同步改；契约不约束 Python 包布局） |
| 2 | C1 自报 `tenant_id` 传递位置未定义 | **检测位置 = 请求 body `params.tenant_id`**；与 `context.tenant_id` 不一致 → 403 |
| 3 | C1 exhibition/venue 级资源判定未定义 | **路径含 `/exhibition/` 或 `/venue/`，或 skill 前缀 `exhibition.`/`venue.`** 即资源级；空 scopes 访问 → 403 |
| 4 | C2 `DATA_NOT_CONNECTED` 场景未列入 mock | 错误码已存在（1.0）；**任务卡 §2.6 补该 mock 场景**（答"待接入"，INV-10 口径不可绕过） |
| 5 | C4 `error_code` 必填性张力（"缺一不可" vs "如有"） | **`error_code` 仅出错时必填，其余 10 字段恒必填** |
| 6 | D1 JWT 验签密钥注入方式未定义 | **mock/自测仅解析 payload 不验签**；生产密钥注入方式为 v1.1 开放项（§4 D1） |
| 7 | C2 知识类响应判定未定义（citations 可选） | **知识类 = `sources` 含 `type:knowledge`** → `citations` 必填，平台拒绝展示缺失者（groundedness） |
| 8 | 权限校验让测试难做（前期可否不加 / 测试环境不强校验） | **校验恒开 + 身份来源可插拔**：`STRICT`/`DEV` 两档，**不设 `OFF`**；环境只切身份来源与验签，401/403 与 scope 下推在所有环境执行。**角色层级 / 权限后台延后**，本次只按 `scopes` 判定，`roles[]` 保留可留空 |
| 9 | 实现侧新增 `REQUEST_CONTEXT_BROKEN`（400）但 v1.0 错误码表漏列 | **补进 C2 错误码表**（新增错误码 = minor，按版本规则单边可发）；实现侧须同步补进本地 `ErrorCode` enum 与 HTTP 映射 |

### v1.1 → v1.2（F-S1-05 修复，2026-09-21：C2 统一信封 → 直接 REST）

> **背景**：v1.1 走 `POST /api/v1/skills/{name}` + 统一信封，但真实 warehouse（mingyang-warehouse，48 个 REST 端点）无该路由，真实调用 404；mock 掩盖此缺口。
> **决策**：修订契约本身（非豁免 exhibition-agent 偏离架构），C2 从「统一信封 + skill invoke」改成「直接 REST + 平台侧自组装 SkillResult」。
> **方案**：`docs/plans/plan-fix-f-s1-05-contract-revise-to-rest.md`

| # | v1.1 | v1.2 结论 |
| --- | --- | --- |
| 1 | C2 调用方式：`POST /api/v1/skills/{name}` + 信封 body | **直接调 warehouse REST 端点**（`GET /api/venue-schedule` 等 48 个端点） |
| 2 | C2 响应格式：统一信封（readiness/classification/sources/citations 强制） | **REST JSON**；平台侧自组装 SkillResult（readiness 从 `data_readiness.level` 映射，classification 默认 INTERNAL，sources 从端点路径推导） |
| 3 | C2 错误映射：信封 `error.code` → ContractError 子类 | **HTTP 状态码 + body.error.code** → ContractError 子类（401/403/404/422/429/502） |
| 4 | INV-10 落地：信封 `8error.code = METRIC_NOT_VERIFIED` → 答"待接入" | **双轨**：422 错误码 + 200 `data_readiness.level=pending` → 答"待接入" |
| 5 | C1 ExecutionContext | **保留不动** |
| 6 | C4 trace（11 字段） | **保留不动** |
| 7 | envelope.py 含 SkillRequest/SkillSuccessEnvelope/SkillErrorEnvelope | **移除信封模型**，保留 Readiness/DataClassification/EgressDecision/Source/Citation（平台侧自组装用） |

### v1.2 → v1.3（两项目边界纠正，2026-09-22：知识平台/Metric Registry/F01-F06 从 warehouse 迁到 agent-platform）

> **背景**：v1.2 §0 将"知识平台 / Metric Registry"列在 warehouse 侧，但 warehouse 定位是纯数据服务，不做任何 agent/AI 内容。warehouse 侧新增的 F01-F06 脚手架 + skill_router + tool_catalog + skills/ 放错了位置。
> **决策**：将 warehouse 侧所有 agent 相关代码迁移到 agent-platform（`exhibition_agent/foundation/`），建立两项目清晰边界。
> **方案**：`docs/plans/plan-exhibition-p0-p1-landing.md` §2.0 迁移批次

| # | v1.2 | v1.3 结论 |
| --- | --- | --- |
| 1 | §0 甲方：warehouse（本体 / DDL / 领域 API / Metric Registry / 知识平台） | **warehouse（本体 / DDL / 领域 API → 纯数据服务，不做 agent/AI）** |
| 2 | §0 乙方：agent-platform（编排 / HITL / 评测 / Model Router） | **agent-platform（编排 / HITL / 评测 / Model Router / 知识平台 / Metric Registry / F01-F06 Foundation）** |
| 3 | F01-F06 脚手架在 warehouse 侧 | **迁移到 `exhibition_agent/foundation/`**（execution_context / data_egress / knowledge_lifecycle / metric_registry / evaluation / production_readiness_gate / skill_router + JSON） |
| 4 | skills/ 在 warehouse 侧 | **迁移到 `exhibition-agent/skills/`**（mingyang-venue-ops / exhibition-readonly） |
| 5 | 知识存储边界未定 | **全在 agent-platform 侧**（knowledge-service 拥有 Metadata + 向量索引 + 生命周期状态机） |

---

## 1. 传输与寻址

| 项 | 约定 |
| --- | --- |
| 通道 | HTTPS + JSON；MCP 为**第二阶段**可选增强，不改变本契约语义 |
| 基址 | `https://<warehouse-host>/`（v1.2：直接 REST，端点路径如 `/api/venue-schedule`） |
| 契约版本头 | `X-Contract-Version: 1.2`（缺失按 `1.2` 处理） |
| 上下文头 | `X-Execution-Context`（见 C1） |
| 幂等 | 写操作须带 `Idempotency-Key` |
| 分页 | cursor 分页（`cursor` + `limit`，不提供 offset） |
| 超时 | 默认 10s；长任务返回 `202 + task_id` |

---

## C1. ExecutionContext 契约（平台 → warehouse，字段已冻结）

> 来源：主方案 §2.2.1。这是 **INV-8 的真正载体**。

```text
ExecutionContext
├── user_id
├── tenant_id
├── tenant_type     SPONSOR / VENUE / CONTRACTOR / EXHIBITOR
├── roles[]
├── scopes[]        exhibition:{id} / venue:{id}
├── auth_source     IAM / SSO / PLATFORM_LOCAL
└── request_id      贯穿 Agent → Skill → Retrieval → Domain API → 审计
```

**传递方式（v1.1 已定：采用 (b) JWT）**：
- (b) **平台网关签发的 JWT claim** —— 天然防篡改，**v1.1 定为默认**
- (a) `X-Execution-Context: base64(JSON)` —— 保留为可配置适配器（备用于非网关环境），需平台侧签名防篡改

> ⚠️ **验签密钥注入方式未定**（v1.1 开放项，见 §4 D1）：mock / 自测阶段**仅解析 payload、不验签**；生产环境密钥经「网关统一验签」或「中间件 / 配置注入」待双方拍板。

**warehouse 侧强制校验**：

| 情况 | 行为 |
| --- | --- |
| 头缺失 / 不可解析 | **401**，**绝不降级**为"默认租户" |
| 签名无效 / `auth_source` 不可信 | **401** |
| 调用方自报 `tenant_id` 与 context 冲突 | **403**（拒绝自报，只信 ExecutionContext；**自报检测位置 = 请求 body `params.tenant_id`**，与 `context.tenant_id` 不一致即 403） |
| `scopes[]` 为空却访问 exhibition/venue 级资源 | **403**（**资源级判定 = 请求路径含 `/exhibition/` 或 `/venue/`，或 skill 名前缀 `exhibition.` / `venue.`**） |
| `request_id` 缺失 | **400**（审计链断裂不允许放行） |

### 执行档位（v1.1 新增：环境只切"身份来源"，校验恒开）

| 档位 | 适用 | 身份来源 | 验签 | 401 / 403 判定 | scope 下推检索层 |
| --- | --- | --- | --- | --- | --- |
| `STRICT` | 生产 | Java / IAM 网关签发 JWT | ✅ | ✅ | ✅ |
| `DEV` | 本地 / 测试 / mock | `PLATFORM_LOCAL` 适配器（fixture 直接构造） | ❌（密钥注入待定，见 §4 D1） | ✅ **仍执行** | ✅ **仍执行** |

> 🔴 **不设 `OFF` 档** —— 校验逻辑在**所有环境统一执行**，环境差异**仅限**「身份从哪来 + 是否验签」。
> 反例：若测试环境写 `if testing: skip`，则 401/403 代码直到生产才首次真正执行；开关忘切即**越权穿透**（A 主办召回 B 主办手册，INV-8 崩），且「缺 context → 401」这条验收在测试期失去验证意义。

**测试便利性**：由 fixture 提供默认合法上下文（如 `ctx(tenant=..., scopes=[...])`），正常用例无感；越权用例 = **显式构造空 / 非法 `scopes` 的 context** 触发 403。测试代码量与"无权限校验"相当。

**角色体系延后**：本次**仅按 `scopes[]` 判定**；`roles[]` 字段保留（C1 字段已冻结）但**前期可留空、不参与判定**。角色层级 / 权限后台 / RBAC 配置等"权限模型"推到能力完善后统一补。

---

## C2. Skill / 领域 API 调用契约（v1.2：直接 REST + 平台侧自组装）

> **v1.2 修订（F-S1-05）**：从 v1.1 的「`POST /api/v1/skills/{name}` + 统一信封」改成「直接调 warehouse REST 端点」。
> 原因：真实 warehouse（mingyang-warehouse）有 48 个 REST 端点（`GET /api/venue-schedule` 等），无 `POST /api/v1/skills/{name}` 路由；v1.1 信封方案要求 warehouse 改造加路由，非最佳解。

### 调用方式

平台侧直接调 warehouse 已有的 REST 端点（GET 为主，写操作 POST/DELETE）：

```
GET  /api/venue-schedule?venue_id=vn-001
GET  /api/portrait/exhibition/{exhibition_id}
POST /api/leads  (写操作，HITL)
```

端点清单由 warehouse 侧的 `SKILL.md`（能力总表）维护，平台侧动态加载（`skill_loader/parser.py` 解析 48 个端点）。

### 成功响应（REST JSON，非信封）

warehouse 返回端点原生 JSON，**不强制**统一信封字段。平台侧自组装 `SkillResult`：

| SkillResult 字段 | 来源 |
| --- | --- |
| `readiness` | 从 REST JSON `data_readiness.level` 映射：`complete`→READY，`pending`/`sparse_sample`/`incomplete`→NOT_CONNECTED，`synthetic`→SYNTHETIC，`partial`→PARTIAL；缺失默认 READY |
| `classification` | 默认 INTERNAL（REST 端点不返回分级） |
| `sources` | 从端点路径推导（如 `/api/venue-schedule` → `Source(type="table", name="t_venue_schedule")`） |
| `citations` | 从 REST JSON `citations` 字段提取（如有） |
| `warnings` | SYNTHETIC/PARTIAL 时平台侧自加警告 |

**`data_readiness` 强制标注（INV-3 红线，保留）**：
- `level="sparse_sample"` / `"pending"` / `"incomplete"` → 平台侧必须向用户显式标注"该画像为样本/待接入数据，结论仅供参考"
- 仅当 `level="complete"` 时可按完整数据呈现
- 推荐/预测类（SYNTHETIC）同理：须标注"合成数据，仅供链路演示，非真实经营结论"

### 错误响应（HTTP 状态码 + JSON body）

```json
{ "error": { "code": "...", "message": "...", "retryable": false } }
```

| HTTP | body.error.code | 触发 | 平台侧应如何处理 |
| --- | --- | --- | --- |
| 401 | `AUTH_CONTEXT_MISSING` / `AUTH_CONTEXT_INVALID` | C1 头缺失/非法 | 报错，**禁止**降级为默认租户 |
| 400 | `REQUEST_CONTEXT_BROKEN` | C1 `request_id` 缺失 | 报错，不得放行 |
| 403 | `SCOPE_DENIED` | 越权访问 | 报错（纳入"越权召回"监控） |
| 403 | `EGRESS_DENIED` | 出域策略未过 | **直接拒绝，不得降级到云模型** |
| 404 | `KNOWLEDGE_NOT_PUBLISHED` | 非 `PUBLISHED` 知识 | 不展示（F03 生命周期） |
| 422 | `METRIC_NOT_VERIFIED` | 命中已注册但未 `VERIFIED` | **禁止 L3 自算**（INV-10） |
| 422 | `METRIC_BLOCKED` | 指标 `BLOCKED` | 答"待接入"，禁止自造口径 |
| 422 | `DATA_NOT_CONNECTED` | 数据源未接入 | 答"待接入" |
| 429 | `RATE_LIMITED` | 限流 | 退避重试 |
| 502 | `UPSTREAM_ERROR` | 上游故障 | 重试 / 降级提示 |
| 500 | `INTERNAL` | — | 上报 |

### INV-10 落地（v1.2 双轨）

> 🔴 **INV-10 落地点**（v1.2 双轨）：

**轨 1（422 错误码）**：warehouse 返回 422 + `body.error.code in (METRIC_NOT_VERIFIED, METRIC_BLOCKED, DATA_NOT_CONNECTED)` → 平台侧答"该指标待接入"，**不得**让 LLM 自己写 SQL 算。

**轨 2（200 data_readiness）**：warehouse 返回 200 + `data_readiness.level in ("pending", "sparse_sample", "incomplete")` → 平台侧答"该指标待接入"。

两轨均断言 `sql_statements == []`（全程未生成任何 SQL）。

---

## C3. HITL 契约（两种形态，禁止实现为一套）

### ① Execution Approval（执行审批）—— 副作用操作

```
warehouse 收到写请求
   → 返回 202 { hitl: { type:"EXECUTION_APPROVAL", task_id, payload, expires_at } }
平台创建审批任务 → 人工决策
   → 回调 POST /api/v1/hitl/{task_id}/resolve
      { decision: "APPROVE|REJECT", actor: {...}, reason, idempotency_key }
warehouse 校验 actor ∈ ExecutionContext 且有权 → 执行 / 驳回
```

### ② Knowledge Adjudication（知识裁定）—— 知识冲突

```
知识冲突且 constraint_kind 未标注（T6 懒标注）
   → { conflict_id, candidates:[...], recommended, precedence_applied }
人工裁定 → 回写知识 metadata（标签 / override）
```

| | Execution Approval | Knowledge Adjudication |
| --- | --- | --- |
| 作用对象 | Execution 状态机 | 知识条目 |
| 产出 | 继续 / 驳回 | 判定结论 + **回写 metadata** |
| 归属 | 平台侧能力，warehouse 提供待审批动作 | 知识平台侧（F03） |
| 协议 | 上述 `task_id` 流程 | `conflict_id` 流程 |

> **禁止复用同一套 task 结构** —— 二者语义、产出、超时策略均不同（主方案 §16.1）。

---

## C4. 评测与可观测契约

**每次调用必须可追溯的最小 trace 字段**：

```text
request_id · tenant_id · skill · latency_ms · readiness
data_classification · egress_decision · model · cost
retrieval_hit_ids[] · error_code（仅出错时必填）
```

> **必填口径（v1.1 澄清）**：上述 11 字段中，**`error_code` 仅在出错时必填**，成功响应可省略；其余 10 个字段**恒必填**（含成功路径）。

**确定性验收判据**（不是统计指标，必须恒等）：

| 判据 | 期望 |
| --- | --- |
| 跨租户越权召回数 | **= 0** |
| 过期 / 未发布知识召回数 | **= 0** |
| 无 `readiness` 的数值响应数 | **= 0** |
| trace 缺失 `request_id` 数 | **= 0** |

**Golden Set 类别（平台侧维护，warehouse 提供语料与状态机）**：
`Positive` / `Cross-Tenant Negative` / `Lifecycle Negative` / `Conflict-Precedence`

---

## C5. 数据分级（F02 衔接）

warehouse 为每个响应/字段标注 `classification`（五级）；平台侧 **Model Router** 依据「分级 + 企业出域策略」选择模型（Small / Private-Qwen / Private-DeepSeek / Cloud）。

| 等级 | 默认出域 |
| --- | --- |
| `PUBLIC` | ✅ |
| `INTERNAL` | 🟡 脱敏 / 白名单后 |
| `CONFIDENTIAL` | ❌ |
| `PII` | ❌（脱敏后仍受限） |
| `FINANCIAL` | ❌ |

> 出域策略是**企业级 Policy**，不得写死；未分类数据按 `CONFIDENTIAL`。

---

## 2. 版本与兼容

| 变更类型 | 版本 | 要求 |
| --- | --- | --- |
| 新增可选字段 / 新错误码 | minor（1.x） | 单边可发，**向前兼容** |
| 删除字段 / 改语义 / 改必填 | major（2.0） | **双方评审 + 灰度** |
| C1 字段变更 | major | 等同破坏性，须同步 F01 |

**任何一方内部重构（换框架、换存储、换编排实现）都不得改变本契约。**

---

## 3. 迁移策略（v1.2：warehouse 零改造）

v1.2 修订后，warehouse **无需改造**（直接用现有 48 个 REST 端点）：

1. ✅ 平台侧 exhibition-agent 已改完：skill 层从 `POST /api/v1/skills/{name}` + 信封改成直接调 `GET /api/venue-schedule` 等 REST 端点
2. ✅ 平台侧自组装 `SkillResult`（readiness 从 `data_readiness.level` 映射）
3. ✅ INV-10 双轨落地（422 错误码 + 200 data_readiness 字段）
4. ✅ mock server 改成 REST 端点 mock（保持测试可跑）
5. ⏳ warehouse 侧 `data_readiness` 字段标注补全（当前画像/推荐/预测类已标，其余端点按需补）

---

## 4. 待决项（需双方拍板）

| # | 待决 | 影响 |
| --- | --- | --- |
| D1 | C1 传递方式：**已定 JWT**（v1.1）；**验签密钥注入方式待决**（网关统一验签 / 中间件 / 配置） | 实现复杂度、防篡改强度 |
| D2 | `request_id` 由谁生成（平台 / warehouse） | 链路贯通与去重 |
| D3 | MCP 是否为二期目标 | 是否再写一层适配 |
| D4 | 限流配额（按 tenant / 按 skill） | 429 策略 |
| D5 | agent-platform 侧契约副本存放路径与同步责任人 | 防止两份漂移 |
| D6 | legacy 端点清单与改造排期 | 迁移节奏 |
| D7 | 契约评审人（双方各一名） | major 变更谁签字 |

---

## 5. 验收（契约 1.2 可视为生效的判据）

> 勾选状态反映 `exhibition-agent` v1.2 实现的实际测试覆盖（114 passed, 1 skipped）。
> 标注测试名供回溯；未勾选项为显式留待后续阶段。

- [x] 无 `X-Execution-Context` 调用 → **401**（不是 200 + 默认租户）— `test_c1_execution_context::test_missing_header_raises_401`
- [x] 越权 scope → **403** — `test_c1_execution_context::test_empty_scopes_resource_level_raises_403` + `test_server::test_query_empty_scopes_returns_403`
- [x] 命中未 `VERIFIED` 指标 → **422**，平台侧**不触发** L3 — `test_inv10_no_sql::test_inv10_metric_pending_answers_pending_and_no_sql`（断言 `sql_statements == []`）
- [x] 非 `PUBLISHED` 知识 → **404** — `test_skill_venue_schedule::test_skill_knowledge_not_published`
- [x] v1.2 直接 REST：200 响应返回 REST JSON dict，平台侧自组装 SkillResult — `test_warehouse_client_rest::test_normal_success_rest_returns_json_dict`
- [x] v1.2 INV-10 双轨：200 + data_readiness.level=pending → 答"待接入" — `test_skill_venue_schedule::test_skill_data_not_connected_200_answers_pending`
- [x] 每条 trace 含 `request_id` — `test_c4_trace::test_trace_request_id_mandatory`
- [ ] 写请求必带 HITL + `Idempotency-Key` — 显式留待后续阶段（骨架不实现写操作，见 README 红线）
- [x] 越权召回数 = 0、过期召回数 = 0（golden set 回归通过）— `test_observability::test_c4_scope_denied_zero_on_normal_path`（正常路径 `scope_denied_count == 0`）

---

> **下一步**：本契约经双方确认后，`exhibition-agent` 在 `agent-platform/applications/` 下按此契约接入；
> 在此之前，平台侧可用 mock server 按本契约自测，不依赖 warehouse 就绪。
