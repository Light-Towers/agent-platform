# TB-7：端到端冒烟（docker compose）

技术债 TB-7 的闭环记录与执行说明。

## 目标

验证 `agent-platform` 在容器编排下能完成「启动 → lifespan 预热 → 健康检查就绪 → 可服务」的完整链路，覆盖：

- `postgres`（pgvector）镜像启动并可连接；
- `agent-platform` 服务依赖 pg 健康后启动、连接池建立、LangGraph 图构建；
- `/health` 返回 200，服务对外 ready。

## 结论：已真端到端闭环 ✅

当前开发机 **有 Docker 守护进程**（`Docker 27.5.1` / `Compose v2.33.0`），已完整跑通真端到端冒烟：

```bash
HOST_PORT=18000 make compose-smoke   # EXIT_CODE=0
```

输出要点：

```
Container agent-platform-postgres-1  Healthy
Container agent-platform-agent-platform-1  Healthy
== agent-platform /health ==
{"status":"healthy","version":"0.1.0","storage":"postgres","llm":false,...,"coordination":true,"revert":true}
```

`storage=postgres` 证明走的是 pgvector 完整链路（非内存模式）。

> 说明：默认宿主端口 8000 可能被同机其他服务（如 `zhanggui-zhiku-web`）占用，
> 此时用 `HOST_PORT=18000 make compose-smoke` 临时切换；探测走容器内 `127.0.0.1:8000`，
> 与宿主端口无关，不影响冒烟语义。

## 真端到端暴露并修复的 3 个真实缺陷

此前文档曾误判为「环境阻塞（无 Docker）」，实际是环境具备但部署链路存在多处真实缺陷。
逐层修复如下：

### 1. Dockerfile 无法解析 workspace 本地依赖

- **现象**：`pip install --no-cache-dir .` 报 `No matching distribution found for agent-core`。
- **根因**：`agent-core` / `shared-schemas` 是 `[tool.uv.sources] workspace=true` 声明的本地依赖，
  仅 uv 能解析；普通 pip 把它们当 PyPI 包去下载。
- **修复**：`RUN pip install --no-cache-dir ./agent-core ./shared-schemas .`，同一安装事务内
  传入两个本地路径。另补 `.dockerignore` 裁剪构建上下文。

### 2. pgvector 用同步 register 适配异步连接池

- **现象**：`psycopg.pool: 'coroutine' object has no attribute 'register'`，连接池初始化超时。
- **根因**：`db.py` 导入同步版 `register_vector`，但 `AsyncConnectionPool` 的连接是 `AsyncConnection`，
  `TypeInfo.fetch` 返回未 await 的 coroutine。
- **修复**：改用 `register_vector_async`。

### 3. pgvector 扩展启用顺序 + checkpoint saver API 变化

- **现象**：先报 `vector type not found in the database`，后报
  `'_AsyncGeneratorContextManager' object has no attribute 'setup'`。
- **根因**：
  - `register_vector_async` 在连接建立时即 fetch `vector` 类型，但 `CREATE EXTENSION` 原在
    `pool.open()` 之后才执行 → 顺序颠倒；
  - `AsyncPostgresSaver.from_conn_string()` 新版本返回 async context manager，旧用法
    `saver = from_conn_string(...); await saver.setup()` 失效。
- **修复**：
  - 新增 `ensure_extensions()`，在 `pool.open()` 前用一次性连接先执行 `CREATE EXTENSION IF NOT EXISTS vector`；
  - `_build_checkpointer()` 改为 `AsyncPostgresSaver(get_pool())`，复用 `init_pool` 已建立的
    连接池（构造函数直接接受 `AsyncConnectionPool`），生命周期归 `close_pool()` 统一管理。

## 无 Docker 环境下的等价冒烟（保留，快速回归）

`scripts/smoke_memory.py` 清除 `DATABASE_URL` 强制内存模式，验证「导入 + 图构建 + 非 pg 路径」：

```
uv run python scripts/smoke_memory.py
# LIFESPAN_OK / db_enabled=False / graph built=True / checkpoint type=InMemorySaver
```

## 真端到端与等价冒烟的覆盖差异

| 项 | 内存模式冒烟（`scripts/smoke_memory.py`） | compose 端到端（`make compose-smoke`） |
|----|------------------------------------------|----------------------------------------|
| app 导入 / 图构建 | ✅ | ✅ |
| 非 pg 路径（/health 等） | ✅ | ✅ |
| pgvector 连接池 | ❌（内存模式跳过） | ✅ |
| 容器网络 / depends_on | ❌ | ✅ |
| 镜像构建（Dockerfile） | ❌ | ✅ |

等价冒烟负责「app 逻辑层」快速回归；compose 端到端负责「部署形态层」验证。两者互补。

## 执行步骤（`make compose-smoke`，含 `--build`）

1. `docker compose up -d --build --wait`：重建镜像（验证最新代码）并等待两服务 healthcheck 均 `healthy`。
2. 探测容器内 `http://127.0.0.1:8000/health`，打印健康响应。
3. `docker compose down -v`：清理容器与卷。

compose healthcheck：

- `postgres`：`pg_isready -U agent -d agent_platform`
- `agent-platform`：`python -c "urllib.request.urlopen('http://127.0.0.1:8000/health')"`，
  `start_period: 40s`（覆盖 lifespan 内 `init_pool(wait=True)` 最多 ~30s 的 pg 连接等待）。

> 注：`python:3.11-slim` 默认无 `curl`，healthcheck 用 `urllib` 而非 `curl` 避免额外安装。
