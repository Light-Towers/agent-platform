# Plan：工程结构债务收口（5 项）

> 状态：2026-09-22 制定并实施
> 前置：10 维度排查发现 2 高 + 3 中优先级债务。

## #1 agent_federation 主路径接入 shared_schemas 契约（高）

**问题**：`api/server.py` 用自定义 `TaskRequest(BaseModel)` + 裸 dict 返回。

**改动**：
- `TaskRequest` → `shared_schemas.QueryRequest`（`thread_id` 映射为 `session_id`）
- `/api/task` 响应类型化为 `TaskAcceptedResponse(BaseModel)`
- 导入 `shared_schemas.QueryRequest`

**影响面**：`api/server.py` 单文件，不改外部 API 行为（字段名 `query` 不变，`thread_id` → `session_id`）。

## #2 exhibition-agent / zhanggui-zhiku 接入联邦契约（高）

**问题**：两个应用完全游离于 `shared_schemas`。

**改动**：
- zhanggui-zhiku：`QueryRequest` 继承 `shared_schemas.QueryRequest`（加 `is_stream`/`history` 扩展字段）；health 端点用 `shared_schemas.HealthResponse`
- exhibition-agent：health 端点用 `shared_schemas.HealthResponse`；内网 IP 默认值改 `127.0.0.1`

**注意**：exhibition-agent 的 `/api/chat` 是 chat 接口（messages 列表），不强制改为 QueryRequest。

## #3 CircuitBreaker 双适配层收敛（中）

**问题**：agent_runtime 和 agent_federation 各有一套 async CircuitBreaker 适配。

**改动**：
- `agent_runtime/circuit_breaker.py`：增加 `policy` 可选参数（支持 `SlidingWindowPolicy`）+ `on_state_change` 回调
- `agent_federation/agent/circuit_breaker.py`：改为复用 `agent_runtime.circuit_breaker.CircuitBreaker`，注入 `on_state_change=record_circuit_state`
- per-name 注册表保留在 agent_federation（应用级关注点）

## #4 agent_federation 配置中心 + 内网IP清理（中）

**问题**：配置散落 + `192.168.100.241` 硬入库。

**改动**：
- `exhibition-agent/skill_loader/app.py:34`：`192.168.100.241` → `127.0.0.1`
- agent_federation：`api/server.py` 中的 `API_KEY`/`ZHIKU_API_URL`/`ALLOWED_ORIGINS` 等保留 `os.getenv` 但统一加注释指向 `agent/config.py`

## #5 硬编码 timeout 提取为配置项（中）

**问题**：23 处散落的 `timeout=15/30/60`。

**改动**：agent_federation `agent/config.py` 增加 `TIMEOUT_*` 常量，替换 `tools/` 下硬编码。其他应用保留（机械改动，优先级低）。

## 验收标准

- [x] #1 agent_federation 用 shared_schemas.QueryRequest
- [x] #2 zhanggui-zhiku QueryRequest 继承 shared_schemas；exhibition-agent health 用 HealthResponse
- [x] #3 agent_federation CB 复用 agent_runtime CB
- [x] #4 内网 IP 清理
- [x] #5 agent_federation timeout 提取
- [x] 全量测试不回归
- [x] ruff 0 error
