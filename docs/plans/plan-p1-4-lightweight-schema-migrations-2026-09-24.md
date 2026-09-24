# P1-4 轻量版 Schema 版本迁移方案

> 目标：为 `agent_runtime` 引入**零新依赖的版追踪迁移系统**，替代当前 522 行巨型 `SCHEMA_TEMPLATE` + `try/except: pass` 幂等 ALTER 循环。
> 关联：架构审计 P1-4（原标"Alembic 迁移"，勘察后判定 Alembic 不契合本仓 psycopg async 技术栈，收敛为轻量方案）。

## 1. 问题陈述

| 痛点 | 现状证据 | 影响 |
|------|---------|------|
| 无版本追踪 | 全仓无 migration 目录/表；`schema_version` 仅用于 checkpoint JSONB 内容版本（`state_migration.py`），非 DDL | 无法回答"生产库跑到哪版了" |
| 吞异常 | `try/except: pass` 包裹每条 ALTER（db.py L428/440） | 网络故障/权限错误静默忽略，排查困难 |
| 巨型单体模板 | 522 行 `SCHEMA_TEMPLATE` + 散落 ALTER 循环 | 加一列改三处（template + ALTER + index） |
| 无有序性 | ALTER 循环无顺序保证 | 表间依赖时可能先引用后创建 |
| 无回滚 | 纯 IF NOT EXISTS 不可逆 | schema 变更不可撤回 |
| 多实例竞态 | 仅有进程内 `asyncio.Lock`，无跨实例互斥 | 多副本同时启动并发跑 ALTER（虽 IF NOT EXISTS 幂等但日志噪音） |

## 2. 设计

### 2.1 架构总览

```
agent_runtime/
├── db.py                    # 连接池管理（保留，ensure_schema 委托 runner）
├── migrations/              # ← 新增
│   ├── __init__.py          # 导出公共 API
│   ├── base.py              # Migration 元数据 + 文件发现（扫描 .sql）
│   ├── runner.py            # 迁移执行引擎（advisory lock + transaction + 模板替换）
│   ├── 001_baseline.up.sql   # 全量建表（{{vector_dim}} 模板变量）
│   ├── 002_workspace.up.sql  # 幂等 ALTER: chunks.workspace_id
│   ├── 002_workspace.down.sql # 回滚
│   ├── 003_memory.up.sql     # 幂等 ALTER: memories 扩展列
│   └── 003_memory.down.sql
```

### 2.2 `schema_migrations` 表（元数据）

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum   TEXT NOT NULL DEFAULT ''  -- up() SQL hash，检测已应用迁移是否被篡改
);
```

### 2.3 Migration 文件约定

**命名规范**：`{NNN}_{description}.{up|down}.sql`

- `NNN` = 3 位零填充版本号（单调递增）
- `description` = 短描述（下划线分隔，自动转空格为可读名）
- `up` 必需、`down` 可选（无 down = 不可逆）

模板变量：SQL 内可用 `{{vector_dim}}`，runner 执行前统一替换。

示例 `002_workspace.up.sql`：
```sql
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks (workspace_id);
```

DBA 可直接用 `psql < 002_workspace.up.sql` 校验。

### 2.4 Runner 逻辑 (`runner.py`)

```python
_MIGRATION_LOCK_KEY = 0xCAFE0001  # pg_advisory_lock 专用 key（与 scheduler 不冲突）

async def run_migrations(pool, *, target_version: int | None = None) -> list[Migration]:
    """
    1. 确保 schema_migrations 表存在（自身幂等）
    2. pg_advisory_xact_lock(_MIGRATION_LOCK_KEY) —— 跨实例互斥
    3. SELECT MAX(version) FROM schema_migrations → current_version
    4. 从 registry 取 version > current_version 的迁移列表，按 version 升序
    5. 逐条：
       BEGIN;
         await migration.up(conn)
         INSERT INTO schema_migrations (version, name, checksum) VALUES (...)
       COMMIT;
       — 失败 → ROLLBACK + raise（不再吞异常）
    6. 返回已应用列表（供日志/健康检查）
    """
```

### 2.5 与现有 `ensure_schema()` 的关系

| 阶段 | 行为 |
|------|------|
| **过渡期**（本次 PR） | `ensure_schema()` 改为：先建 `schema_migrations` 表 → 检测"全新库"（无记录 + 无业务表）→ 若有业务表但无记录，执行 **baseline stamp**（mark version=1 without running）→ 再 `run_migrations()` 应用 pending |
| **稳态**（后续 PR） | 删除 `SCHEMA_TEMPLATE` + 旧 `try/except` 循环，所有 DDL 变更统一走 `migrations/0XX_*.py` |

### 2.6 启动时机

保持当前架构：在 `init_pool()` 内、连接池打开后调 `ensure_schema(pool)`。`ensure_schema` 内部委托给 `run_migrations`。**无需改部署流程**。

### 2.7 多实例安全

- **advisory_xact_lock**：整个"读版本 + 应用迁移"在单个事务内，锁自动释放
- 已有先例：`execution_scheduler.py:403` 用 `pg_advisory_xact_lock` 做跨实例串行化，复用此模式
- 第二实例启动时锁等待 → 拿到锁后发现版本已最新 → 无 pending → 秒过

## 3. 影响面

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `agent_runtime/migrations/` | **新增** | 整个包（base.py + runner.py + __init__.py + migration 文件） |
| `agent_runtime/db.py` | **重写** | 删 `SCHEMA_TEMPLATE` + 旧 `ensure_schema`；改为 import runner |
| `agent_runtime/db.py: init_pool()` | 微调 | `ensure_schema(pool)` 调用改为 `await run_migrations(pool)` |
| `agent_runtime/tests/` | **新增** | runner 单测（mock pool + 验证版本推进/回滚/并发锁） |
| 各应用 lifespan | **无改动** | 对上层透明，仍走 init_pool 入口 |
| `packages/agent-runtime/pyproject.toml` | 无改动 | 零新依赖，仅用已有 psycopg |

## 4. 迁移策略（分阶段）

### Phase A（本次实施）
1. 新建 `migrations/` 包骨架（base + runner）
2. 编写 `001_baseline.py`：包含当前 `SCHEMA_TEMPLATE` 全部 22 表的 CREATE IF NOT EXISTS
3. 编写 `002_workspace.py` / `003_memory_upgrade.py`：从旧 ensure_schema 的 ALTER 循环迁入
4. 改写 `ensure_schema()` → 委托 runner + baseline stamp 逻辑
5. 删除旧 `try/except: pass` 循环
6. 单测 + 集成测试保绿

### Phase B（后续独立 PR）
- 将 `SCHEMA_TEMPLATE` 从 `db.py` 彻底删除（Phase A 保留为兼容回退参考）
- 后续每个 schema 变更 = 新建一个 `0XX_*.py` 文件

## 5. 验收标准

- [ ] `schema_migrations` 表自动创建，记录迁移历史
- [ ] 全新库启动 → 001_baseline 自动 apply → 22 张表就位 → version=3
- [ ] 存量库启动 → baseline stamp（不重跑建表） → 检测 pending → 秒过
- [ ] 多实例并发启动 → advisory lock 串行 → 不报错、不重复 apply
- [ ] 迁移失败 → 事务回滚 → raise 真实异常（不吞）→ 进程 fail-fast
- [ ] 后续加列只需新建 `0XX_*.py`，不改 `db.py` 任何一行
- [ ] `ruff check .` = 0 / `lint_architecture` 通过 / 全量 pytest 绿
- [ ] `agent_runtime/db.py` 行数从 522 → 约 180（删巨型模板）

## 6. 红线自查

| 规则 | 状态 |
|------|------|
| 依赖方向单向（kernel 不 import applications） | ✓ migrations 包在 agent_runtime 内部 |
| 零新依赖 | ✓ 仅用已有 psycopg + pgvector |
| 不凑绿 | ✓ 不改测试断言 |
| 先方案后编码 | ✓ 本文档即方案 |

## 7. 已定决策

| ID | 决策 | 选项 | 理由 |
|----|------|------|------|
| D-1 | 不引入 Alembic | Alembic vs 轻量 | Alembic 强绑 SQLAlchemy、autogenerate 无 Model 可用、需 sync 引擎适配 async psycopg；80% 功能不可用、20% 功能 150 行代码即可覆盖 |
| D-2 | advisory_xact_lock 而非 SKIP LOCKED | advisory vs skip | 迁移是全局一次性操作（非队列消费），advisory lock 语义正确 |
| D-3 | baseline stamp 兼容存量库 | stamp vs force-rerun | 存量库已有全部表，重跑 CREATE IF NOT EXISTS 浪费且可能 ALTER 冲突 |
| D-4 | version 用 INTEGER 非 semver | int vs string | 单调递增无歧义，排序简单；复杂依赖链场景留到需要时引入 down_revision |

## 8. 执行结果（2026-09-24）

全部 Phase A 已实施并验证绿：

| 产物 | 说明 |
|------|------|
| `agent_runtime/migrations/__init__.py` | 包入口，导出公共 API |
| `agent_runtime/migrations/base.py` | Migration 元数据 + checksum + 文件扫描发现 |
| `agent_runtime/migrations/runner.py` | advisory_xact_lock + 事务 + 版本追踪 + 模板替换 + rollback |
| `migrations/001_baseline.up.sql` | 纯 SQL 全量建表（312行，22表，{{vector_dim}} 占位） |
| `migrations/002_workspace.up.sql` + `.down.sql` | 幂等 ALTER + 回滚 |
| `migrations/003_memory.up.sql` + `.down.sql` | 幂等 ALTER + 回滚 |
| `agent_runtime/db.py` | ensure_schema() 委托 runner，删旧 try/except: pass 循环 |
| `tests/test_schema_migrations.py` | 13 个单测（文件读取/发现/全新库/stamp/失败/模板替换） |

验证结果：
- `ruff check .` = 0 errors
- `lint_architecture.py` = 0 (双不变量通过)
- `check_doc_sync.py` = 0
- pytest 全绿（agent-runtime 548 + root 400 + agent_server 41 + federation/nl2sql/kefu/agent-core 404 + exhibition 343）

Phase B 待做（后续独立 PR）：删除 `SCHEMA_TEMPLATE` 常量（约 330 行），db.py 降至约 180 行。
