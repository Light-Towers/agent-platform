# CodeQL Batch 7：取消 dismiss 通道，剩余告警全部真修

> 状态：**B7a 已执行**（三条真修）；**B7b 待拍板**（两条需架构决策，不得先动代码）
> 日期：2026-10-01　触发：用户明确「不要用 dismiss 这种简单的处理方式」
> 前置：Batch 1-6 见 `plan-codeql-codescanning-remediation-2026-10-01.md` 与 `plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md`

## 1. 本批约束

1. **不使用 dismiss**。任何一条都不以「面板关闭 + 理由」收尾。
2. 修不动的**如实报告为未解**，不用假模型、不改命名规避检测器、不做路径级查询排除来伪装成"已解决"。
3. 每条必须有客观依据（当前 open 事实 + 官方 query help 的判定口径），不凭记忆下结论。

## 2. 当前事实（`refs/heads/main`，2026-10-01 取，共 6 条）

| # | rule.id | 位置 | 官方判定口径要点 |
|---|---------|------|------------------|
| 34 | `py/weak-sensitive-data-hashing` | `applications/agent_federation/gateway/gray.py:40` | 查询只在「对敏感数据用弱哈希」时报；**非口令场景推荐 SHA-2** |
| 38 | `py/weak-sensitive-data-hashing` | `packages/agent-core/agent_core/guardrails/auth.py:92` | 把输入归类为 **password**（限定输入空间 → 需慢 KDF）；SHA-2 在非口令场景本是 GOOD |
| 39 | `py/weak-sensitive-data-hashing` | `packages/agent-core/agent_core/guardrails/auth.py:117` | 同上 + 12 hex 截断 |
| 42 | `py/path-injection` | `packages/agent-core/agent_core/guardrails/fs.py:162` | 污点在守卫**之前**抵达 sink |
| 43 | `py/clear-text-logging-sensitive-data` | `packages/agent-core/agent_core/guardrails/fs.py:93` | 日志表达式含被归类为 **secret** 的值 |
| 44 | `py/clear-text-logging-sensitive-data` | `packages/agent-core/agent_core/guardrails/fs.py:103` | 同上 |

补充取证：官方 query help（`py-weak-sensitive-data-hashing`）**未提供** `usedforsecurity=False` 之类的豁免口子；Python 可自定义的 9 种 sink kind 不含 password-hashing 与 clear-text-logging → 这两类**无法用模型包解决**，只能改代码（此结论已在 Batch 6 记录，本批据此行动）。

## 3. B7a：三条真修（本批执行）

### 3.1 #34 灰度分桶哈希：MD5 → SHA-256

- **依据**：官方对「非口令场景」的直接建议就是 SHA-2；且 CodeQL 把 `user_id` 视为可识别信息（query help 明确列举 usernames）。
- **影响面实测**：`_get_gray_pct()` 默认 `"0"`（灰度关闭）；`is_in_gray` 在**产品代码中无调用点**（仅 `tests/unit/test_guards.py`），分桶结果不落库、不持久化 → 换哈希函数导致的人群重排无生产影响。
- **验收**：`test_deterministic` / `test_distribution`（30% 时 2700~3300）必须仍通过——SHA-256 均匀性满足；不新增豁免。
- **回滚**：单行还原。

### 3.2 #43 / #44 路径护栏日志：不落任何路径文本

- **根因（首轮假设，已被下面实测推翻一半）**：`_reject` 打 `base=%s`（`root`，来自调用方经 env/配置解析出的部署目录）、`_ensure_within` 打 `resolved=%r`（同样以 `root` 为前缀）。当时认为 CodeQL 把 env/配置派生值归为 secret。
- **真修（经实测修正两次，以下为本批终态）**：日志**不再落任何路径文本**，只留「拒绝原因 + 不携带原文内容的数值型结构摘要」（`len` / `fragments` / `absolute`）。
- **实测过程（重要，此为证据而非推测）**：第一版只去掉 `base=%s` 与 `resolved=%r`、保留 `input=%r`。PR #38 的 `CodeQL` 检查报 **2 new alerts (high)**，注解位置为 `fs.py:99` / `fs.py:110`（即同两处 logger 位移后的新行号）。两处语句此时只剩「字面量 reason + 入参」⇒ **被判 secret 的是入参本身**。消除法结论与 Batch 6 方案 §5 的先前假设一致：路径里经 `resolve_thread_id(thread_id, api_key)` 带入凭证派生的会话目录名 `session_user-<HMAC(api_key)>`，故**这不是误报**。
- **官方口径**：`py/clear-text-logging-sensitive-data` 的 Recommendation 只有一句“Sensitive data should not be logged”，**未提供** masking / 哈希摘要之类的豁免→ 采取“不打”而不是赌“打了但不可逆”。
- **契约变更与代价（如实记录）**：Batch 3 定的「留痕含原文」就此改为「不落路径文本」。排障路径改为：从接入层访问日志取完整 URL（`?path=` 本就在其中），或用同一入参本地复跑。结构摘要仍足以区分拒绝形态与量级。`applications/agent_federation/api/server.py` 中依赖旧语义的注释同步修正。
- **测试断言方向反转的说明**：两条日志回归用例由「断言原文在内」改为「断言原文不在内 + 断言 reason 与 `len=` 在内」——依据是上述官方口径与实测，**不是为凑绿而收窄**（新断言比旧断言多两项）。
- **契约审计（首轮前）**：全仓 `*.md` 与 `packages/agent-core/tests/test_guardrails_fs.py` 均未断言这两行日志文案（已 grep 确认），因此改动不打破外部可见契约。
- **额外收益**：不再把用户可控文本原样拼进日志，同时降低 `log-injection` 面（该 kind 属可建模清单，但我们选择不用模型糊弄）。
- **回滚**：`_reject` / `_ensure_within` 的日志参数还原为 `%r` 原文形式（并可删 `_input_shape`）。

### 3.3 #42 `resolve_within`：在解析**之前**加词法包含守卫

- **现状**：`:160` 拼出 candidate → `:162` `resolve()`（sink）→ `:166` 才做 containment。sink 永远早于守卫，`barrierGuardModel` 语义上覆盖不到（Batch 6 §9.1 结论）。
- **真修**：先做**纯词法**包含判定（`candidate.is_relative_to(root)`，不触碰文件系统），明显越界直接拒；解析之后再复检一次（防符号链接逃逸）。
  顺序变为：词法 containment → `resolve()` → 规范化 containment。
- **为什么这是真加强而非躲检测器**：
  1. 不再对未验证的越界输入调用 `resolve()`，避免在符号链接/超长路径/平台非法字符上先做文件系统遍历再拒绝（当前实现是"先解析后拒"）；
  2. 绝对路径与异盘符输入更早失败，异常原因更准确；
  3. **不放宽任何接受集**：词法判定对 `a/../b` 这类前缀内片段返回 True，仍由解析后的复检裁决，符号链接逃逸照旧被拒。
- **副作用（如实记录）**：`PathTraversalError` 的原因字符串对"明显越界"输入可能由 `路径无法解析`（原经由 resolve OSError 分支）变为 `路径越出基准目录`。异常消息不回带路径（既有约定），对外 403 文案固定不回显原文（`tests/test_file_endpoints.py` 覆盖），故对外契约不变。
- **模型协同**：Batch 6 已声明 `Path.is_relative_to` 的 `barrierGuardModel`，本改动使 sink 落入守卫之后，模型得以适用——**这是"代码变强 + 工具能理解"的叠加，不是靠模型掩盖缺陷**。若重扫仍不闭合，则如实报告并保持 open（不 dismiss、不加假模型）。
- **验收**：`test_guardrails_fs.py` 现有穿越/NUL/绝对/异平台用例全绿；新增「词法越界在 resolve 前被拒」与「symlink 逃逸仍被拒」两类用例（若宿主不支持 symlink 创建则 skip 守卫，沿用现有 skip 约定）。
- **回滚**：删除前置守卫 3 行。

## 4. B7b：两条待拍板（不在本批动代码）

#38 / #39 的核心不是算法选错，而是**「把 API Key 摘要成用户标识」这个模式本身**被 CodeQL 判为口令哈希场景。三条出路：

| 选项 | 内容 | 代价 | 评价 |
|------|------|------|------|
| **B7b-1（推荐）** | **principal_id 化**：认证后使用服务端签发/存储的不透明主体 id 派生 thread id，密钥不再进哈希；#38 与 #39 同时**真消失** | 会话目录命名迁移（可复用 `scripts/migrate_thread_identity.py` 框架）、鉴权中间件需主体映射、联邦各服务契约核对 | 与 ADR-0007「服务端断言租户身份」同向，属真实架构改进 |
| B7b-2 | 先执行历史会话迁移，**迁移完成后删除 `legacy_thread_id`**（消 #39）；#38 继续留 open | 需部署侧动作；#38 不解决 | 诚实但不完整 |
| B7b-3 | default setup 的 query-suite 按路径排除这两个查询 | 会同时屏蔽该文件未来的真实同类问题 | **不推荐**：这是"看不见"而非"修好了" |

不选：改用 scrypt/pbkdf2（把高熵密钥当口令做慢哈希，热路径纯损失，且使摘要与既有会话全部漂移）；改名 `secret`→其它以规避名称启发式（藏而非修）。

## 5. 批次与验收流程

1. 本 PR（B7a）：lint 门禁 + 定向测试 → 合 main → **主干重扫**按 alert number 做集合差。
2. 判定标准：闭合的必须 `state=fixed` 且 `dismissed_at=None`（自动闭合）。
3. 未闭合的：写进 `docs/TODO.md` §8，状态从「待 dismiss」改为「**未解，原因与下一步**」，**不点 dismiss**。
4. B7b 待用户拍板后另立方案与 PR。

## 6. 本批验证记录

- PR #38 首轮（仅去 base 的版本）：`Analyze (python)` / `Analyze (actions)` / `ci` / `ha` 均 pass，`CodeQL` 检查 fail——**2 new alerts (high)**，注解 `fs.py:99` / `fs.py:110`；`raw_sarif` 不经 REST 暴露（分析详情无该字段），改用消除法定位。本轮未合入。
- PR #38 次轮（不落路径文本 + `_input_shape`）本地实测：`lint_architecture.py` exit 0（P2/P4-2/P5/P6/P7/P8 全过）；`check_doc_sync.py` 0 警告；分 session 实跑 agent-core **281 passed / 3 skipped**、根 `tests` **500 passed / 17 skipped**、联邦 **152 passed**；`ruff check` 无告警。（本机无 CodeQL CLI，告警是否闭合以 PR 检查与主干重扫为准。）
- 待回填：次轮 PR 检查结果、合入后 `refs/heads/main` 重扫差集（预期 #34 与 #43/#44 闭合；#42 待看，PR 作用域本轮未报 path-injection）。
