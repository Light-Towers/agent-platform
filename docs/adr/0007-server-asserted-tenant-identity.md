# ADR-0007: 服务端断言租户身份（tenant 从客户端字段收归服务端解析）

- 状态：**采纳（Accepted，2026-09-27 评审通过 + 分支 A 拍板，活跃 P0）**；实施计划：`docs/plans/plan-tenant-identity-2026-09-27.md`
- 日期：2026-09-27
- 关联：`ADR-0006`（本 ADR 落地其 D1「tenant 由服务端解析、客户端不可指定」的**身份层缺口**）、`ADR-0003`（双库/连接源）、`ADR-0004`/`ADR-0005`（记忆契约）、`docs/plans/plan-isolation-hardening-2026-09-27.md`（T9–T13）、AGENTS.md 框架规则「需评估：ExecutionContext 是否迁移到 PyJWT + 标准 JWT」
- 触发问题：**隔离加固（T9–T13/T1）把 `tenant_id` 当唯一安全边界、store 层漏传即 fail-fast，但 `tenant_id` 的*来源*仍是客户端可传的 `QueryRequest.tenant_id` —— 边界可信性没真正闭合。**

---

## 1. 结论先行

**当前 `tenant_id` 不是可信边界**：它由客户端在请求体里传入，两应用又都用**单一静态 `API_KEY`**（无 key→tenant 映射）。因此一个持有合法 key 的调用方可把 `tenant_id` 填成**任意值**，读写任意租户的数据——隔离加固做得越严（谓词、fail-fast），这个"调用方可自报租户"的缺口反而越关键。**需要把"租户身份"从客户端字段收归服务端断言**（认证主体 → tenant），本 ADR 给出方案，待拍板后单独立项实施。

> **评审升级（2026-09-27，已实测核实）：存在比"客户端可传"更隐蔽、更危险的通道——`tenant_id` 由 LLM 填。** `agent_server/capabilities.py:281,284` 的 `knowledge_retrieve` 工具 `input_schema` 把 `tenant_id` 列为 `required`，即**模型自己决定去哪个租户检索**：一次幻觉或被提示注入（MINJA / OWASP ASI06）即可把读/写打到任意租户，无需调用方参与。因此本 ADR 的收口对象是**两个**入口：客户端 body 字段 + LLM 可填的 tool 参数。

---

## 2. 现状技术事实（2026-09-27 实测）

| 事实 | 证据 |
|------|------|
| `/query` 等端点 tenant 取自请求体字段（客户端可控） | `shared_schemas/query.py:18` `tenant_id: str \| None = Field(None, ...)`；`agent_server/api/query_router.py` `req.tenant_id or "default"` |
| 两应用认证为**单一静态密钥**，无主体→租户映射 | `agent_server/api/auth.py:16` `verify_api_key`（`compare_digest(x, settings.api_key)`）；`agent_federation/api/server.py` `API_KEY` 单值 |
| 服务端租户 ContextVar 已铺管道但**无生产绑定方** | `agent_runtime/workspace_registry.py` `bind_tenant_context`/`server_tenant_id` 定义完整；`agent_federation/api/context.py` `set_tenant_context` 仅测试引用，无 middleware 从认证绑定 |
| PlannerRuntime 身份恒 `'default'`，执行/远程调用拿不到真实租户 | `agent_server/main.py` `PlannerRuntime(workspace_id="default", user_id="default")`；执行记忆写路径靠 `plan.tenant_id`（本次 T1 刚接通轨迹），但 runtime identity 层仍缺 |
| agent_server→knowledge-service 远程 skill 不传租户 | `agent_server/capabilities.py` `_knowledge_query`/`_knowledge_retrieve` 透传 kwargs，`tenant_id` 缺省 → knowledge-service 侧 `resolve_server_tenant` 注入 `'default'`（T11 现状：安全但不正确） |
| **【评审新增·更危险】`tenant_id` 由 LLM 填** | `capabilities.py:281` `"tenant_id": {"type": "string"}` + `:284` `"required": ["query", "tenant_id"]` —— `knowledge_retrieve` 强制模型产出租户值；幻觉/提示注入即可越权到任意租户（MINJA / ASI06） |
| **【评审新增】开发模式旁路：未配 key 即不校验** | `agent_server/api/auth.py:18-19` `if not settings.api_key: return None`；身份层建好前，"既无令牌体系又开着不校验"= 裸奔，需生产 fail-fast |
| 联邦网关→子服务用单一 `KNOWLEDGE_API_KEY`，无内部租户签名 | `agent_federation/tools/knowledge_tools.py`、`knowledge_service` 侧 `KNOWLEDGE_API_KEY` |

**净结论**：T9–T13/T1 建立了「tenant 为边界、漏传不可见」的**机制**；本 ADR 补的是**这个 tenant 从哪来、凭什么信**。

---

## 3. 决策（候选方案，待拍板）

> 目标不变量：**进入任何 store / ContextVar 的 `tenant_id` 必须由服务端从认证主体派生，客户端体里的 `tenant_id` 一律忽略或降级为"仅作断言、与令牌不符即拒"；且 `tenant_id`/`user_id` 不得出现在任何 LLM 可见/可填的 tool 参数 schema 中**（阻断幻觉/提示注入借模型之手选租户）。

### 方案 A（推荐）：签名令牌携带 tenant claim（JWT / 标准 token）
- 入站 `Authorization: Bearer <jwt>`，`sub`/自定义 claim `tenant_id` 由认证服务签发；中间件验签 → `bind_tenant_context(claims.tenant_id)`。
- 下游内部调用（网关→knowledge/kefu/nl2sql）用**服务间签名头**（如 `X-Internal-Tenant` + HMAC/JWT-svc）传递已断言租户，子服务**只信内部签名头、不信 body 的 tenant_id**。
- 契合 AGENTS.md 已列的「ExecutionContext → PyJWT 评估」；`user_id` 可一并作为 claim（解 T13 用户画像的真实 user 来源）。
- 成本：引入/接入 IdP 或自签密钥体系；shared_schemas 契约与鉴权中间件改动。

### 方案 B（轻量、单租户/少量租户）：API Key → tenant 映射表
- 把"单一 `API_KEY`"升级为"每租户一 key"，`api_key → tenant_id` 查映射（配置/DB）；中间件据 key 解析租户并绑定 ContextVar。
- 改动面小、可渐进（保留旧单 key = `default` 租户过渡）；但 key 轮转/多租户规模化不如 JWT，且不天然承载 user_id。

### 方案 C：网关集中断言，子服务信内部头
- 联邦网关做唯一认证入口，解析 tenant 后对下游注入签名内部头；子服务剥离/忽略外部 `tenant_id` 字段。
- 与 A/B 可叠加（A/B 解决"入站身份"，C 解决"内部传播可信"）。单独 C 不解决入站伪造。

**建议**：以 **A（JWT/签名令牌）+ C（内部签名头）** 为目标态；若近期只需按部署单元隔离，可先落 **B** 作为过渡（key→tenant），再演进到 A。`ExecutionContext` 是否整体迁 JWT 与既有框架待评估项合并决策。

---

## 4. 落地范围（拍板后，另出实施 plan；本 ADR 不含代码）

1. **认证/绑定 + 生产 fail-fast**：`agent_server` + `agent_federation` 增加 middleware：验令牌/查 key→tenant → `bind_tenant_context(...)`；请求结束 reset。**生产启动前置校验**：既未配置令牌/key→tenant、又未显式声明单租户（如 `SINGLE_TENANT=default`）时**拒绝启动**，杜绝 `auth.py` "未配 key 即不校验" 旁路在多租户环境裸奔。
2. **契约收口**：`shared_schemas.QueryRequest.tenant_id` 语义降级为**只读诊断字段**（服务端以断言值覆盖；与令牌不符 → 403，不回显内部细节）。是否删除该字段涉及存量客户端，需 `CONTRACT_VERSION` 升版 + 弃用期（AGENTS 兼容期原则）。
3. **移除 LLM 可填租户通道（评审补强·最高优先）**：从 `capabilities.py` 所有 remote skill 的 `input_schema` 中**删除 `tenant_id`（及任何身份类参数）**，改为服务端从 ContextVar 注入；LLM 不再被允许指定检索/写入的租户。`agent_server/capabilities.py` 远程 knowledge skill、`agent_federation/tools/knowledge_tools.py` 一律从 `server_tenant_id()` 取**已断言** tenant 传下游（后者 T11 已用 `get_tenant_context`，上游一绑定即自动正确）；网关→子服务加签名头。
4. **运行时身份**：`PlannerRuntime` / `ExecutionContext.identity.tenant_id` 从请求断言租户填充（当前恒 `'default'`），使执行记忆写路径（已接 `TrajectoryRecord.tenant_id`←`plan.tenant_id`）与配额/审计/限流一致。
5. **`user_id` 同期作为 claim（评审补强，不再列开放项）**：T13 用户画像 + GDPR 按主体删除**全依赖可信 `user_id`**；若仍由客户端/LLM 自报，画像层建在沙上。认证主体须同时签发 `user_id`，与 `tenant_id` 同源。
6. **一致性**：与 `server_tenant_id(default)` 的 ContextVar 优先语义对齐——绑定后 `default` 参数仅用于"确属单租户部署"的显式声明，不再是"客户端没传就兜底"。

---

## 5. 后果

**正向**：`tenant_id` 成为真正不可自报的安全边界，闭合 ADR-0006 D1；T9–T13/T1 的隔离机制从"防内部越权"升级为"防外部伪造"；user_id 可信后 T13 用户画像、GDPR 按主体删除才落地完整。

**风险 / 成本**：
- 契约变更影响所有子服务与外部客户端（需升版 + 弃用期 + 网关适配）。
- 引入令牌/密钥体系（IdP 或自签）是运维依赖。
- 存量"客户端自传 tenant_id=正确值"的调用方，切换后必须由认证主体提供同一 tenant，否则被拒——需迁移期灰度。

**明确不做（本 ADR 阶段）**：不改代码、不动 `verify_api_key` 现有单 key 行为、不改 store 谓词（隔离机制已就绪）；仅在拍板后另立实施 plan。

---

## 6. 验证（实施阶段）
- 越权用例：合法 key/令牌但 body 伪造 `tenant_id=其他租户` → 数据读写仍落在**令牌租户**，伪造被忽略/403（`tests/governance` 行为级 + `tests/ha` 真实 PG）。
- 契约回归：`test_tenant_default_forbidden` / `test_isolation_dimension_contract` 保持绿；新增"tenant 源=服务端断言"红线（AST：生产 `/query` 等入口不得以 `req.tenant_id` 作边界值）。
- 内部传播：网关→子服务签名头缺失/伪造 → 子服务拒绝（fail-closed）。

---

## 7. 评审后建议决议（待正式拍板）

> 以下为 2026-09-27 评审达成的建议，ADR 作者认同；标记 Accepted 前仍需用户正式拍板。

| 拍板项 | 建议决议 | 理由 |
|---|---|---|
| 目标态 | **跳过 B，直接 A+C**（JWT claim + 内部签名头） | B 的 key→tenant 映射是抛弃式工作；缺口紧迫（含 LLM 可填通道），不走两遍 |
| 令牌签发 | **自签 RS256 起步**（子服务仅持公钥），预留换 IdP | RS256 解 `KNOWLEDGE_API_KEY` 单密钥痛点；验签层隔离，后续平滑迁移 IdP |
| `QueryRequest.tenant_id` 弃用 | **双读过渡**：信令牌、body 仅审计比对（不符记审计不拒），一个版本后切 403 | 立刻覆盖会打断自报正确值的存量客户端 |
| `user_id` | **同期作为 claim 落地**（非开放项） | T13 画像 / GDPR 按主体删除的前置 |
| ExecutionContext 迁 JWT | **并入本 ADR 一次决策** | 避免同一契约改两次 |

### 7.1 定级（2026-09-27 已拍板：**分支 A —— 活跃 P0**）

> **拍板结果（2026-09-27 用户确认）**：当前实例**已承载 ≥2 个真实外部租户**（分支 A）。
> ⇒ 本缺口定性为**活跃 P0**：任何持合法 key 的调用方现即可读写任意租户数据；`knowledge_retrieve` 的 LLM 参数化租户通道同样活跃。
> ⇒ **触发分支 A 特有动作——追溯审计**（见实施 plan A1）：越权访问可能**已经发生**，需排查存量痕迹（访问日志、`semantic_cache`、`memories`/`chunks`/`episodic_memories` 各表租户分布、执行轨迹），属事故响应而非仅排期修复。

原两分支记录（留档）：
- 仅内部 / 自家前端 · 或每租户独立部署 ⇒ 「对外商用 / 多租户同实例前置项」，非本月急；
- 一个实例同时服务多外部租户且 key/身份可被各租户触达 ⇒ **活跃 P0**（任何合法调用方可读任意租户 + LLM 可被诱导越权）。**← 已确认走此分支**

### 7.2 部署灰度顺序（评审补强，写入实施 plan）
§6 的 fail-closed（内部签名头缺失/伪造即拒）**必须排在"内部签名头全量上线"之后**：滚动升级窗口内若有未升级网关未带头，会被子服务全量拒。顺序应为：① 网关开始附带签名头（子服务暂不强制）→ ② 观测全量覆盖 → ③ 子服务再切 fail-closed。
