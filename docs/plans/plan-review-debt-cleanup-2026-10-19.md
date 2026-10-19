# 评审延优清债方案：R8/R1（guard 面）· R5（DDL）· R10（workspace 隔离维）

> 2026-10-19。对象：`docs/TODO.md` §5 的 R1/R5/R8/R10 四条（nl2sql 合入前评审 #12/#16/#17 延优 + 第一批评审 #7）。
> 定位：这是**清债批**——R2/R3/R4/R6/R9 已同批先行落地（各自 issue 号引用），本文件覆盖剩下四条中"先方案后编码"的三条（R8/R5/R10）+ 与 R8 同文件的 R1。
> 红线依据：`AGENTS.md`「所有代码优化/重构必须先制定方案」；R8/R10 在 TODO 里即标注 **D·先方案后编码**，R5 标注"涉 DDL 迁移，先方案后动"。

---

## 1. R8（#120）：敏感列 L2 白名单的三条绕过路径——**是 bug，不是特性**

### 1.1 证据（代码实签，`packages/agent-core/agent_core/sql/guard.py`）

| 路径 | 机制 | 净效果 |
|---|---|---|
| 多表未限定列 | `_referenced_columns` 对未限定列"仅当只有一个真实表时归属该表，多表时不猜" ⇒ `SELECT phone AS p FROM a JOIN b` 的 `phone` 不进集合 | L2 不拒 |
| `SELECT *` | 星号不含 `exp.Column` 节点 ⇒ 集合为空 | L2 不拒（表级校验照过） |
| 别名 | 结果层 L3 脱敏按**结果键**匹配，键是别名 `p` 不在敏感集 | L3 不脱 |

⇒ `SELECT phone AS p FROM a JOIN b`：**既不拒也不脱，全链路静默放过**。默认单表查询正常拦，故是潜伏缺陷而非现网事故。

### 1.2 修法（按 TODO 登记的"修法方向"）

1. **多表未限定列任一脸命中即拒**：`_unqualified_sensitive_hits()`——未限定列在**任一**真实表里是敏感列即命中。不猜归属（猜错就是把 A 列当 B 列核），任一脸命中即拒；误杀面由 `sensitive_columns` 配置控制（策略面，不是代码面）。
2. **`SELECT *` 展开含敏感列的表即拒**：`_star_sensitive_hits()`——星号不可静态展开，只要任一候选表带敏感列就拒；候选表全干净时放行（不误伤 `SELECT * FROM orders`）。
3. **L3 不改**：别名绕过随 L2 拒绝自然消失（`a.phone AS p` 限定列本就被现路径拦；未限定列走新路径 1；星号走新路径 2）。L3 按结果键脱敏的语义保留——它是"漏网时兜底"，不是主闸。

### 1.3 判据

- `SELECT phone AS p FROM a JOIN b`（phone 在 a 敏感）→ 拒；
- `SELECT phone FROM a JOIN b`（b 也有 phone）→ 拒（任一脸）；
- `SELECT a.phone AS p FROM a JOIN b` → 拒（限定列现路径，回归不破）；
- `SELECT * FROM a JOIN b`（a 或 b 有敏感列）→ 拒；
- `SELECT * FROM orders`（无敏感列）→ 放行（不误伤）；
- 未配 `sensitive_columns` 时行为逐字节不变（policy 默认 None 的老调用方零影响）。

## 2. R1（#114）：危险函数黑名单补条——家族前缀化

### 2.1 证据

实测放行：`pg_advisory_lock(1)`、`lo_open`、`pg_ls_waldir()`、`dblink_send_query`、`pg_switch_wal()`。根因：黑名单是**精确名**匹配（`FORBIDDEN_FUNCTIONS` frozenset），同家族新成员逐个漏；`dblink` 精确名甚至拦不住 `dblink_send_query`（函数名归一后是全名）。

### 2.2 修法

精确名单保留，新增**家族前缀**拒（这些家族的全体成员都不该由 LLM 生成的 SQL 调用）：

| 前缀 | 家族 |
|---|---|
| `pg_advisory_` | 咨询锁（会话级持有 ⇒ DoS） |
| `lo_` | 大对象读写（`lo_open`/`lo_import`/`lo_export`…） |
| `pg_ls_` | 目录列举（`pg_ls_dir`/`pg_ls_waldir`/`pg_ls_logdir`…） |
| `dblink_` | 外部连接（可绕过只读语义） |

另补精确名 `pg_switch_wal`（不属上述家族）。schema 限定名（`pg_catalog.pg_sleep`）由既有归一覆盖，前缀匹配同样受益。

### 2.3 判据

五个实测放行函数全部拒；`lower/count/coalesce` 等正常函数不误伤；既有黑名单用例不回归。

## 3. R5（#117）：取值字典唯一键缺 `table_name` + 分词器版本无标记——**是 bug（数据层）**

### 3.1 证据

`001_meta_schema.up.sql`：`uq_nl2sql_value UNIQUE (tenant_id, workspace_id, datasource_id, column_name, value)`。同名列（`orders.status` vs `venues.status`）写第二个即**撞约束**；且行内无 `table_name` ⇒ 撞了也无法回溯所属表。`search_text` 无分词器版本标记 ⇒ 换 tokenizer 后既有 tsvector/search_text 静默失效（召回率悄悄降）。

### 3.2 修法（DDL 迁移 + 全链补 `table_name`）

1. **`002_value_info_table_name.up.sql`**（幂等，跟随 001 的对账路径风格）：
   - `ADD COLUMN IF NOT EXISTS table_name TEXT NOT NULL DEFAULT ''`；
   - `ADD COLUMN IF NOT EXISTS tokenizer TEXT NOT NULL DEFAULT ''`（分词器版本标记，构建方写入）；
   - 换唯一键：`DROP CONSTRAINT IF EXISTS uq_nl2sql_value` → `ADD CONSTRAINT uq_nl2sql_value UNIQUE (tenant_id, workspace_id, datasource_id, table_name, column_name, value)`。存量行 `table_name` 全为 `''` ⇒ 换键不破坏存量（键变宽只会更宽松）。
2. **写路径**：`meta_repository._VALUE_TABLE` 自然键加 `table_name`；`save_value` 透传；构建方（meta_knowledge_service 的取值构建）写 `table_name` + `tokenizer`。
3. **读路径**：`ValueRepository.recall` 的 `extra_cols` 加 `table_name`（结果可回溯所属表）；`prune_values` 的 keep 集加 `table_name`。
4. **分词器版本**：`tokenizer.py` 暴露当前 tokenizer 标识，构建时写入；**不**做存量重刷（无构建即无标记，空标记行按"未标"处理，读路径不消费）。

### 3.3 判据

- 同名列两表可共存（不再撞约束）且 recall 能区分所属表；
- 既有迁移/初始化用例不回归（001 的形状对账路径保留）；
- `prune_values` 的 keep 语义与键同构。

## 4. R10（#122）：`workspace_id` 无服务端断言路径——**隔离维缺一环（bug 带半特性）**

### 4.1 证据

`tenant_scope.py` docstring 自认"workspace 无独立 ContextVar 断言路径"；`resolve_scope` 的 workspace 取请求体 > default。tenant 维已被 #104 系列收口（服务端断言），workspace 维客户端可伪造 ⇒ 多工作区部署下归属维形同虚设。

### 4.2 定夺：**显式声明"enforce 前 workspace 不作为隔离维"**（不补断言机制）

理由：
1. 断言源不存在——身份门当前只签 tenant claim（#104），为 workspace 造一套 claim 机制是**无消费者的过度设计**（架构原则：最小必要优先）；
2. 真实危害不是"缺断言"本身，而是**读者误以为它隔离**——docstring 自认只对读代码的人可见，部署/配置面无人知晓；
3. 多工作区部署真实到来时再补断言（届时 claim 源、存储分片、查询谓词一起设计，才是完整特性）。

落地（纯文档决策，零行为变更）：
- `tenant_scope.py` docstring 补显式警告段（红线条目：不作为隔离维 + 伪造面 + 升级路径）；
- ADR-0007 增补一节（workspace 维的 enforce 前置条件与升级路径）；
- TODO R10 翻勾，处置记为"知情降级 + 升级路径在册"。

## 5. 批次与验证

| 项 | 形态 | 提交 |
|---|---|---|
| R8+R1 | `agent_core/sql/guard.py` + 测试 | 同批一笔（同文件同面，TODO 对 R1 的自注"宜并入下一批 guard 改动不单开分支"） |
| R5 | 002 迁移 + meta_repository + value_repository + 构建方 + 测试 | 独立一笔 |
| R10 | tenant_scope docstring + ADR-0007 + TODO 翻勾 | 独立一笔 |

验证：`make lint`（ruff + lint_architecture）、`check_doc_sync`、nl2sql 全量、agent-core 全量、governance sql_guard 用例、durability 用例、`recount_todo_index.py`。分支 `fix/review-debt-cleanup`，一个 PR 合回 feat（R2/R3/R4/R6/R9 已先行在同分支）。
