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

**问题**：配置散落 + `<internal-ip>` 硬入库。

**改动**：
- `exhibition-agent/skill_loader/app.py:34`：`<internal-ip>` → `127.0.0.1`
- agent_federation：`api/server.py` 中的 `API_KEY`/`KNOWLEDGE_SERVICE_URL`/`ALLOWED_ORIGINS` 等保留 `os.getenv` 但统一加注释指向 `agent/config.py`

> **2026-10-15 对码复核（回应 tech-debt-cleanup 三方审核 W2「plan 自称 ✅ 但未落地：241 仍在 exhibition README、sandbox.py:10 新写 126:2375」）**：W2 这条**基本是误读**——逐处核实后，#4 的**代码修复确已落地**，W2 点名的两处 241/126 都是**有意保留的文档**而非未清理的硬编码默认值：
> - `skill_loader/app.py:36-38` 的实际默认已是 `http://127.0.0.1:8000`（`WAREHOUSE_BASE_URL` → `EXHIBITION_API_BASE_URL` → localhost 兜底），241 早已不是默认值 ⇒ #4 的核心修复（去硬编码内网 IP 默认）**已完成**。
> - `README.md:98-109`「接真实 warehouse（<internal-ip>:8000）」是**教人如何连真实 warehouse 的文档**（mock 默认另列），且其环境变量名 `EXHIBITION_AGENT_WAREHOUSE_BASE_URL` **是对的**——`config.py:11` 用 pydantic `env_prefix="EXHIBITION_AGENT_"`，字段 `warehouse_base_url` 由前缀拼出该名（`server.py:163` 读 `settings.warehouse_base_url`）；字面 `git grep` 搜不到该串正因它是拼出来的，不是漏接。**不要据此去「修」README**。
> - `sandbox.py:10` 的 `tcp://<internal-ip>:2375` 是 `docker_host` 参数的**文档示例**（非默认值），且 `CHANGELOG.md:341` 明确把它当 Docker 端点旁证引用 ⇒ 有意保留。
> - **唯一真实残留（本批已修）**：`skill_loader/app.py:6` 的 docstring 仍写「默认 http://<internal-ip>:8000」，与 :36-38 的实际默认（127.0.0.1:8000）矛盾——已订正为实际默认并补上 `EXHIBITION_API_BASE_URL` 回退说明（docstring-only，ruff + AST 校验通过）。
> ⇒ 结论：#4 保持 `[x]`；W2 的「未落地」定性不成立（把有意文档误当未清理硬编码）。真正的账只是那条滞后 docstring，已闭环。

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
