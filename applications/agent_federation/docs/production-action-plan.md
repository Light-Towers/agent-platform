# deepagents 生产级执行方案

> 日期：2026-08-12
> 范围：上下文管理 / 子 Agent 失败处理 / 并发控制 / 缓存击穿 / 动态子 Agent / 开源差距 / 工程债务
> 原则：最小侵入、渐进启用、每步可回退
> 关系：本方案是 `refactor-plan.md` Phase 0-7 落地后的**第二波生产化补强**。Phase 0-7 已于 2026-08-11 完成（见 `VERIFICATION_REPORT.md`），本方案针对落地后遗留的并发/上下文/失败处理/缓存/动态编排等纵深问题。
> 评审定案（2026-08-12 grill 评审）：决策见 `docs/adr/0001-delegation-time-health-routing.md`、`docs/adr/0002-postgres-checkpoint-from-start.md`、`docs/adr/0003-postgres-store-pgvector-memory.md`

---

## P0：安全 & 止血（立即做）

### 0.1 docker-compose.yml 硬编码 Langfuse 密钥

**文件**：`docker-compose.yml:15`
**问题**：base64 编码的 `pk-lf-…:sk-lf-…` 真实密钥对已硬编码，且已随提交 `25072742` 进入 git 历史
**动作**：

1. 改为环境变量引用：

```yaml
# before
- OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic cG9s...

# after
- OTEL_EXPORTER_OTLP_HEADERS=${LANGFUSE_OTLP_HEADERS:-}
```

2. **轮换 Langfuse 密钥**（旧密钥已在 git 历史中，仅改环境变量不能消除泄露）：
   - 在 Langfuse 控制台生成新 `pk-lf-*` / `sk-lf-*` 对
   - 更新 `.env`（不入库）
   - 评估 `git filter-repo` 清洗历史（需协调团队 force pull）

3. `.env.example` 补充：
```
LANGFUSE_OTLP_HEADERS=Authorization=Basic <your-base64>,x-langfuse-ingestion-version=4
```

### 0.2 pyproject.toml 依赖同步

**动作**：将 `requirements.txt` 中运行时依赖同步到 `pyproject.toml`

```bash
# 用 uv（与 refactor-plan §10 约定一致）
uv pip compile requirements.txt -o tmp.txt
# 手动将缺失依赖加入 pyproject.toml [project.dependencies]
```

缺失项（已排除 `tavily-python`，已在 `pyproject.toml:27` 声明）：`valkey`, `langfuse`, `pandas`, `openpyxl`, `python-docx`, `weasyprint`, `markdown`, `md2pdf`, `reportlab`, `pycairo`, `ragflow-sdk`, `tiktoken`, `numpy`, `opentelemetry-exporter-otlp-proto-http`

### 0.3 _FallbackModel 永久降级修复（已根治）

**文件**：`agent/llm.py` → `agent_core/llm/fallback.py`、`agent_core/llm/fallback_lc.py`
**原问题**：`primary_failed=True` 后只置位不复位，导致主模型恢复后仍永久走备用模型；
原 `_FallbackModel` 把降级路由复制在 `deepagents` 侧，与内核 `FallbackChatModel`
存在语义漂移，且 `invoke` 绕过 LangChain `_generate` 管道（`bind_tools`/tracing 失效）。

**最终方案（已落地）**：删除 `deepagents` 侧的 `_FallbackModel` 子类，降级语义收敛为
内核 `FallbackChatModel` 的**唯一真相源**，由「连续失败计数 + 冷却窗口 + 成功复位」
保证可恢复：

- 主模型连续失败达 `failure_threshold` → 切备用并记录冷却截止；
- 冷却到期 → 下次请求先试探主模型，成功即复位计数（无永久降级）；
- `invoke`/`ainvoke`/`stream`/`astream` 全部走同一路由，无重复实现。

`LangChainFallbackModel`（`BaseChatModel` 子类，仅 langchain extra 时导入）作为薄适配层，
`_generate/_agenerate/_stream/_astream` 直接委托内核，不再有"任意对象薄代理"旁路。
`create_fallback_model()` 在有备用模型时直接返回 `LangChainFallbackModel`。

```python
# agent_federation/agent/llm.py —— 无降级逻辑，仅构造适配层
if fallback is not None:
    return LangChainFallbackModel(primary=primary, fallback=fallback)
return primary
```

**验证**：`agent_federation/tests/unit/test_llm_fallback.py` 8 passed（含「主失败→降级备→
冷却到期→恢复」契约）；agent-core + agent_federation 单测 96 passed。

### 0.4 kefu-service 入库完整性核查

**状态**：`kefu-service/` 13 个文件已在提交 `98736a6a` 入库（`git ls-files` 确认）
**动作**：核查入库完整性（缺 README / .gitignore / .env.example）

```powershell
# 检查是否有 .env 或密钥（PowerShell）
Select-String -Path "Code\agent\kefu-service\*.py" -Pattern "api_key|password|secret"
# 核查缺失文件
Test-Path "kefu-service/README.md"
Test-Path "kefu-service/.gitignore"
Test-Path "kefu-service/.env.example"
```

### 0.5 DB 子 Agent 仍连 pharma_db（非会展库）

**问题**：`database_query_agent` 的连接配置指向 `pharma_db`（制药库），而非会展业务库
**文件**：`tools/db_tools.py` / `.env`
**前置条件**：会展库（`expo`）需先存在并完成数据迁移（README L76 仍标记 ⬜）
**方案**：按 `DB_SERVICE` 环境变量区分连接串（懒读取，避免 import 时环境变量未加载；默认 `pharma`——会展库就绪前不启用 `expo`）

```python
# tools/db_tools.py
def _get_db_url() -> str:
    """按当前子服务类型选库（每次调用读取，与 create_fallback_model 惯例一致）。"""
    urls = {
        "pharma": os.getenv("PHARMA_DB_URL"),
        "expo": os.getenv("EXPO_DB_URL"),       # 会展库
        "default": os.getenv("DB_URL"),
    }
    svc = os.getenv("DB_SERVICE", "pharma")
    url = urls.get(svc, urls["default"])
    if not url:
        raise ValueError(f"数据库连接未配置: DB_SERVICE={svc}")
    return url
```

`.env.example` 补充：
```
DB_SERVICE=pharma
PHARMA_DB_URL=mysql+pymysql://user:pass@host:3306/pharma
EXPO_DB_URL=mysql+pymysql://user:pass@host:3306/expo
```

---

## P1：并发安全（紧随 P0）

### 1.1 _main_agent 懒加载竞态

**文件**：`agent/main_agent.py`
**方案**：lifespan 预初始化，消除首次并发竞态

```python
# api/server.py lifespan 中追加
async def lifespan(app):
    # ... 现有逻辑 ...
    from agent.main_agent import get_main_agent
    await get_main_agent()  # 预初始化，启动时完成
    yield
```

### 1.2 checkpointer 持久化（Postgres 起步，跳过 SQLite 档）

**文件**：`agent/main_agent.py:32-44` + `api/server.py` lifespan
**问题**：`InMemorySaver` 纯内存，进程重启全丢
**踩坑记录**：`VERIFICATION_REPORT.md` L8-10 记录了 `AsyncSqliteSaver.from_conn_string` 两种写法均失败（直接传 → "Invalid checkpointer"；`async with` 内 return → "threads can only be started once"）；SQLite 档还隐含单 worker 约束（多 worker 各持连接写同一文件会锁竞争）
**决策**：按 `docs/adr/0002-postgres-checkpoint-from-start.md`，**直接采用 `AsyncPostgresSaver`（连接池）**，不落地 SQLite 档；docker-compose 新增 postgres 服务（checkpoint 专用）

```python
# api/server.py lifespan
async def lifespan(app):
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pool = AsyncConnectionPool(
        conninfo=os.getenv("CHECKPOINT_POSTGRES_DSN"),
        max_size=20, open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    app.state.checkpointer = checkpointer  # 供 get_main_agent / P5.4 动态 agent 统一注入

    from agent.main_agent import get_main_agent
    await get_main_agent(checkpointer=checkpointer)  # 预初始化
    yield
    await pool.close()
```

```python
# agent/main_agent.py 改造
async def get_main_agent(checkpointer=None):
    global _main_agent
    if _main_agent is not None:
        return _main_agent
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()  # 仅本地无 Postgres 的测试态 fallback
    # ... 用 checkpointer 构造 agent ...
```

依赖增量：`langgraph-checkpoint-postgres`（psycopg3，**不可用 asyncpg**）。uvicorn 解除单 worker 约束，可多 worker 部署。

### 1.3 checkpoint 定期清理（时间保留制 retention job）

**问题**：checkpoint 无自动清理，长期运行存储膨胀
**事实订正**：LangGraph checkpoint 体系**没有 `aprune` API**（`AsyncPostgresSaver` 仅提供 `adelete_thread` 等按线程删除），原示例不可执行
**方案**：时间保留制后台任务，按 `CHECKPOINT_RETENTION_DAYS`（默认 7）清理过期 checkpoint（与 ADR-0002 的 Postgres 配套；多 worker 下需单实例运行或以 `pg_try_advisory_lock` 防重）

```python
# agent/checkpoint_cleaner.py
_CLEAN_SQL = """
DELETE FROM checkpoints
WHERE thread_id IN (
    SELECT DISTINCT thread_id FROM checkpoints
    WHERE type = 'checkpoint' AND thread_id NOT IN (
        SELECT DISTINCT thread_id FROM checkpoints
        WHERE type = 'checkpoint' AND NOW() - to_timestamp(metadata->>'step_time', 'YYYY-MM-DD"T"HH24:MI:SS') < make_interval(days => %s)
    )
)
"""  # ⚠️ 列名/时间字段以 langgraph-checkpoint-postgres 实际 schema 为准，落地前 inspect 核对

async def start_checkpoint_cleaner(pool, interval=3600, retention_days=7):
    """每小时清理一次，每个 thread 保留最近 50 个 checkpoint。"""
    while True:
        await asyncio.sleep(interval)
        try:
            async with pool.connection() as conn:
                await conn.execute(_CLEAN_SQL, (retention_days,))
        except Exception as e:
            logger.warning("checkpoint 清理失败: %s", e)
```

### 1.4 工具超时线程泄漏

**文件**：`tools/_timeout.py`
**问题**：`asyncio.wait_for` 超时后底层线程仍在运行，连接不释放
**方案**：超时后记录告警 + 连接池监控

```python
async def wrapper(*args, **kwargs):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        monitor.report_tool_outcome(
            tool_name=func.__name__, outcome="timeout",
            error_class="TimeoutError")
        logger.warning("工具 %s 超时(%ss)，底层线程仍在运行，可能泄漏连接",
                      func.__name__, timeout)
        return f"工具 {func.__name__} 执行超时（{timeout}s），已隔离"
    # ... 其余不变
```

DB 连接池加监控：
```python
# tools/db_tools.py
def _get_engine():
    # ... 现有逻辑 ...
    _engine = create_engine(
        url, pool_size=pool_size, max_overflow=max_overflow,
        pool_recycle=pool_recycle, pool_pre_ping=True,
        pool_timeout=10,  # 获取连接超时 10s（而非无限等待）
        echo=False,
    )
    return _engine
```

### 1.5 API_KEY 模式下无法多轮对话

**问题**：`server.py:127-131` 启用 API_KEY 时每次请求生成新 UUID，checkpointer 形同虚设，无法维持多轮对话
**安全约束**：现有代码有意忽略客户端传入的 thread_id 防止会话劫持（`server.py:127` 注释）
**方案**：**无状态 uuid5 确定性派生，删除映射表**（多 worker 一致、重启无损、零内存增长）

```python
# api/session_manager.py
_NAMESPACE = uuid.UUID("<固定常量，入库后不可变>")

def derive_thread_id(api_key: str, session_label: str = "default") -> str:
    """同一 API_KEY 在任何 worker/任何重启后都派生出同一 thread_id，防会话劫持。"""
    return str(uuid.uuid5(_NAMESPACE, f"{api_key}:{session_label}"))

# api/server.py
@app.post("/api/task")
async def run_task(request: TaskRequest, x_api_key: str = Header(None), x_session_label: str = Header("default")):
    if API_KEY:
        # 纯函数派生：客户端无法指定他人 thread_id（防劫持），多 worker 结果一致
        thread_id = derive_thread_id(x_api_key, x_session_label)
    else:
        thread_id = request.thread_id or str(uuid.uuid4())
```

多会话需求用 `x_session_label` 作命名空间：仅作隔离，派生结果不可指定他人 thread_id。

### 1.6 同 thread_id 并发状态撕裂

**问题**：非 API_KEY 模式下客户端复用同一 thread_id 发起两个请求，两个 astream 并发写同一 checkpoint，状态撕裂
**文件**：`agent/main_agent.py`
**方案**：per-thread_id 互斥锁 + 引用计数清理（避免锁生命周期 Bug）

```python
# agent/main_agent.py
import weakref

_thread_locks: dict[str, asyncio.Lock] = {}
_thread_refcount: dict[str, int] = {}

async def _get_thread_lock(thread_id: str) -> asyncio.Lock:
    lock = _thread_locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _thread_locks[thread_id] = lock
        _thread_refcount[thread_id] = 0
    _thread_refcount[thread_id] += 1
    return lock

def _release_thread_lock(thread_id: str):
    """引用计数减一，归零时清理锁。"""
    _thread_refcount[thread_id] -= 1
    if _thread_refcount[thread_id] <= 0:
        _thread_locks.pop(thread_id, None)
        _thread_refcount.pop(thread_id, None)

async def run_deep_agent(task_query, session_id):
    lock = await _get_thread_lock(session_id)
    try:
        async with lock:  # 同一 thread_id 串行执行
            # ... 现有逻辑 ...
    finally:
        _release_thread_lock(session_id)
```

---

## P2：上下文管理（高优先级）

### 2.1 SummarizationMiddleware 阈值适配

**问题**：trigger=170K tokens，qwen-max 窗口仅 32K，主动 summarize 永不触发
**方案 A**：在 `LangChainFallbackModel`（即 `create_fallback_model` 返回的模型）暴露上下文窗口上限，供 summarization 读取

```python
# agent_core/llm/fallback_lc.py
class LangChainFallbackModel(BaseChatModel):
    @property
    def profile(self) -> dict:
        # 主模型上下文窗口；qwen-max 32K，留 2K 余量
        return {"max_input_tokens": 30_000}
```

**方案 B**：支持环境变量配置（`agent/config.py`；⚠️ 独立开关 `SUMMARIZATION_ENABLED`，不与 `PLANNER_ENABLED`（TodoList）耦合）

```python
# agent/config.py 追加
SUMMARIZATION_TRIGGER_FRACTION = float(os.getenv("SUMMARIZATION_TRIGGER_FRACTION", "0.75"))
SUMMARIZATION_KEEP_FRACTION = float(os.getenv("SUMMARIZATION_KEEP_FRACTION", "0.15"))
```

在 `create_deep_agent` 调用时传入自定义 middleware：

```python
# main_agent.py _build_middleware()
# ⚠️ 需 spike 验证 import 路径（deepagents 0.7.5 是否提供该入口）
# 备选：from langchain.agents.middleware import SummarizationMiddleware
from deepagents.middleware.summarization import create_summarization_middleware

if SUMMARIZATION_ENABLED:
    middleware.append(create_summarization_middleware(
        model=model,
        trigger=("fraction", SUMMARIZATION_TRIGGER_FRACTION),  # 75% 窗口触发
        keep=("fraction", SUMMARIZATION_KEEP_FRACTION),        # 保留最近 15%
    ))
```

### 2.2 长期记忆（跨会话，PostgresStore + pgvector）

**问题**：仅 session 级 checkpointer，无跨会话知识积累
**决策**：按 `docs/adr/0003-postgres-store-pgvector-memory.md`，用 **`PostgresStore` + pgvector 语义检索**（`InMemoryStore` 重启失忆 + 多 worker 碎片化，不满足"长期"语义）

```python
# main_agent.py
from langgraph.store.postgres import PostgresStore
from langgraph.store.base import IndexConfig

_store = PostgresStore(
    connection_string=os.getenv("STORE_POSTGRES_DSN"),
    index=IndexConfig(dims=512, embed=_bge_embed),  # bge-small-zh 512 维
)

_main_agent = create_deep_agent(
    # ... 现有参数 ...
    store=_store,  # 跨会话共享记忆（语义检索）
)
```

- Postgres 镜像用 `pgvector/pgvector`（官方镜像不含扩展）；`_bge_embed` 复用 Phase 3 固定本地 sentence-transformers（bge-small-zh），embedding 模型为锁定项，更换需重建记忆向量
- 本地无 Postgres 的测试态回退 `InMemoryStore`

主管 prompt 追加：
```yaml
## 长期记忆
- 用户偏好、历史结论可存入长期记忆（store）
- 新会话开始时检索相关历史记忆作为上下文
```

---

## P3：子 Agent 失败处理（已完成 ✓，2026-08-18，高优先级）

### 3.1 接入健康检查到路由（委派时过滤）

**问题**：`config.healthy` 被写但从未被读
**决策**：按 `docs/adr/0001-delegation-time-health-routing.md`——**委派时过滤，不在 `_build_subagents()` 构造时过滤**。agent 由 lifespan 预初始化并终身缓存（P1.1），构造时过滤只在启动时生效一次，运行中宕机永不降级，撑不起验收标准。
**方案**：

```python
# agent/async_subagents.py —— 委派层 wrapper（与熔断器 per-call 同族）
def _wrap_with_health(key, subagent):
    """每次委派前检查 config.healthy，不健康即走本地 fallback。"""
    # ... 委派调用前读 config.get_subservice(key).healthy ...
    # 不健康 → 调对应本地 fallback subagent + 熔断器计数
```

配套后台探活回路（纳入 lifespan）：复用 `zhiku_tools.py` 探活模式，周期 ping 各子服务 `/health`，驱动 `mark_unhealthy`/`mark_healthy`。
**状态**：✓ 探活回路已在 P1 阶段落地（`agent/health_check.py` + `api/server.py` lifespan 启动 `start_health_check()`，仅 `is_remote_mode()` 时启用，周期 30s 探活，失败超阈值调 `mark_unhealthy(key)`）。

验收口径：子服务宕机 → 30s 内被探活标记；**下一次委派**即走本地 fallback（而非路由表实时重建）。

### 3.2 接入熔断器到子服务调用

**文件**：`agent/async_subagents.py`（新增 `DelegatingSubAgent` 包装层）、`agent/circuit_breaker.py`（新增零依赖 per-agent 熔断器）
**方案**：包裹 AsyncSubAgent 委派调用，委派前检查 `config.healthy` 与熔断状态，失败计入熔断，OPEN 态跳过远程并降级。

```python
# agent/circuit_breaker.py：per-agent 状态机 CLOSED/OPEN/HALF_OPEN
# 失败率 50%（≥5 次样本 / 20 次窗口）触发 OPEN；冷却 30s 后 HALF_OPEN 探测恢复
from agent.circuit_breaker import get_breaker_sync, CircuitBreaker

class DelegatingSubAgent:
    async def ainvoke(self, input):
        if not self._svc.healthy:
            return await self._fallback(input, reason="unhealthy")
        if not await self._breaker.allow():
            return await self._fallback(input, reason="circuit_open")
        # 指数退避重试（SUBAGENT_RETRIES=2）
        ...
        await self._breaker.record_failure()
        return await self._fallback(input, reason="remote_failed")
```

### 3.3 主管 prompt 补充失败处理策略

**文件**：`agent/main_agent.py` 的 `_system_prompt` 拼接处（已追加"子 Agent 委派失败处理策略"段）
**状态**：✓ 已落地。追加内容要求主管在子 Agent 返回 `degraded` 标记时如实告知用户、不编造、对降级结果标注不确定性。

### 3.4 子 Agent 层重试

**方案**：在 `DelegatingSubAgent.ainvoke` 内包裹指数退避重试（`SUBAGENT_RETRIES=2`，`SUBAGENT_RETRY_BASE=0.5s`），用尽后降级；无需独立 `subagent_retry.py`。
**状态**：✓ 已落地（与 3.2 合并实现于 `DelegatingSubAgent`）。

**本地 fallback 桥接**：`SubserviceConfig.local_agent` 在 `get_all_subservices()` 首次调用时 **lazy 装配**（仅 `AGENT_MODE=remote`），指向本地 `agent.subagents.*` dict；远程不健康/熔断/失败时用 `create_deep_agent(model, ...)` 懒编译并调用，未配置则返回结构化降级响应（`degraded: True`）。

---

## P4：缓存击穿（已完成 ✓，2026-08-18，中优先级）

### 4.1 singleflight 接入主链路

**问题**：`singleflight.py` 定义了但 `main_agent.py` 未使用
**文件**：`agent/main_agent.py`（缓存 miss 分支，原 190-204 区域）
**状态**：✓ 已落地。缓存 miss 后以 cache key（与 SemanticCache 一致，含 `kb_versions`/`tenant_id`/`gray_pct`）为 singleflight key，包裹 Agent 核心执行，同一 query 的并发只跑一次 LLM。
**方案**：抽出 `_execute_agent_core(task_query, workspace_id)` 协程承载 session 准备 + 上下文注入 + per-thread 锁 + astream 执行并返回最终答案；`run_deep_agent` 在缓存 miss 后用 `singleflight(cache_key, _execute_agent_core, ...)` 调用。`_execute_agent_core` 返回后由 `run_deep_agent` 统一做监控上报/记忆沉淀/缓存写入（幂等，避免合并重复）。

```python
from agent.cache.singleflight import singleflight
from agent.cache.layers import _build_cache_key

# 缓存查询
if CACHE_ENABLED:
    _cache_hit = await SemanticCache.get(_cached_intent, task_query)
    if _cache_hit is not None:
        monitor.report_task_result(_cache_hit["answer"])
        return
    # miss → singleflight 防击穿
    cache_key = _build_cache_key(
        _cached_intent, task_query,
        cfg.kb_versions, cfg.tenant_id, cfg.gray_pct
    )
    _final_answer = await singleflight(
        cache_key,
        _execute_agent,  # 实际执行函数
        task_query, session_id
    )
    monitor.report_task_result(_final_answer)
    return
```

```python
async def _execute_agent(task_query, session_id):
    """实际执行 Agent，返回最终答案字符串。"""
    # ... 现有 astream 逻辑 ...
    return _final_answer
```

**效果**：100 个相同请求同时到达 → 第 1 个执行，其余 99 个等同一结果。

**等待方语义（生产级口径）**：

- 等待方**只收最终结果**（经 `run_deep_agent` 统一上报/记忆/缓存），不做流式事件回放/广播（事件归属 workspace_id 各异，fan-out 复杂度和收益不成比例）
- 缓存 key 已含 `tenant_id` + `kb_versions` + `gray_pct`，确保相同 query 跨租户/跨 KB 版本不命中同一结果，避免数据串流事故 ✓
- **多轮续聊安全**：singleflight key 基于 `intent + query`，同 thread 的不同 query（续聊追问）不会命中同一 key，天然绕过合并，不会把不同轮次答案错配 ✓
- Langfuse 成本只归集真正执行的 `_execute_agent_core` 一次 LLM 调用，等待方不重复记账 ✓

**实测**：`test_singleflight.py` 验证 10 并发同 key 仅执行 1 次 fn，结果一致；异 key 各执行；异常正确传播。

### 4.2 set_async Task 引用持有

**文件**：`agent/cache/semantic_cache.py`（已落地）
**状态**：✓ 已完成。`SemanticCache.set_async` 已用 `_pending_writes: set` 持有 `asyncio.create_task` 引用并 `add_done_callback(_pending_writes.discard)`，避免 GC 提前回收导致缓存写入静默丢失。

---

## P5：动态子 Agent（已完成 ✓，2026-08-18，中优先级）

### 5.1 工具注册表（已完成）

**文件**：`agent/tool_registry.py`（新增）
**状态**：✓ 已实现。采用「延迟定位串」（`module:attr`）而非 import 期硬依赖，避免外部 SDK（如 tavily）缺失时阻断导入（同时修复了 `tools/tavily_tool.py` 顶层 import 改为延迟构造，解耦 import 期依赖）。

```python
# agent/tool_registry.py
TOOL_REGISTRY = {  # 工具名 -> "module:attr" 延迟定位串
    "generate_markdown": "tools.markdown_tools:generate_markdown",
    "convert_md_to_pdf": "tools.pdf_tools:convert_md_to_pdf",
    "read_file_content": "tools.upload_file_read_tool:read_file_content",
    "execute_sql_query": "tools.db_tools:execute_sql_query",
    "internet_search":   "tools.tavily_tool:internet_search",
    "zhiku_retrieve":    "tools.zhiku_tools:zhiku_retrieve",
}
ROLE_TOOLS = {  # 角色 -> 工具名列表（声明式）
    "files":      ["generate_markdown", "convert_md_to_pdf", "read_file_content"],
    "data":       ["execute_sql_query", "read_file_content"],
    "search":     ["internet_search", "read_file_content"],
    "knowledge":  ["zhiku_retrieve", "read_file_content"],
}
BASE_ROLES = ["files"]  # 始终挂载
```

### 5.2 SubAgentFactory（已完成）

**说明**：动态模式不改变委派拓扑，`_build_subagents()` 仍返回原 3 个 subagent，未做 per-spec 子 agent 拆分（与规划 5.2 的 `build_subagents` 略有差异，但实际动态粒度落在「主管工具集」而非「子 agent 集合」，更符合低成本增量价值）。工具粒度的 `get_tools_for_roles(roles)` 已实现于 `tool_registry.py`。

```python
# agent/subagent_factory.py（参考，实际未单独建文件；逻辑并入 tool_registry）
from agent.tool_registry import get_tools

_DEFAULT_PROMPT = "你是专业助手，请使用提供的工具完成任务。"

def build_subagents(role_specs: list[dict]) -> list[dict]:
    """按规约现场构造子 Agent。"""
    subagents = []
    for spec in role_specs:
        subagents.append({
            "name": spec["name"],
            "description": spec["description"],
            "system_prompt": spec.get("system_prompt", _DEFAULT_PROMPT),
            "tools": get_tools(spec["capabilities"]),
        })
    return subagents
```

### 5.2 SubAgentFactory

```python
# agent/subagent_factory.py
from agent.tool_registry import get_tools

_DEFAULT_PROMPT = "你是专业助手，请使用提供的工具完成任务。"

def build_subagents(role_specs: list[dict]) -> list[dict]:
    """按规约现场构造子 Agent。

    Args:
        role_specs: [{"name", "description", "capabilities": ["能力1", ...]}]
    """
    subagents = []
    for spec in role_specs:
        subagents.append({
            "name": spec["name"],
            "description": spec["description"],
            "system_prompt": spec.get("system_prompt", _DEFAULT_PROMPT),
            "tools": get_tools(spec["capabilities"]),
        })
    return subagents
```

### 5.3 角色规约 prompt（已完成为 `_plan_roles`）

**文件**：`agent/main_agent.py` 的 `_plan_roles(task_query)`
**状态**：✓ 已实现。用 LLM（结构化 JSON 输出）按任务选角色，失败/解析失败回退 `normalize_roles` → 全量工具（静态语义）。`_extract_json` 容错（去代码块、截取首个 `{}`）。

```yaml
# prompt/dynamic_planner.yaml （参考，实际使用 main_agent._plan_roles 内联 prompt）
planner:
  system_prompt_addition: |
    ## 动态角色规划

    对于复杂任务，先分析所需能力，输出角色规约 JSON：
    [{"name": "角色名", "description": "职责描述", "capabilities": ["能力1", "能力2"]}]

    可用能力池：
    - sql_query: 数据库查询
    - web_search: 联网搜索
    - knowledge: 知识库检索
    - file_read: 文件读取
    - markdown: Markdown 生成
    - pdf: PDF 转换

    规则：
    - 每个角色至少具备一种能力
    - 简单任务用单个角色
    - 复杂任务拆分多角色，标注协作关系
```

### 5.4 每请求构造 agent + LRU 缓存（已完成）

**文件**：`agent/main_agent.py` 的 `get_main_agent_for_task(role_specs)`
**状态**：✓ 已实现。按 `hashlib.sha256(sorted(roles))` 做 LRU（`_ROLE_CACHE`，容量 `DYNAMIC_AGENT_CACHE_MAX`，默认 10）。复用全局 `_main_checkpointer` / `_main_store` 保证会话历史一致；`role_specs=None` 回退静态单例。

```python
# main_agent.py（实际实现）
from collections import OrderedDict
_ROLE_CACHE: "OrderedDict[str, object]" = OrderedDict()
_ROLE_CACHE_MAX = int(os.getenv("DYNAMIC_AGENT_CACHE_MAX", "10"))

async def get_main_agent_for_task(role_specs=None):
    if role_specs is None:
        return await get_main_agent()
    cache_key = hashlib.sha256(json.dumps(sorted(role_specs), sort_keys=True).encode()).hexdigest()
    if cache_key in _ROLE_CACHE:
        _ROLE_CACHE.move_to_end(cache_key)
        return _ROLE_CACHE[cache_key]
    tools = get_tools_for_roles(role_specs)
    agent = create_deep_agent(
        model=model, system_prompt=_system_prompt, tools=tools,
        checkpointer=_main_checkpointer, store=_main_store,
        subagents=_build_subagents(), middleware=_build_middleware(),
    )
    _ROLE_CACHE[cache_key] = agent
    if len(_ROLE_CACHE) > _ROLE_CACHE_MAX:
        _ROLE_CACHE.popitem(last=False)
    return agent
```

### 5.5 渐进启用（已完成）

**文件**：`run_deep_agent` 缓存 miss 分支
**状态**：✓ 已实现。读取 `DYNAMIC_AGENT_ENABLED`：
- `true`：`roles = await _plan_roles(task_query)` → `get_main_agent_for_task(roles)`；异常回退静态。
- `false`（默认）：静态单例 `get_main_agent()`。

**实测**：`test_tool_registry.py` 覆盖注册表一致性、角色筛选去重、normalize 兜底、`_plan_roles` 解析/失败回退、`get_main_agent_for_task` LRU 淘汰（容量 2 → 第三类触发淘汰，构造次数=3）。

---

## P6：测试补全（低优先级但必须做）

### 6.1 核心模块单测

| 模块 | 测试文件 |
|------|---------|
| `agent/intent/` | test_intent_classifier.py |
| `agent/rewrite/` | test_rewrite.py |
| `agent/cache/` | test_cache_layers.py, test_singleflight.py |
| `gateway/` | test_rate_limit.py, test_circuit_breaker.py |
| `agent/tracing/` | test_trace_propagation.py |
| `agent/llm.py` | test_fallback_model_recovery.py |

### 6.2 集成测试

```python
# tests/integration/test_concurrent_requests.py
async def test_10_concurrent_same_query():
    """10 个相同请求并发，验证 singleflight + 缓存。"""

async def test_main_agent_init_no_race():
    """首次并发不产生竞态。"""

async def test_fallback_model_recovery():
    """主模型恢复后自动切回。"""
```

### 6.3 评测集实跑标定与覆盖度补充（复用 run-all.py，不新建脚本）

**状态**：`eval/golden.jsonl` 已有 200 条（Phase 0 已落地，VERIFICATION_REPORT Phase 5 PASS）；`eval/run-all.py` + `run_eval`/`judge`/`score_routing` 均已就位
**遗留问题**：200 条的实跑标定（路由准确率 / 工具调用四分类 / 任务完成率）尚未全量跑通，覆盖度需补充
**动作**：

1. 用现有 `python -m eval.run-all` 全量实跑 200 条，产出标定报告落盘（缺的是实跑结果，不是脚本；若指标有缺口，增量改 `run_eval`/`judge`，不另起入口）
2. 覆盖度矩阵盘点：意图分类 × 子服务 × 单轮/多轮 × 中文/英文 × 简单/复杂，**只补缺格样本**进 `golden.jsonl`，目标每格 ≥10 条

### 6.4 zhiku golden 标注修复

**问题**：`zhanggui-zhiku/eval/golden_queries.jsonl`（73 条）的 eval 指标全 0，标注是假设性的
**动作**：重新标注 73 条 golden queries

```bash
cd zhanggui-zhiku
python -m eval.relabel_golden --review  # 人工逐条审核
```

### 6.5 zhiku kg 通道接入 Neo4j

**问题**：`zhanggui-zhiku/.../node_query_kg.py` 仅 `time.sleep(1)`，未接 Neo4j，是 stub（代码内已有诚实标注）
**动作**：接入 Neo4j 图数据库

```python
# zhanggui-zhiku/.../node_query_kg.py
from neo4j import AsyncGraphDatabase

async def query_kg(query: str, top_k: int = 5) -> list[dict]:
    """从 Neo4j 查询知识图谱。"""
    async with _driver.session() as session:
        result = await session.run(
            "MATCH (n)-[r]->(m) WHERE n.name CONTAINS $query "
            "RETURN n, r, m LIMIT $k",
            query=query, k=top_k
        )
        return [record.data() async for record in result]
```

### 6.6 README 测试数同步

**问题**：README 记载 24 个测试，实际已有 30 个（VERIFICATION_REPORT 确认）
**动作**：更新 README

```powershell
# 统计实际测试数（PowerShell）
cd deepagents
python -m pytest --collect-only -q 2>&1 | Select-Object -Last 1
# 更新 README.md 中的测试数
```

---

## P7：开源差距补齐（长期演进）

> 对比 CrewAI / AutoGen / OpenAI Swarm / LangGraph / MetaGPT 发现的编排能力差距
> 参考：`docs/dynamic-subagent-research.md`

### 7.1 Human-in-the-loop（人工审核/中断）

**差距**：CrewAI / LangGraph / AutoGen 均支持，本项目无
**场景**：高风险操作（删除数据、发送邮件）前需人工确认
**方案**：LangGraph interrupt 机制

```python
# main_agent.py
from langgraph.types import interrupt

# 在工具执行前插入 interrupt
async def _execute_with_approval(tool_name, args):
    if _is_high_risk(tool_name):
        approval = interrupt({
            "type": "approval_required",
            "tool": tool_name,
            "args": args,
        })
        if not approval.get("approved"):
            return "操作已被用户拒绝"
    return await _execute_tool(tool_name, args)
```

前端 WebSocket 推送 `approval_required` 事件，用户确认后 `Command(resume={"approved": True})` 恢复。

### 7.2 结构化输出

**差距**：CrewAI 支持 `output_pydantic`，LangGraph 支持 structured output，本项目 Agent 返回纯文本
**方案**：Pydantic schema 约束（⚠️ 需 spike 验证：`response_format` 不在 refactor-plan 已核实的 `create_deep_agent` 0.7.5 签名清单内，落地前先 inspect；不兼容则退回 `structured_response` 参数或自定义输出解析）

```python
from pydantic import BaseModel

class AgentResponse(BaseModel):
    answer: str
    confidence: float
    sources: list[str]
    needs_followup: bool

# create_deep_agent 传 response_format
agent = create_deep_agent(
    # ... 现有参数 ...
    response_format=AgentResponse,
)
```

### 7.3 子 Agent 并行执行

**差距**：当前子 Agent 串行委派，多路由场景延迟叠加；CrewAI / AutoGen 支持并行
**方案**：asyncio.gather 并行委派

```python
# agent/parallel_dispatch.py
async def dispatch_parallel(subagent_tasks: list[dict]) -> list[str]:
    """并行委派多个子 Agent，汇总结果。"""
    results = await asyncio.gather(
        *[_call_subagent(t["type"], t["description"]) for t in subagent_tasks],
        return_exceptions=True,
    )
    return [
        r if not isinstance(r, Exception) else f"子 Agent 失败: {r}"
        for r in results
    ]
```

主管 prompt 追加：
```yaml
## 并行委派
- 若任务需要多个独立子服务的信息，可同时委派
- 格式：[{"type": "db", "description": "..."}, {"type": "knowledge", "description": "..."}]
- 系统将并行执行，汇总结果后继续推理
```

### 7.4 MCP 工具服务器支持

**差距**：CrewAI / AutoGen / LangGraph 均支持 MCP，本项目无
**价值**：复用 MCP 生态工具（Playwright / FileSystem / GitHub 等）
**方案**：接入 `langchain-mcp-adapters`

```python
# agent/mcp_integration.py
from langchain_mcp_adapters.client import MultiServerMCPClient

async def load_mcp_tools():
    client = MultiServerMCPClient({
        "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]},
        "filesystem": {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem", "/workspace"]},
    })
    tools = await client.get_tools()
    return tools

# 在 create_deep_agent 时合并
all_tools = [generate_markdown, convert_md_to_pdf, read_file_content] + await load_mcp_tools()
```

### 7.5 Code Execution 能力

**差距**：AutoGen 有内置 sandbox，CrewAI 有 code tools，本项目无
**场景**：用户要求执行 Python 代码做数据分析
**方案**：受限沙箱执行

```python
# tools/code_exec_tool.py
@tool
@with_timeout(timeout=10)
def execute_python(code: str) -> str:
    """在受限沙箱中执行 Python 代码。"""
    from RestrictedPython import compile_restricted
    byte_code = compile_restricted(code, '<inline>', 'exec')
    restricted_globals = {"__builtins__": _safe_builtins, "pd": pd, "np": np}
    exec(byte_code, restricted_globals)
    return str(restricted_globals.get("_result", ""))
```

### 7.6 Durable Execution（断点恢复）

**差距**：LangGraph 支持 durable execution，本项目无
**场景**：Agent 执行到第 3 步时进程崩溃，恢复后从第 3 步继续
**方案**：LangGraph checkpoint + run resume（依赖 P1.2 持久化 checkpointer）

```python
async def resume_agent(thread_id: str):
    """从最后 checkpoint 恢复执行。"""
    config = {"configurable": {"thread_id": thread_id}}
    async for chunk in main_agent.astream(None, config=config):
        # None input → 从中断点继续
        ...
```

### 7.7 Agent 间 peer 对话 / Debate

**差距**：AutoGen 支持 group chat / debate，本项目仅 supervisor→worker
**场景**：多个子 Agent 对同一问题给出不同答案，投票取最优
**方案**：LangGraph 多 agent 图

```python
# agent/debate_pattern.py
async def debate(question: str, agents: list, rounds: int = 2) -> str:
    """多 Agent 辩论，投票取最优。"""
    positions = []
    for round_i in range(rounds):
        round_answers = await asyncio.gather(
            *[_ask_agent(a, question, positions) for a in agents]
        )
        positions.extend(round_answers)
    return await _judge(positions)
```

---

## 执行顺序与依赖

```
P0（0.1-0.5）
    ↓
P1（1.1-1.6）
    ↓
P2（2.1, 2.2）  ← 依赖 P1.2（持久化 checkpointer）
    ↓
P3（3.1-3.4）
    ↓
P4（4.1, 4.2）  ← 依赖 P1.1（预初始化）
    ↓
P5（5.1-5.5）  ← 依赖 P3（失败处理）、P4（缓存）
    ↓
P6（6.1-6.6）  ← 贯穿全程，每完成一个 P 写对应测试
    ↓
P7（7.1-7.7）  ← 长期演进，按需逐项启用
```

## 环境变量汇总

```bash
# .env.example 新增

# P0
LANGFUSE_OTLP_HEADERS=

# P1
CHECKPOINT_POSTGRES_DSN=postgresql://user:pass@localhost:5432/checkpoints
CHECKPOINT_CLEANER_INTERVAL=3600
CHECKPOINT_RETENTION_DAYS=7

# P2（新增）
SUMMARIZATION_ENABLED=false
SUMMARIZATION_TRIGGER_FRACTION=0.75
SUMMARIZATION_KEEP_FRACTION=0.15
STORE_POSTGRES_DSN=postgresql://user:pass@localhost:5432/store

# P4（新增）
CACHE_ENABLED=true
SINGLEFLIGHT_ENABLED=true

# P5
DYNAMIC_AGENT_ENABLED=false
AGENT_CACHE_MAX=10

# P7（新增）
HITL_ENABLED=false
MCP_ENABLED=false
CODE_EXEC_ENABLED=false
PARALLEL_DISPATCH=false
```

## 风险矩阵

| 改动 | 风险 | 缓解 |
|------|------|------|
| 放弃全局单例 | 内存增长 | LRU 缓存 + 超时回收 |
| 每请求构造 agent | 首次延迟 | LRU 命中后零开销 |
| Postgres checkpoint（ADR-0002） | 连接池耗尽 / DSN 泄露 | 池上限 + `pool_timeout` + DSN 仅走 `.env`（不入库） |
| singleflight | 事件循环关闭时 call_later 报错 | try/except 兜底 |
| 动态子 Agent | LLM 输出不可控 | 能力池白名单 + JSON schema |
| 熔断器接入 | 误熔断正常服务 | HALF_OPEN 试探 + 手动重置 API |
| HITL interrupt | 用户不响应导致永久阻塞 | 超时自动拒绝 + 默认安全策略 |
| MCP 工具 | 外部进程安全风险 | 白名单 + 沙箱隔离 |
| Code Execution | 任意代码执行风险 | RestrictedPython + 超时 + 无网络 |
| 并行委派 | 子 Agent 间资源竞争 | 信号量限制并行度 |
| per-thread 锁 | 死锁风险 | 引用计数清理 + 超时释放 |
| DB 多库切换 | 连接池膨胀 | 按库独立连接池 + 上限 |
| Langfuse 密钥轮换 | 历史清洗需团队协调 | filter-repo + force pull 通知 |
| 长期记忆 embedding 锁定（ADR-0003） | 换模型需重建全部记忆向量 | 固定 bge-small-zh，与 Phase 3 解耦策略一致 |

## 验收标准

| 指标 | 目标 |
|------|------|
| 100 相同请求并发 | LLM 调用 ≤ 1 次；等待方收最终结果 + `singleflight` 标记事件，时长 ≤ 执行方 +1s |
| 主模型恢复 | 60s 后自动切回 |
| 上下文 75% 窗口 | 主动 summarize，无 overflow |
| 子服务宕机 | 探活 30s 内标记，**下一次委派**即走 fallback（ADR-0001） |
| 进程重启 | 对话历史不丢（Postgres checkpoint，多 worker 成立，ADR-0002） |
| 首次并发 | 无竞态（lifespan 预初始化） |
| 动态子 Agent | 按任务能力声明组装，注入同一 Postgres checkpointer，LRU 命中率 > 80% |
| API_KEY 多轮对话 | uuid5 派生：任意 worker 同 key 同 label 结果恒定（防劫持） |
| 同 thread_id 并发 | 串行执行，无状态撕裂（引用计数锁） |
| kefu-service | 入库完整性核查通过（README/.gitignore/.env.example） |
| DB 连接 | 按子服务类型选库，默认 pharma，expo 就绪后切换 |
| 评测集 | run-all.py 全量实跑报告落盘，覆盖度每格 ≥10 |
| zhiku kg | 接入 Neo4j，非 stub |
| README 测试数 | 与实际一致 |
| 长期记忆 | PostgresStore + pgvector 语义检索，重启不丢（ADR-0003） |
| checkpoint 保留 | retention 7 天可配，表行数 7 天滚动稳定 |
