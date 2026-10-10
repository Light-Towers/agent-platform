# 方案：存量库列缺口（execution_leases.generation 等 4 列）——主链路硬阻塞修复（2026-10-10）

> 立项来源：演示版最小可执行切片第 0 天的基线核对。方案原文（`演示版最小可执行切片_c2432705.md`）
> 的前提是「重建镜像 + 分发即得到可用主链路」。**本轮实跑证伪了该前提的一个环节**：
> 集群库是**存量库被 stamp 过的库**，baseline 的 DDL 从未真正执行，因此改代码/重建镜像都不会补上缺的列。
> 本方案只解决这一件事，属演示版第 0 天的前置修复，不改演示版的范围与排期结论。

## 1. 现象与实测事实（全部为 2026-10-10 stdout 读数，非推断）

**现象**：不带密钥打 `POST /query`，SSE 先正常吐 `event: route`，随即吐错误事件：

```
data: {"type": "error", "error": "column \"generation\" of relation \"execution_leases\" does not exist
LINE 1: ...execution_leases (execution_id, owner, expires_at, generation..."}
```

**读数 1 — 线上表确实没有该列**（`information_schema` 直查，namespace `agent-platform`，pod `postgres-6ff4688bb8-vn7v6`，库 `agent_platform`，用户 `agent`）：

| 表 | 线上实际列 | baseline 声明 | 差集 |
|---|---|---|---|
| `execution_leases` | execution_id, owner, expires_at | + generation | **generation** |
| `execution_checkpoints` | execution_id, completed, updated_at, resumable, version | + generation, state_schema_version | **generation, state_schema_version** |
| `semantic_cache` | cache_key, question, answer, embedding, created_at, … | + tenant_id | **tenant_id** |

全库逐表比对（脚本 = 解析 `migrations/*.up.sql` 的 `CREATE TABLE` + `ADD COLUMN` 声明面，与线上
`information_schema.columns` 223 行做集合差）：**缺列总数 = 4**，且线上无「HEAD 未声明的多余列」。

**读数 2 — 不是「镜像旧、重建即对齐」**：运行 rev `626ec17` 的 `001_baseline.up.sql` **已包含** `generation BIGINT NOT NULL DEFAULT 1`（在 126 上 `git show 626ec17:<path>` 取到），而线上表没有它 ⇒ 这张表**不是这段 SQL 建的**。

**读数 3 — 成因**：`schema_migrations` 里 1..10 的 `applied_at` **完全相同**（`2026-09-30 02:38:43.941711+00`），name 为 `baseline`/`workspace`/… ⇒ 走的是 `runner._try_baseline_stamp()` 的 **stamp 路径（只记版本、不执行 DDL）**。此后 `CREATE TABLE IF NOT EXISTS` 对已存在的旧形状表是永久 no-op，增量链 002..010 又从未覆盖这几列 ⇒ **缺口不会随重建收敛**。

**读数 4 — checksum 无漂移（一处必须记录的取证陷阱）**：曾一度判为「HEAD 的 v1–v4 与库内 checksum 漂移 ⇒ 新 pod 启动即 `MigrationError` CrashLoop」，**该结论作废**。实为**本机取证方法的假阳性**：

```
v1 001_baseline  blob(git show)=3b9a8357  worktree=03dbb05a  git ls-files --eol: i/lf w/crlf
```

Windows 工作区把这几个 .sql 检成了 **CRLF**（`attr/text=auto eol=lf` 未生效于已存在的 w/crlf），而
`Migration.checksum()` 取的是**文件字节**。126 上是 git checkout（天然 LF），其 blob 值 `3b9a8357/97ac454c/d44fa3bf/cd910723`
与库内记录**逐字相同** ⇒ 运行 rev 与新 rev 均无漂移、启动不会因 checksum 失败。
⇒ **纪律**：任何在 Windows 侧取 migration checksum 的比对必须以 `git show` 的 blob 字节为准，不得以工作区文件字节为准。

## 2. 影响面（按可观测性分三档，不得混写）

| 档 | 缺列 | 后果 | 现场表现 |
|---|---|---|---|
| **硬阻塞** | `execution_leases.generation` | `PlannerRuntime.execution()` **每次进入执行边界都 acquire 租约**（`protocol.py:522` → `durability_pg.py:219` 的 INSERT 带 generation 列） ⇒ 默认 deterministic planner 的 `/query` **必然失败** | SSE 吐 error；演示版六个环节里 1/2/3/4/5 全塌 |
| 次级 | `execution_checkpoints.generation` + `state_schema_version` | checkpoint 落库与 generation fencing 失效（HA/resume 面） | 本版不展示该面，但它是真实的写失败 |
| **静默** | `semantic_cache.tenant_id` | `cache_lookup`（`cache.py:51` 带 `WHERE tenant_id = %s`）与 `_cache_write`（L91）都异常，但被 `except Exception: logger.exception(...); return None` 与「失败静默」吞掉 ⇒ **缓存永久 miss、缓存写永久丢**，只留日志 | `/health` 与页面**都不报**；属观测方案登记的「关了和坏了分不清」同族 |

⇒ 第一档使演示版第 0 天的完成标志（「真实问一次能答」）无法达成，**不修则后面 8 天全部悬空**。

## 3. 目标与非目标

**目标**
1. 让存量库补齐这 4 列，`/query` 主链路真实跑通。
2. 修复**升级路径本身**而非只修这台机器：新建库上该修复必须是 no-op。
3. 幂等、可回滚、有用例钉住（对齐本仓 v6 的既有先例与写法）。
4. 把「同类缺口第三次出现」堵住：加一条**基线列存在性门禁**（见 §5）。

**非目标**
- 不动 baseline SQL 文件本身（改它=制造 checksum 漂移，正是 §1 读数 4 那个陷阱）。
- 不改任何业务代码语义、不引入新依赖。
- 不处理「stamp 路径应否同时校验列形状」的彻底重构（那是 §5 门禁的议题，本方案只加检查不加改造）。

## 4. 迁移策略（首选：新增增量 migration v11）

新增 `packages/agent-runtime/agent_runtime/migrations/011_existing_db_column_gap.up.sql` / `.down.sql`，
形态与 v6 的「存量库升级路径补列」注释与写法一致：

```sql
ALTER TABLE execution_leases      ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 1;
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS generation BIGINT;
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS state_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE semantic_cache        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
```

- 列定义**逐一对齐 `001_baseline` 现行声明**（type / nullability / default），不新造口径。
- `semantic_cache.tenant_id` 取 `DEFAULT 'default'` 而非 baseline 的 `''`：与 v6（chunks/sql_*）、v10（episodic/procedural）
  的隔离谓词口径一致，且线上现有 2 行归入 default 桶后**不会被真实租户读到**（同 v5「无过渡期跨租户读」语义）。
- 新库路径：baseline 已自带这些列 ⇒ 四条 ALTER 全部 `IF NOT EXISTS` no-op。
- 回滚：`.down.sql` 用 `DROP COLUMN IF EXISTS`，只回滚 schema、不做破坏性数据重写（对齐 v6 down 的政策）。
- 装配：无需接线。`run_migrations()` 在 lifespan 启动期自动应用 pending（`main.py` 现有路径），属**全局装配已由构造保证**。

**验收用例**（红线：不得拿放宽断言凑绿）
- 在真实 PG 上钉「存量旧形状库（手建无 generation 的 execution_leases / 无 tenant_id 的 semantic_cache）经 v11 后可正常 acquire 与 cache_lookup」，进 `tests/ha`（该套件本就以真实 pgvector PG 为前置，缺环境即 skip 属设计意图）。
- 钉「v11 在全新库上是 no-op」（跑完 baseline 再跑 v11，列集合不变）。
- 现有 `tests/durability/test_pg_durability.py`、`tests/governance/test_isolation_dimension_contract.py` 必须仍绿（不得改断言）。

## 5. 强制门禁（本类的第三次预防）

v6 注释自述 2026-09-30 R6 已因**同一形态**崩过一次（sql_* 缺 workspace_id）。本轮 4 列是第二次。
按 AGENTS.md「三层齐备才算全局解」，只有 ALTER 属「单一实现 + 装配」，缺门禁则迟早第三次。

候选（**待拍板，本方案不擅自选定**）：
- ① 扩 `scripts/lint_architecture.py`？——**不合适**：它是静态全仓扫描，看不见运行库形态。
- ② 加一条只读脚本 `scripts/audit_schema_drift.py`：对任意给定 DSN，比对「migrations 声明面列集合」vs「库内实际列集合」，有差集即非零退出；接入 CI 的 nightly 或真集群验收环节（不接 `make lint`，因 CI 无真集群库）。
- ③ 只登记为技术债，本版不做。

本方案作者意见：**取 ②**，且脚本已在 §1 以一次性形式验证过逻辑可用（本轮实测即由该比对得出 4 列差集），落仓成本低。

## 6. 备选方案（若需求方更倾向「不新增 migration」）

| 选项 | 动作 | 代价 | 判定 |
|---|---|---|---|
| A（本方案首选） | 新增 v11 增量 migration | 一个 SQL 文件 + down 文件 + 用例 | 修的是**升级路径**，新库/存量库都对 |
| B | 清空并重建集群库（drop schema 后由 baseline 全新建表） | 破坏性；线上 2 行 semantic_cache + 1 个 checkpoint thread 丢失（其余表实测均 0 行） | 只让**这台机器**变好，升级路径缺陷原样留在仓里；且在共用环境上做破坏性操作，须单独授权 |
| C | 手工在库上 `ALTER` 一次，不入仓 | 最小 | **即 AGENTS.md 明令禁止的第二条代码通道**（线上与仓库漂移），不采纳 |

## 7. 排期影响

**不新增天数**：A 方案的一次构建本就要跑（演示版第 1 天为语义检索依赖改 `Dockerfile` 并重建分发）。
v11 随同一次构建上线，第 0 天末即可用它验掉「真实问一次能答」这一完成标志。

## 8. 复现命令（全部只读）

```bash
# 缺列差集（本机，工作区须与 HEAD 一致）
ssh 126 "kubectl -n agent-platform exec <pgpod> -- psql -U agent -d agent_platform -tA -F'|' \
  -c \"select table_name||' '||column_name||' '||data_type||' '||is_nullable||' '||coalesce(column_default,'NULLDEFAULT') \
      from information_schema.columns where table_schema='public' order by table_name, ordinal_position\"" > live_cols.txt
# 与 migrations 声明面取集合差（脚本见 §1，判据：missing_total=4）

# stamp 证据（四版本同刻 ⇒ 未执行 DDL）
... -c "select version||' | '||name||' | '||applied_at::text from schema_migrations order by version"

# 证伪「重建即对齐」：运行 rev 的 baseline 已含该列
ssh 126 "git -C /opt/agent-platform show 626ec17:packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql \
  | sed -n '/CREATE TABLE IF NOT EXISTS execution_leases/,/);/p'"

# §1 读数 4 的取证纪律（blob 而非工作区字节）
git show HEAD:packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql | sha256sum | cut -c1-8
git ls-files --eol packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql
```
