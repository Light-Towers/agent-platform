# 方案：M5 连接池关闭竞态 + M3 日志框架统一（v2 修订）

> 状态：**Approved with changes（M5）/ Needs revision→已修订（M3）**
> 关联：§20 生产部署就绪的中优先级架构债（可靠性基础设施修复，不做大规模架构重构）
> 约束：遵循 `AGENTS.md` —— 重构/优化先出方案，确认后再动手；本方案已按评审意见修订。

设计原则（评审定稿）：
1. **M5 = Shutdown correctness**：解决 DB pool 生命周期竞态，**不承担 Durable Execution**（不保证任务失败后从 checkpoint 自动恢复）。
2. **M3 = Observability correctness**：统一的是 **logging 配置（handler/level/propagation/format）**，不是强制所有业务模块统一 `get_logger()` API。
3. `agent_core.logging` 作为配置入口，但**不通过 logger name 重写或过度控制宿主应用**。

---

## 一、M5：连接池关闭竞态（`packages/agent-runtime/agent_runtime/db.py`）

### 1.1 目标
消除 `close_pool()` 在多副本优雅关闭（SIGTERM → lifespan shutdown）时的竞态：
- 并发/重复调用 `close_pool` 安全（幂等、不抛错，真实关闭仅一次）。
- 关闭进行中，新请求 `get_pool()` 立即返回 `None`（优雅降级），不从「关闭中」的池借用连接。
- **优雅等待已有连接归还，设置关闭等待上限（timeout）；达到上限后允许关闭流程继续，不阻塞进程退出**。timeout ≠ 强关 ≠ 取消在途请求。
- `close()` 自身异常被记录，`_closing` 复位，绝不永久卡死 runtime。

### 1.2 影响面
- 唯一实现点：`agent_runtime/db.py` 的 `close_pool()` 与 `init_pool()`。
- 调用方（仅 lifespan 关闭路径，行为不变）：`agent_server/main.py:253`、`agent_federation/api/server.py:115`、`scripts/smoke_query_real.py:91,108`。
- 不涉及接口签名变化（`close_pool()` / `get_pool()` / `init_pool()` 保持原签名）。
- 不引入状态机复杂度，保持 `_pool: Pool | None` + `_closing: bool`。

### 1.3 实现策略
1. 新增模块级 `_closing: bool = False`。
2. `close_pool()`：
   - 进入 `_pool_lock`；若 `_pool is None or _closing` → 直接返回（幂等）。
   - 置 `_closing = True`；将当前池赋给局部 `pool`；**立即 `_pool = None`**（新请求 `get_pool()` 返回 None，避免从关闭中池借用）。
   - 退出锁后 `try: await pool.close(timeout=30)`；`except Exception as e: logger.warning("连接池关闭异常(忽略): %s", e)`；`finally: _closing = False`。
   - 语义：先摘全局池 → 停止接受新使用 → 优雅等待在途连接归还（最多 30s）→ 记录异常/超时 → 允许进程继续退出。
3. `init_pool()`：在锁内增加早退——`if _closing: logger.warning("连接池正在关闭，跳过初始化"); return None`；其后 `if _pool is not None: return _pool`。保证 CLOSING 状态下**绝不创建第二个池**。

### 1.4 验收标准（增强测试 `tests/test_db_pool_close.py`）
- **Case A（关闭前已借连接）**：`conn = await pool.connection()` 后 `close_pool()`，该 `conn` 仍可正常 `execute` 并释放，池最终关闭。
- **Case B（关闭后新请求）**：`close_pool()` 后 `get_pool() is None`。
- **Case C（关闭中 init）**：`close_pool()` 进行中 `init_pool()` 返回 `None`，不产生第二个池。
- **Case D（重复 close）**：连续 N 次 `close_pool()`，真实 `pool.close()` 仅执行一次（用 mock 计数断言）。
- **Case E（close 自身异常）**：mock `pool.close()` 抛异常 → 异常被 `logger.warning` 记录，`_closing` 复位为 `False`（不永久卡死）。
- 现有 `tests/`(350) + `agent_federation/tests/unit`(92) 全绿。
- `ruff check .` 与 `scripts/lint_architecture.py` 通过。

---

## 二、M3：日志框架统一（ Observability correctness，范围收窄）

### 2.1 目标
以 `agent_core.logging` 为**配置入口**，消除三类真实缺陷：
1. **重复日志**：`agent_core.logging` 给 `agent_core` logger 加 handler 却未 `propagate=False`，宿主 `basicConfig` 又给 root 加 handler → 每条 agent_core 日志打印两次。
2. **日志静默丢弃**：`agent_core.logging` 仅配置 `agent_core` 子树；`agent_runtime.*` 无 handler 且继承 WARNING → 非 agent_server 宿主下 agent-runtime 的 INFO/DEBUG 被吞。
3. **配置所有权不清**：多个宿主各自 `basicConfig`，进程级 root 行为不可预期。

**真实语义（评审定稿）**：本方案是 **「统一配置入口 + root 默认出口，尊重已有宿主 root handler」**，而非「完全统一/接管 root」。
- `configure_logging()` **仅当 root 尚无 handler 时**挂默认 stderr handler；若宿主（Gunicorn/Uvicorn/测试 runner/企业框架）已配置 root，则**尊重宿主 handler**，不覆盖其 formatter/level。
- 因此 `agent_server` / `agent_federation` 之所以能建立自己的 root 出口，是因为它们在其它包 import **之前**主动调用了 `configure_logging()`；若由外部宿主先配置 root，则本调用退化为「仅保证 agent_core 子树不双打 + 设级别」，不强行控制 root 形态。

**不做**：强制所有业务模块统一 `get_logger()` API；不重写 logger name 命名空间；不接入 zhanggui loguru；不引入 `force` 重置宿主 root。

### 2.2 影响面（收窄）
- 核心：`packages/agent-core/agent_core/logging.py`（扩展 `configure_logging()` + `propagate=False` + 修正 `get_logger` 不改名）。
- 入口接入（调用 `configure_logging`）：`agent_server/main.py`、`agent_federation/api/server.py`，以及其它**真正自行配置 logging** 的入口。
- **不改**：`agent-runtime` 14 模块裸 `getLogger`、`agent_server` 子模块裸 `getLogger`、zhanggui loguru。它们经 root 正确传播后即生效，为形式统一改 19 个文件收益低、diff 大，本期不做。

### 2.3 实现策略（Phase 0 + Phase 1，Phase 2 暂缓）

**Phase 0 — 核心工具（`agent_core/logging.py`）**
- `get_logger(name)`：**永远保持 `__name__` 原样**，不做任何 namespace 重写（既不强制 `agent_core.` 前缀，也不对 `agent_runtime.x` 做转换）。`get_logger()` 只负责获取 logger，不负责命名空间改写。
- 新增 `configure_logging(level=logging.INFO, fmt=None, datefmt=None)`：
  - 进程内**严格幂等**：复用 `_CONFIG_LOCK` / `_CONFIGURED`；重复调用**不增长 handler 数量**（单测断言）。
  - 配置 **root** logger（挂 stderr handler），默认格式 `%Y-%m-%d %H:%M:%S %(levelname)s [%(name)s] %(message)s`。
  - 对 `agent_core` logger 设 `propagate=False`（消除双打），其余 logger 正常向 root 传播。
  - 支持环境变量 `LOG_LEVEL`（默认 INFO）覆盖级别；**不引入 `force` 参数**（避免删除已有 handler / 重置 root 的副作用）。
  - 第三方噪声控制：root 仅设为配置的 level；不主动把 `httpx`/`uvicorn`/`sqlalchemy` 等第三方库降级到 DEBUG，避免生产噪声爆炸（验收项）。
- 保留 `set_level()` 向后兼容。

**Phase 1 — 入口接入**
- `agent_server/main.py:34`：删除 `basicConfig`，改调 `configure_logging()`（format 与现有形态对齐，保持日志外观稳定）。
- `agent_federation/api/server.py`：lifespan 起始调 `configure_logging()`。
- 其它真正自行 `basicConfig`/`dictConfig` 的入口，统一改用 `configure_logging()`。

**Phase 2（暂缓，不在本期）**：是否将 `agent-runtime`/`agent-core` 内部裸 `getLogger` 改为 `get_logger` —— 待前两 commit 验证后再决定（很可能无需全改）。zhanggui loguru 桥接单独排期。

### 2.4 验收标准
- **无重复日志**：单测捕获 stderr，断言 agent_core 路径下同一 message 仅出现一次；且**重复调用 `configure_logging()` 后 root/agent_core handler 总数不变**（断言 handler 数量）。
- **无静默丢弃**：`configure_logging(level=INFO)` 后 `logging.getLogger("agent_runtime.admission").info(...)` 在 stderr 可见。
- **身份保留**：`get_logger("agent_runtime.admission")` 返回 logger name 仍为 `agent_runtime.admission`（不被改写）。
- **第三方噪声不爆炸**：`configure_logging()` 后 `httpx`/`uvicorn` 等默认维持 WARNING 及以上（不主动拉到 INFO/DEBUG）。
- 全量门禁：`tests/`(350) + `agent_federation/tests/unit`(92) + `kefu-service/tests`(8) + `eval/run_eval.py --fail-below 0.8`(12/12) 全绿；`ruff check .` 与 `scripts/lint_architecture.py` 通过。

---

## 三、提交策略
- **Commit 1（M5）**：`agent_runtime/db.py` + `tests/test_db_pool_close.py`。
- **Commit 2（M3 Phase 0+1）**：`agent_core/logging.py` + `agent_server/main.py` + `agent_federation/api/server.py`（其它自配置入口）。
- **Commit 3（M3 Phase 2，可选）**：待前两个 commit 验证后决定是否统一 `agent-runtime`/`agent-core` 内部 `getLogger`，大概率不必须。
- 回滚安全：M3 调用点改动为纯 import/配置替换；`configure_logging` 失败可降级为原 `basicConfig`（保留分支）。不改动 zhanggui-zhiku 日志体系，零回归风险。

---

## 四、评审定稿结论
| 项 | 结论 |
|---|---|
| M5 `_closing` + 先摘 `_pool` 再 close | ✅ 采纳 |
| M5 `init_pool` 关闭中绝不复建池 | ✅ 新增约束 |
| M5 timeout = 优雅等待上限（非强关） | ✅ 语义澄清 |
| M5 测试 A–E 五类 | ✅ 增强 |
| M5 状态机 | ❌ 不引入，保持 `_pool`/`_closing` |
| M3 消除双日志 + `propagate=False` | ✅ 采纳 |
| M3 `get_logger` 不改名 | ✅ 采纳（不作 namespace 重写） |
| M3 root 配置但限第三方噪声 | ✅ 采纳 |
| M3 删除 `force` 参数 | ✅ 采纳 |
| M3 不强制 19 模块统一 API | ✅ 采纳（Phase 2 暂缓） |
| M3 zhanggui 不动 | ✅ 采纳 |
| 分 commit | ✅ 采纳 |
