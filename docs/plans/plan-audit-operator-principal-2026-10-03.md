# 方案：会话回退审计主体去凭据化（`revert_audit.operator` 取服务端断言主体）

> 状态：**待拍板**（红线「所有代码优化/重构必须先制定方案」——本文档未动一行业务代码）。
> 来源：`docs/TODO.md` §5 L73（B7b 收尾时登记，标注「属安全语义而非可读性」）。
> 关联真相源：`docs/adr/0007-server-asserted-tenant-identity.md`、`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md`（B7b-4 已把**会话身份**主体化，本方案是同一语义在**审计主体**上的收尾）。

## 1. 问题定性（全部实取，非推断）

### 1.1 缺陷链
`applications/agent_server/api/session_router.py:57` 目前是：

```python
operator = api_key or "default"          # api_key ← Depends(verify_api_key) 的返回值
result = await revert_handler.revert(operator, req.session_id, req.checkpoint_id)
```

而 `verify_api_key`（`api/auth.py:23-29`）**返回入站头原文** `x_api_key`（不是摘要、不是 id）。⇒ 今天写进审计的「操作人」**就是明文部署密钥本身**。

值往下走两条出口（`packages/agent-runtime/agent_runtime/revert.py`）：

| 出口 | 位置 | 后果 |
|------|------|------|
| PG 模式 | `:131-143` `INSERT INTO revert_audit (..., operator, ...)` | 明文密钥**持久化**进 `revert_audit.operator`（`migrations/001_baseline.up.sql:85-95`，`TEXT NOT NULL` + `idx_revert_operator`） |
| 内存模式 | `:147-155` `logger.info("revert_audit ... operator=%s ...")` | 明文密钥**写进应用日志**（容器 stdout / 日志文件，保留期与外泄面由部署决定） |

两条出口都在 `spawn_background(...)` 里异步执行，失败仅 `logger.warning` ⇒ 现状不会因改值而报错。

### 1.2 为什么 CodeQL 没报（说清以免被当成"没问题"）
主干 `refs/heads/main` 告警面实取为 **open 0 / dismissed 0**（2026-10-03 B7b b3 复验），`py/clear-text-logging-sensitive-data` 也没有命中这条站点——它的检出依赖「值经数据流被分类为 secret」，而这里凭据经**函数形参 `operator`** 跨模块（app→runtime）传入，规则未把 `verify_api_key` 的返回值接到该流上。**未报出 ≠ 不存在**：本项由人工语义审计发现并登记于 TODO L73，处置不依赖告警面板。

### 1.3 消费面（决定兼容成本，否定式断言逐条 grep）
全仓 `revert_audit` 命中 **10 处**，分类实取：

- 建表与索引：`migrations/001_baseline.up.sql:85-95`；迁移在册清单 `migrations/runner.py:37`。
- 写入：`revert.py:131`（INSERT）、`revert.py:148`（日志行）。
- 治理白名单：`tests/governance/test_isolation_dimension_contract.py:43`（该表按「系统/审计表」豁免 `tenant_id` 列）。
- 测试：`packages/agent-runtime/tests/test_revert.py:115-137` 两条，均以**字面量 `"test_user"`** 直接调 handler，不经 router。

⇒ **`SELECT ... FROM revert_audit` 全仓 0 处**：该列是 write-only，无仓内读取方、无对外 API（`api/control.py` / `health_router.py` 均不暴露审计）、仓库无前端工程（`docs/TODO.md` §1 实取）。**换值形状不破任何已知消费者**。

同类站点已排查（证明本项是唯一处）：

| 审计点 | 是否含凭据 | 证据 |
|--------|-----------|------|
| `capabilities.py:143 _audit_sink`（Skill 调用审计） | 否，只记 `name/latency/error`，且 `AuditMiddleware(redact=True)` | 文件实读 |
| MCP 调用审计 `mcp_client.py`（`mcp_call_audit.caller`） | 否，`caller` 为静态标识（默认 `"skill_registry"`） | `skills/mcp.py:30` |
| 会话回退审计 `revert_audit.operator` | **是（本项）** | §1.1 |

### 1.4 现状语义的一个必须写破的事实（等价性论证的前提）
`API_KEY` 每部署一把（`config.py` 的 `settings.api_key`）。⇒ 「按密钥区分操作人」在今天的部署形态下**本来就区分不出任何两个调用方**：同一部署所有客户端的 `operator` 值完全相同。换成服务端断言租户，**基数不变（仍是 1）**，变的只是「值不再是一把可用密钥」。这与 B7b-4 §3.4 对会话桶的论证同构，不是本方案新造的假设。

开发模式（`settings.api_key` 为空）今天得到 `operator = "default"`；改后得到 `server_tenant_id(default_tenant_id)` = 配置的 `DEFAULT_TENANT_ID`（默认 `"default"`）⇒ 开发模式取值不变。

## 2. 目标与非目标

**目标**
1. 审计主体不再来自凭据（明文密钥不再进 DB、不再进日志）。
2. 主体来源与 B7b-4 同源：ContextVar 断言优先，其次部署级 `DEFAULT_TENANT_ID`——不新增第二套身份机制。
3. 三层齐备：单一实现在位（复用 `server_tenant_id`）+ 装配不散落（改既有站点）+ **强制门禁**（新增 lint 不变量拦截未来把凭据当主体的写法）。

**非目标**
- 不改 `revert_audit` 表结构（不加 `tenant_id` 列；它按 ADR-0006 属"系统/审计表"白名单，改动另议）。
- 不做用户级（`user_id`）细化归因：约束 A（`server_user_id()` 零生产消费者）与约束 B（联邦 `identity_bridge.py` 显式丢弃 user）未解除，属 A5 批次。
- 不在代码里自动清洗/删除历史审计行（销毁审计痕迹需人工决策）。

## 3. 方案选型（三条，选定 A）

| 代号 | 取值 | 判定 |
|------|------|------|
| **A** | `operator = server_tenant_id(settings.default_tenant_id)` | ✅ 采纳。与 `import_router.py:48` / `sql_router.py:29` / `capabilities.py:91` / B7b-4 `auth.py:43` **逐字同写法**（已是仓内既定惯例，非新发明）；基数等价（§1.4）；开发模式值不变 |
| B | user 优先、租户兜底（`server_user_id()`） | ❌ 本批不取。默认部署无 user 断言 ⇒ 需再引一套兜底策略，且 fail-fast 路径会破坏零依赖冒烟；归 A5 |
| C | 保留"按密钥归因"，改用服务端可验证的 key id | ❌ 不取。需要新增 key→主体映射能力（与 B7b-2 Q4「不恢复每密钥语义」的已拍板口径一致），且审计主体本就该是租户/用户而非一把密钥 |

**值形状（Q1，需拍板）**：
- **(a) 存租户原值**（推荐）：`operator` = 断言/配置的租户字符串，与库里其它表的 `tenant_id` 同形，跨表 join 直观。新旧行判别用 `reverted_at < 升级时刻`（由代码保证，非启发式）。
- (b) 存 `tenant-<id>` 带前缀形态：与 `thread_id` 形状一致，好处是行内自解释；代价是引入第二个命名空间，且 A5 换 user 主体时前缀要再改一次。

⇒ 推荐 **(a)**：前缀属 thread-id 命名空间，审计主体列不该复制它。

## 4. 实施步骤（单 PR，可整体回滚）

1. `applications/agent_server/api/session_router.py`
   - `operator = api_key or "default"` → `operator = server_tenant_id(settings.default_tenant_id)`；
   - 形参 `api_key=Depends(verify_api_key)` → `_auth=Depends(verify_api_key)`（**签名级**去掉凭据可见性，与 B7b-2/B7b-4 同构；FastAPI 的 `Depends` 只认 callable，形参名不参与解析 ⇒ 鉴权行为逐字不变）；
   - 新增 `from agent_runtime.workspace_registry import server_tenant_id`（依赖方向 app → agent-runtime，红线 1 合规）。
2. 同批清理两处**死凭据绑定**（`api_key=Depends(verify_api_key)` 但函数体从不使用）：`import_router.py:28`、`sql_router.py:21` 改名 `_auth`。零行为变更，收益是 §4.4 的门禁可以**零白名单**落地（不必给"绑了但没用"开后门）。
3. 强制门禁（P12，新 lint 不变量，落 `scripts/lint_architecture.py`，计入 `make lint`/`make ci`）：
   - 判据（AST，仅扫 `applications/**`）：凡函数形参的默认值为 `Depends(<credential_dep>)`（在册名单：`verify_api_key`）者，其**形参名不得作为任何 `Call` 的实参**（位置或关键字）出现于该函数体内。违规即 CI 失败。
   - 已知局限（必须写进 docstring，不得当作完备门禁）：AST 名匹配抓不到「先赋给别名再传」的间接流；抓不到 kernel 内部对凭据的处理（那是 P6 的地盘）。⇒ 定位是**防未来漂移的粗筛**，与 §5 的行为用例互补。
   - 不引入白名单：步骤 2 完成后全仓应恰为 0 违规。
4. 行为用例（`tests/governance/test_auth.py` 同目录新增或扩写）：
   - 断言 `/session/revert` 传给 handler 的 `operator` **等于** `server_tenant_id(get_settings().default_tenant_id)`；
   - 反向断言 `operator != <入站密钥值>`（凭据不得出现在审计参数位）；
   - 绑定 `IdentityMiddleware` 断言租户（`bind_tenant_context`）时取到断言值而非部署 default，验证"ContextVar 优先"；
   - 回归锁：门禁 P12 在**合成源码**上必红（照 `test_isolation_dimension_contract.py:133` 的做法，不往真实代码注脏）。

## 5. 迁移与既存数据处置

- **schema**：无变更（列名、类型、索引全部保留）⇒ 无 migration、无停机窗口。
- **历史行**：`reverted_at < 升级时刻` 的 `operator` 值是明文密钥（或 `"default"`）。代码侧**不自动改写**（红线：不静默销毁审计痕迹）。给运维的**可选**脱敏语句（写进部署交接文档，由人决定是否执行）：

  ```sql
  -- 可选：升级后把旧行的凭据形态替换为不可逆标记（代价：旧行失去区分度）
  UPDATE revert_audit SET operator = 'legacy-credential-redacted'
   WHERE reverted_at < '<升级部署时刻>';
  ```

- **日志**：已落盘的旧日志随保留期自然过期；升级即停止新增。**运维动作**：若历史日志的访问面大于运维范围，按 B7b 惯例轮换 `API_KEY`（改值即失效，无需其它配合动作——凭据已不参与任何派生）。
- **存量是否真有非零旧行未取证**（同 TODO L99 的部署侧受阻现状，见 §7）。⇒ 本方案不得表述为"存量已核实/已清理"。

## 6. 验收标准（硬指标，全部可实跑）

| # | 判据 | 取法 |
|---|------|------|
| 1 | `git grep -n "operator = api_key"` **0 命中**；`session_router.py` 无 `api_key` 名字 | 本地命令 |
| 2 | `scripts/lint_architecture.py` P12 exit 0，且合成违规源必红 | 本地 + CI |
| 3 | 新用例：`operator == server_tenant_id(...)` 且 `!= api_key` 全绿 | `uv run pytest tests/governance -q` |
| 4 | 受影响 session 全绿：governance（根 session 内）、agent-runtime（`test_revert.py` 未动断言方向）、agent_server | 按 AGENTS 分层验证 |
| 5 | `ruff check .` / `check_doc_sync.py` exit 0 | 本地 |
| 6 | **主干面**：合入后 `refs/heads/main` 重扫 `open=0 / dismissed=0` 不回退，`ci`/`assembly` success（PR 绿 ≠ 主干绿）；**`ha` 已删——本批不命中 `ha.yml` 的触发路径，属「不适用」而非「漏跑」**（写在本行原文里会让人下次去找一个不会存在的 check） | `gh api` 实取 |
| 7 | 账面：CHANGELOG 新增本批段 + `docs/TODO.md` L73 转 `[x]`（附测量时点 sha） | 人工 |

## 7. 未取证 / 风险登记（不美化）

- 部署侧「存量 `revert_audit` 行数与非零旧值」**未取证**：本机无 docker / 无 kubectl / 无 `~/.kube/config` / 无 `.env`，`root@192.168.100.126:22` 仍在 banner 交换前被关闭（2026-10-03 再试 1 次，同签名 `Connection closed by ... port 22`）。⇒ 「历史上是否曾有密钥被写进库/日志」只能由运维在可达环境查证，代跑命令见 `docs/operations/audit-operator-principal-runbook.md`（本方案步骤 5 的配套）。
- `revert_enabled` 默认 `True`（`config.py:90`）⇒ 该缺陷在任何启用 PG 的部署里都真实可触发，不能按"没人用"降级。
- P12 属**名匹配**粗筛（§4.3 局限）：不得在文档或汇报中声称"已具备凭据不入审计的全局完备门禁"。

## 8. 拍板项（需用户确认后开工）

| Q | 选项 | 建议 |
|---|------|------|
| Q1 | `operator` 值形状：(a) 租户原值 / (b) `tenant-` 前缀 | **(a)** |
| Q2 | 是否同批清理 `import_router` / `sql_router` 的两处死凭据绑定（步骤 2） | **是**（否则 P12 需带白名单，门禁退化为约定） |
| Q3 | 历史行脱敏：(a) 只出运维 SQL 不自动执行 / (b) 随本 PR 自动 `UPDATE` | **(a)**（审计痕迹不静默销毁） |
| Q4 | 门禁层：(a) 新增 P12 lint + 行为用例 / (b) 仅行为用例 | **(a)**（AGENTS「三层齐备」） |

**拍板结果（2026-10-03）**：Q1–Q4 **均按建议选项全部实施**（单 PR 做完）；同批追加一项用户拍板：ks shim 守卫用例「落」。

## 9. 实施后记（2026-10-03，本地验收 + 合入 + 主干复验均已完成）

- **实际落地**：`session_router.py`（`operator = server_tenant_id(settings.default_tenant_id)` + `_auth=` + docstring）、`import_router.py:28` / `sql_router.py:21`（`_auth=`）、`scripts/lint_architecture.py` 新增 P12（`main()` 接 `v14`）、`ARCHITECTURE.md` §4.1 登记行；新用例 `tests/governance/test_audit_operator_principal.py`（29）+ `applications/knowledge-service/tests/unit/test_tracing_reset_hook_contract.py`（8）。
- **验收实取（命令逐条对齐 Makefile，extras 两种形态都跑）**：判据 1–5 **已达**——lint rc=0（14 条全过，单跑 253s）、ruff rc=0、docsync rc=0、根 session **964 passed / 8 skipped / 28 deselected**（基线 935 + 新文件 29）、runtime 594/1、agent_server 44、ks SDK 在场 **410/7** 与不在场 **404/13**（基线 402/396 各 +8 ⇒ 契约用例形态无关）。判据 6 与判据 7 已达，证据见本节后文「判据 7（commit/PR）与判据 6（主干面）」条。
- **§6 判据 1 的表述订正（写计划时没实跑留下的偏差）**：原写「`session_router.py` 无 `api_key` 名字」——实取后剩余命中是 `verify_api_key`（import 的依赖本体，**应该存在**）与 docstring 叙述；能被守门的是「**无名为 `api_key` 的形参**」与「凭据形参在体内完全不被引用」（后者已做成用例，比 P12 更严）。判据本身不改，但只能按订正后的形状验收。
- **实施中发现的计划外事实（P12 首跑假阳性）**：fail-closed 用 `encoding="utf-8"` + `ast.parse` 会把仓内 **10 个已入库的 UTF-8 BOM** `nl2sql_service/**/__init__.py` 误报为「无法解析」（rc=1，10 条假红）。Python 源码加载器本身剥 BOM（PEP 263），这些文件 import 一直正常 ⇒ **不是架构违规，是读取约定不对**。已改 `utf-8-sig`，并新增两条用例锁住修正的边界（语法真坏仍报 / BOM 文件里的真外流仍报）。教训：**假阳性会把门禁的首批用户训练成“改宽它”**，其危害不低于漏报；新门禁首次实跑必须逐条看违规是不是真的。
- **计划外顺带度量**：`lint_architecture.py` 单跑 **253s**（全仓 rglob + AST）——写自动化验证时需按此设超时，否则“前台无输出”会被误读为脚本挂住。
- **判据 7（commit/PR）与判据 6（主干面）已达**：L3 深度安全评审 **0 findings** → commit `116d51b`（12 files，+934/−8）→ **PR #61**（本仓自有门禁全 pass，CodeQL check-run annotations 0；另有一条 GitHub 侧 AI findings 红，见下文订正）→ merge commit **`bb2b9a8`** @ `2026-10-03T13:09:29Z`；merge 树 OID `7ecbdff3f333b04b3ac09cb15b85573607660eca` 与 PR head 树全等（实取：`git rev-parse "116d51b^{tree}"` 与 `"bb2b9a8^{tree}"` 均为该值）⇒ 未夹带 PR 外内容，§4 的计数可直接归给主干 tip。判据 6 七项**全部实取、总体 PASS**：主干重扫确已按 sha 绑定跑在 `bb2b9a8` 上（analysis `1885966935` python @ 13:10:46Z / `1885965733` actions @ 13:10:02Z，`ref=refs/heads/main`，`results_count` 均 0）、**open 0 / `dismissed_at` 非空 0 / 最大告警号 48 不增 / 合入时刻后新建 0 / `ci`・`assembly`・两个 `Analyze` 全 success / 同 tip 其余 check-run 0 个**。取证据脚本：`.codeartsdoer/temp/verify_main_p12.py`（七项均 fail-closed，不「查不到当通过」）；详细表格与 API 踩坑（`?dismissed=` 不是有效过滤、`-X` 是 HTTP method、check-runs 带 `-f per_page` 偶发 404、analyses 列表的 `commit_sha` 在顶层而非 `most_recent_instance`）见 CHANGELOG「审计主体去凭据化（实施）」§6。
- **判据 6 取证据时的两处实取订正（不改判据强度，只改字面）**：
  - `ha`：**不触发是路径过滤的结果**——`ha.yml` 的 `paths` 是 `packages/**`・`tests/ha/**`・`scripts/ha_real_kill_verify.py`・`Makefile` 等，本批只改 `applications/**` + `scripts/lint_architecture.py` + `tests/governance/` + docs，故 push/PR 两个触发块均未命中；旁证为近 300 次 run 窗口内 `agent-platform-ha` 48/48 success。本批对应的 HA 门禁是 `ha-assembly.yml` 的 `assembly` job（`paths` 含 `applications/**`），已实取 success。原表已按此订正。
  - PR head 上另有一条**非本仓门禁的红**：`github-advanced-security`（app=github-actions）= GitHub 自家 `Code scanning AI findings on PR #61`（`event=dynamic`，非仓内 workflow），job `111207991148` 日志实取为 **`402 / errorCode "quota"` 「You have exceeded your monthly quota」**；它对 #33〜#61 几乎条条 failure（仅 #45〜#47 success）、不必需、仅 PR 触发。⇒ 不规为本批缺陷，但也不得计入「全绿」；已登记 `docs/TODO.md` §8。取证据脚本已加 **[G]：同 tip 其余任何非 success 的 check-run 一律逐条报红，不设白名单**（白名单就是下一个被误读成「已定性」的黑洞）。
- **本方案仍开开的只剩两条外部条件依赖项**：① 部署侧 `revert_audit.operator` 存量历史行取证（本机 docker/kubectl/SSH 三通道均不通，代跑命令在 `docs/operations/audit-operator-principal-runbook.md`）；② P12 的三条局限（别名间接流 / `return` 外流 / kernel 侧归 P6）是**设计内残留面**，不是待办项，不得被当成已闭合。
- **未改变的本方案约束**：P12 仍是名匹配粗筛（§4.3 三条局限逐字成立，已同步到 `ARCHITECTURE.md` §4.1 与用例 docstring）；旧审计行不自动改写（Q3 (a)）；部署侧存量仍未取证（runbook 待运维代跑）。
