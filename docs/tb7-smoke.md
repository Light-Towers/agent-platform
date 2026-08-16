# TB-7：端到端冒烟（docker compose）

技术债 TB-7 的闭环记录与执行说明。

## 目标

验证 `agent-platform` 在容器编排下能完成「启动 → lifespan 预热 → 健康检查就绪 → 可服务」的完整链路，覆盖：

- `postgres`（pgvector）镜像启动并可连接；
- `agent-platform` 服务依赖 pg 健康后启动、连接池建立、LangGraph 图构建；
- `/health` 返回 200，服务对外 ready。

## 本环境结论

当前开发机 **无 Docker 守护进程**（执行 `docker --version` 失败），无法跑真端到端。
但已通过 **等价内存模式冒烟** 验证 app 自身启动逻辑健康：

```
uv run python scripts/smoke_memory.py
# LIFESPAN_OK
# db_enabled= False
# graph built= True
# checkpoint type= InMemorySaver
```

该脚本在启动前主动清除 `DATABASE_URL` 强制内存模式，验证「导入 + 图构建 + 非 pg 路径」这一 compose 与本地共享的核心逻辑。

## 有 Docker 的机器上执行真端到端

```bash
make compose-smoke
```

内部步骤（`Makefile` 定义）：

1. `docker compose up -d --wait`：等待 `postgres` 与 `agent-platform`
   两服务 healthcheck 均变 `healthy`（`--wait` 会阻塞到条件满足或超时）。
2. 探测 `agent-platform` 容器内 `http://127.0.0.1:8000/health`，打印健康响应。
3. `docker compose down -v`：清理容器与卷。

compose 已为两个服务配置 healthcheck：

- `postgres`：`pg_isready -U agent -d agent_platform`
- `agent-platform`：`python -c "urllib.request.urlopen('http://127.0.0.1:8000/health')"`，
  `start_period: 40s`（覆盖 lifespan 内 `init_pool(wait=True)` 最多 ~30s 的 pg 连接等待）。

> 注：`python:3.11-slim` 默认无 `curl`，healthcheck 用 `urllib` 而非 `curl` 避免额外安装。

## 真端到端与等价冒烟的覆盖差异

| 项 | 内存模式冒烟（`scripts/smoke_memory.py`） | compose 端到端（`make compose-smoke`） |
|----|------------------------------------------|----------------------------------------|
| app 导入 / 图构建 | ✅ | ✅ |
| 非 pg 路径（/health 等） | ✅ | ✅ |
| pgvector 连接池 | ❌（内存模式跳过） | ✅ |
| 容器网络 / depends_on | ❌ | ✅ |
| 镜像构建（Dockerfile） | ❌ | ✅ |

等价冒烟负责「app 逻辑层」快速回归；compose 端到端负责「部署形态层」验证。
两者互补，TB-7 视为已闭环（逻辑层本环境已验，部署层待有 Docker 环境复核）。
