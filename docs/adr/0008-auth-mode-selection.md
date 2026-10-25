# ADR-0008: 认证方式（对外入口凭据 / 内部租户断言 / ExecutionContext 令牌化）——决策记录

- 状态：**部分已决 + 三项未决（本文不替用户拍板）**
- 日期：2026-10-16
- 来源：roadmap `plan-production-delivery-roadmap-2026-10-09.md` 阶段3 #24「3 项技术选型悬置」之一
- 关联：`ADR-0007`（服务端断言租户身份，**Accepted 2026-09-27 + 分支 A**）、`AGENTS.md` 框架选型规则「需评估：ExecutionContext 是否迁移到 PyJWT」、`docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §3 第 16 项

## 1. 已决并已实施的部分（先把边界划清，避免把旧问题再问一遍）

| 事项 | 结论 | 证据 |
|---|---|---|
| **内部租户身份**用什么承载 | RS256 JWT（网关签发/验签）+ 网关→子服务的内部 HMAC 签名头 | `packages/agent-runtime/agent_runtime/identity.py:1`（模块头）、`:160-232`（`mint_token` / `verify_token`，`algorithms=["RS256"]`）、`ARCHITECTURE.md:63`「单一实现」 |
| 是否走「先 key→tenant 过渡再演进 JWT」 | **否，跳过 B 直接 A+C**（B 属抛弃式工作） | `ADR-0007` §7 表「目标态」行（2026-09-27 拍板） |
| 缺配置时是否允许静默运行 | 提供 fail-fast 开关，但**默认关** | `require_identity_startup_guard`（`identity.py:318` 拒启文案）、`DEPLOY_ENFORCE_IDENTITY` 默认 False |

⇒ 「认证方式」这个词在下面**只指三件仍未决的事**，不指以上已决部分。

## 2. 三项未决

### U1 对外入口仍是单把静态 `API_KEY`，且"未配 key 即不校验"的旁路仍在
- 现场：`applications/agent_server/api/auth.py:23-29`（单一 `settings.api_key` + `compare_digest`），
  `:25-26` `if not settings.api_key: return None` ⇒ **开发模式旁路**。
- 与 ADR-0007 的关系：ADR-0007 §2 已把这条列为事实，其 §59 的处置是「生产启动前置校验」——
  机制已实现，但**默认不启用**，所以"多租户生产忘配 key ⇒ 入口无鉴权"这条仍未被结构性关闭。
- 选项：
  - **A 把 `DEPLOY_ENFORCE_IDENTITY` 默认改 True**（缺公钥/缺 `SINGLE_TENANT` 即拒启）。代价：现有以
    "零配置冒烟"为契约的部署与文档（`AGENTS.md` 运行方式 `DATABASE_URL= uvicorn …` 零依赖冒烟）会立刻起不来。
  - **B 保持默认 False，改由部署清单强制**（K8s 清单里显式置 True + CI 加一条"生产清单必须为 True"检查）。
    代价：保护面在清单层而非代码层，漏改清单不会被本地测试拦住。
  - **C 不动**。代价：`auth.py:25-26` 的旁路继续是"能起但裸奔"的形状。

### U2 API key 是否需要 key→主体 映射（"替谁调"审计）
- 现场：`ADR-0007` §2「两应用认证为单一静态密钥，无主体→租户映射」；本轮 `bd4fb0b`/`be82e48` 未触碰该面。
- 已知约束：审计主体已按 `116d51b1`（PR #61）改为服务端断言主体（`session_router.py:71`），
  **但那是"操作记录里的主体"**，不等于"入口能区分多个持有者"。⇒ 现在的可归因粒度是部署单元，不是调用方。
- 选项：**A** 多把 key + key→tenant 表（真映射）；**B** 明确宣告"本部署只服务单一组织，调用方区分子系统靠
  网关侧 JWT"（把 U2 归零）；**C** 等真实外部租户数 > 1 且确有跨组织调用需求时再做。
- 判据要点：ADR-0007 §7.1 已确认**当前实例承载 ≥2 个真实外部租户**，所以 B 与现状是否矛盾，需用户一句话定。

### U3 `ExecutionContext` 是否整体迁 JWT
- 现场：`AGENTS.md:111` 仍写「需评估」；`ADR-0007` §53 明确「与既有框架待评估项**合并决策**」⇒ 这条是**有意悬置**，不是遗漏。
- 牵动的面（不迁=继续自研签名串，迁=改对外契约）：exhibition 的 C1 实现 `applications/exhibition-agent/exhibition_agent/foundation/execution_context.py`
  与其 `F01_SIGNING_SECRET`（`docs/TODO.md` / §10 P2-5 实测该键未在任何 `.env.example` 记载，exhibition 那份缺 1 项）。
- 选项：**A** 迁 PyJWT 标准 claims（破坏性：F01 串形状变化，需先审计消费方）；**B** 保留自研串，
  只在网关↔子服务这一条链用 JWT（当前态）；**C** 本版明确不迁，并把「重启条件」写进本文（见 §4）。

## 3. 否决理由（哪些路已经被证据关掉）
- **「用 API_KEY 派生会话身份」已作废**：`ADR-0007` 之后该通道被拆，P6/P6-3 门禁禁止旧入口名再现
  （`ARCHITECTURE.md` §4.1；`tests/governance/test_thread_identity_migration.py`）。⇒ 任何"回到 key 当主体"的方案都不用再讨论。
- **「给每个端点各写一遍鉴权」**属 AGENTS.md 明令禁止的散点式做法（横切关注点全局优先，三层齐备）。

## 4. 重启条件（出现什么信号必须重开这份 ADR）
1. 第二个**外部组织**接入且要求互相不可见 ⇒ U2 必须选 A（现在只是"够用"）。
2. 任一生产清单未置 `DEPLOY_ENFORCE_IDENTITY=true` 而被发现 ⇒ U1 必须选 A 或 B（现在选 C 的前提是"清单里都置了"）。
3. 需要把 `ExecutionContext` 交给外部/第三方系统校验 ⇒ U3 必须选 A（自研串对外的代价此时才真正出现）。

## 5. 待用户回答（一行即可）
- U1：A / B / C；U2：A / B / C；U3：A / B / C。
- 未答之前我不动 `auth.py`、不动 `execution_context.py`、不改任何默认值（红线「先方案后编码」）。
