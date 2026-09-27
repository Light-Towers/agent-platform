# 租户身份断言实施计划（ADR-0007 落地）

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-27 |
| 状态 | 待执行（ADR-0007 已采纳 + 分支 A 拍板：**活跃 P0**） |
| 上位决策 | `docs/adr/0007-server-asserted-tenant-identity.md`（tenant/user 身份从客户端字段收归服务端断言） |
| 与隔离计划的关系 | `plan-isolation-hardening-2026-09-27.md`（T9–T13）建立了「tenant 为边界」的**机制**；本计划补「tenant 从哪来、凭什么信」的**身份层**。分支 A 确认后升级为活跃 P0 |
| 关键新增 | **A1 追溯审计**（分支 A 特有）：越权可能已发生，属事故响应，最先执行 |

---

## 1. 结论摘要

分支 A 确认（实例已承载 ≥2 真实外部租户）后，本计划按三级推进：

1. **A1 追溯审计（立即）**：先取证再修复——排查越权是否已发生，产出审计报告；
2. **A2 LLM 通道移除（代码侧最快见效，可独立先行）**：不依赖令牌体系，当天可上线；
3. **A3–A6 令牌体系（标准路径）**：RS256 自签 → middleware 绑定 → 内部签名头（软→硬灰度）→ 双读过渡 → 契约红线。

目标不变量（ADR-0007 §3）：进入任何 store/ContextVar 的 `tenant_id`/`user_id` 必须由服务端从认证主体派生；**身份类参数不得出现在任何 LLM 可见/可填的 tool 参数 schema**。

---

## 2. 实施任务

### A1（P0·最先）追溯审计（分支 A 特有）

> 产出**只读审计脚本**（`scripts/audit_tenant_access.py` + SQL 手册），由持目标库访问权者在生产/预发执行；编码 agent 不直接连生产库。

排查项（按泄漏可疑度排序）：

| # | 排查点 | 方法 | 可疑信号 |
|---|--------|------|---------|
| 1 | 各业务表租户分布 | `GROUP BY tenant_id` 逐表（memories/chunks/sql_ddl/sql_docs/sql_examples/episodic_memories/procedural_memories） | `'default'` 桶外的孤立小租户、命名异常（测试值、他人租户名） |
| 2 | **semantic_cache 跨租户污染** | 按 tenant 分组统计命中/条目；抽样比对 query 与 tenant 归属合理性 | 同一缓存条目被多租户命中（T11 之前 cache 键若含客户端自报 tenant，错误自报会污染） |
| 3 | 访问日志关联分析 | （若有请求日志）同 API_KEY 来源的 `tenant_id` 集合 | 单 key 出现多租户自报、非常规时段的陌生租户 |
| 4 | knowledge-service 审计日志 | T11 注入的 default 归属审计记录 | 高频落入 default 的真实多租户请求（隔离名存实亡的证据） |
| 5 | 执行轨迹 | `trajectory` / episodic 按 tenant 分布 | 非租户方轨迹混入 |

产出：审计报告（含每个可疑点的 SQL、结果、判定、处置建议）；若发现确认越权 → 升级事故响应（受影响租户清单 + 数据修复 + 通知决策，另行立项）。

### A2（P0·代码先行）移除 LLM 可填租户通道

ADR-0007 §4.3（评审补强·最高优先）。**不依赖 A3，可当天上线**：

- `applications/agent_server/capabilities.py`：所有 remote skill 的 `input_schema` **删除 `tenant_id`**（`_knowledge_query`/`_knowledge_retrieve` 的 `required: ["query","tenant_id"]` 改为 `required: ["query"]`）；`required` 去掉后，实现内部忽略 kwargs 里的同名键（防 LLM 惯性输出）。
- 租户来源：实现体改为 `server_tenant_id(default=... )` / `get_tenant_context()` 取**已断言**租户（当前断言源未建时暂用 T11 同款服务端注入 + 审计，A3 落地后自动切换为真实断言值）。
- `agent_federation/tools/knowledge_tools.py` 已在 T11 改为 ContextVar 下传，保持。
- 验收：AST 断言 `tests/governance/test_identity_not_in_tool_schema.py`——扫描全部 skill/tool 的 `input_schema` 字面量，`tenant_id`/`user_id`/`api_key` 出现即红。

**实施记录（2026-09-27，分支 `feat/isolation-hardening`）**：
- `capabilities.py`：`_GENERAL_QA_INPUT_SCHEMA` 删 `user_id`/`tenant_id` 属性；`_run_general_qa` 租户改取 `server_tenant_id(get_settings().default_tenant_id)`（不信 kwargs）；`_knowledge_retrieve` 远程 schema 删 `tenant_id` 属性 + `required` 收为 `["query"]`；`exhibition_query` 描述去掉“tenant_id 等”暗示。
- 新增模块级 `_sanitize_identity()`：剔除 kwargs 的 `tenant_id`/`user_id`/`api_key`，租户由服务端断言源覆盖（A3 前=部署 default，代码留 `TODO(A3)`）；`_knowledge_query`/`_knowledge_retrieve`/`_nl2sql_query`/`_kefu_query`/`_exhibition_query` 五个远程 skill body 均先 `_sanitize_identity` 再转发。
- 新增 `tests/governance/test_identity_not_in_tool_schema.py`：AST 扫 `applications/`+`packages/` 含 skill/tool 标记文件的 JSON-Schema `properties` 键/`required` 项，命中身份键即红（**全仓 0 违规**）；+ 行为级 `test_sanitize_identity_strips_llm_supplied_identity`（LLM 传 `tenant_id="OTHER_TENANT"` 被剔除，实际取服务端）。
- 红线 1 合规：`capabilities.py` 新增 `from agent_runtime.workspace_registry import server_tenant_id`（agent_server→agent-runtime 单向）。
- 验证：identity 红线 2 passed；governance 128 passed；agent_server 44 passed；根 session 441 passed / 0 failed；ruff 通过。
- 边界：general_qa 的 `user_id` 暂留 `kwargs.get`（A3 可信 user 源落地后收口；本次优先堵跨租户 tenant 通道）；knowledge-service 侧仍 T11 注入 default，A3/A5 切真实断言值。

### A3（P0）RS256 令牌体系 + middleware + 生产 fail-fast

- 新增 `shared_schemas` 或 `agent_runtime` 身份模块（落点评审定，倾向 `agent-runtime/identity.py`，零宿主依赖）：
  - 令牌签发/验签（`PyJWT`，RS256 公私钥；子服务只持公钥）；claims：`tenant_id`、`user_id`、`exp`、`iat`、`jti`；
  - 密钥轮转：支持 `kid` 多公钥并存（`IDENTITY_JWKS_PATH` 或公钥目录），旧密钥宽限期 ≥1 个轮转周期；
  - clock skew 容忍 ±60s；`exp` 短期（≤1h）+ 刷新策略（签发侧职责，本计划只定验签）。
- middleware（`agent_server` + `agent_federation`）：`Authorization: Bearer <jwt>` 验签 → `bind_tenant_context(claims)` + `bind_user_context(claims)` → 请求结束 reset。
- **生产 fail-fast 启动校验**（ADR-0007 §4.1）：既未配置令牌公钥/key→tenant、又未显式 `SINGLE_TENANT=<tenant>` 时**拒绝启动**；开发模式（`SINGLE_TENANT` 显式声明）保留。
- 验收：伪造令牌/过期令牌/无 `tenant` claim → 401；合法令牌但 body 自报他租户 → 见 A5 双读行为。

### A4（P0）内部签名头（网关 → 子服务）

- 网关（agent_federation → knowledge/kefu/nl2sql）出站附 `X-Internal-Tenant` / `X-Internal-User` + HMAC（内部密钥 `INTERNAL_HMAC_KEY`，独立于 KNOWLEDGE_API_KEY）或短 JWT-svc（复用 A3 签发，内部 audience）。
- 子服务**观测期**：收头校验签名 + 记审计，**暂不强制**（灰度第①②步）；`resolve_server_tenant` 优先级改为：内部签名头 > 请求链路 ContextVar > `KNOWLEDGE_DEFAULT_TENANT_ID` 注入（保留并审计）。
- 验收（观测期）：头缺失/伪造 → 审计告警但不拒（软模式）；签名错 → 拒。

### A5（P1）契约双读过渡 + 运行时身份填充

- `shared_schemas.QueryRequest.tenant_id` docstring 降级为「只读诊断字段，服务端断言值覆盖」；`query_router.py` 等 10 处 `req.tenant_id` 逐处替换为断言值；body 与令牌不符 → 记审计（过渡期不拒）。
- `PlannerRuntime` / `ExecutionContext.identity`：从请求断言租户填充（消除恒 `'default'`）；执行记忆写路径（`TrajectoryRecord.tenant_id`←`plan.tenant_id`）自动获得真实租户。
- 一个版本后（弃用期满）：body 不符 **403**，`test_tenant_default_forbidden` 同款 AST 红线扩展到 `req.tenant_id` 作边界值。

### A6（P1）fail-closed 切换 + 契约红线固化

- 灰度第③步：子服务切换 `X-Internal-Tenant` 缺失/伪造 → **拒绝**（fail-closed）；切换前置条件：观测期签名头覆盖率 100% 且审计无异常 ≥7 天。
- 契约测试扩展：`test_isolation_dimension_contract.py` 增加「身份来源红线」用例（AST：生产路由/工具不得以 `req.tenant_id` 作隔离边界）。

---

## 3. 明确不做

- ❌ 不在本计划引入外部 IdP（RS256 自签起步，验签层隔离，日后可平滑替换）；
- ❌ 不改动 store 层谓词与 `_tenant_gate` 语义（机制已就绪，本计划只换 tenant 的**来源**）；
- ❌ 不在过渡期拒绝 body 自报正确租户的存量客户端（双读，A5/A6 分两步收口）；
- ❌ A1 审计脚本不直连生产库（产出脚本与手册，人工在目标环境执行）。

---

## 4. 验收清单

| 任务 | 验收 |
|------|------|
| A1 | 审计报告产出：五排查点各有 SQL+结果+判定；发现确认越权 → 有受影响租户清单 |
| A2 | AST 红线测试红→绿；knowledge skill 实际调用不再接受 LLM tenant（模拟幻觉输入验证忽略） |
| A3 | 四类令牌用例（合法/伪造/过期/缺 claim）全绿；未配置身份且未声明单租户 → 启动即拒 |
| A4 | 软模式下头缺失不拒但审计告警；签名错拒绝 |
| A5 | 10 处 `req.tenant_id` 全部替换为断言源；`grep -c "req.tenant_id" query_router.py` = 0（注释除外） |
| A6 | fail-closed 后：无头请求 403；契约红线测试入 CI |
| 全局 | `make ci` 全绿；`tests/ha/test_tenant_isolation_real_pg.py` 在 CI requires_pg 下全绿 |

---

## 5. 风险与依赖

1. **A1 依赖目标库访问权**——脚本产出后由运维/持权者执行，时间不可控但**必须先于 A3 上线完成**（否则修复后取证困难：新机制会改变数据分布基线）。
2. **PyJWT 新依赖**：进 `agent-runtime` 可选 extra（`identity`），内核 `agent-core` 不引入（红线 3）；供 A3 middleware 与子服务验签共用。
3. **存量客户端迁移**：自报正确租户的调用方在 A5 过渡期无感；自报错误租户的调用方——**这正是要抓的**——过渡期审计会暴露它们。
4. **灰度顺序不可倒置**：A4 软模式 → 观测 100% 覆盖 → A6 fail-closed；倒置会造成未升级网关全量被拒。
5. 迁移/配置变更均向后兼容一个版本（AGENTS 兼容期原则）。
