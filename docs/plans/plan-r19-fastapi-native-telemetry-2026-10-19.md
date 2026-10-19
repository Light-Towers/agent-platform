# R19 落地：FastAPI 原生 telemetry 双埋点 remediation

- 日期：2026-10-19
- 来源：`docs/TODO.md` §0.2 C 组第 4 条 / §6 清单第 4 项 / GitHub issue #23
- 类型：观测行为 remediation（防回归，非新功能）

## 1. 问题

FastAPI ≥ 0.142 引入**原生 telemetry 且默认开启**：框架自行 `trace.set_tracer_provider()` 并为每个请求建 SERVER span。本仓 kernel 已有 `TracingMiddleware`（`agent_core/tracing_middleware.py:38`，span 名 `"<METHOD> <path>"`、kind=SERVER）⇒ 同一请求出现**两个同名 SERVER span（互为兄弟）**，且框架的 `set_tracer_provider()` 会**覆盖 kernel `init_tracing` 装配的 provider**（观测状态机被框架旁路，属"第二状态机"反模式在框架层重现）。

当前锁 `fastapi==0.141.1`（无原生 telemetry）⇒ **本项是前置防护**：在 dependabot 把 fastapi 抬过 0.142 之前把门禁立住。

## 2. 动工前置取证（2026-10-19，命令与计数可复跑）

| 取证项 | 结果 |
|---|---|
| `FastAPI(` 全仓 `*.py` | 9 处：生产构造点唯一 `packages/agent-core/agent_core/guardrails/app_factory.py:44`（经 `**fastapi_kwargs` 透传）；`scripts/opencode_gateway.py:65`（P2 门禁盲区——只扫 `applications/`）；`mock_server/warehouse_mock.py:52`（P2 白名单，dev fixture）；6 处 tests |
| `FastAPIInstrumentor` / `opentelemetry.instrumentation` | **0 命中**（`*.py`）⇒ 无框架 instrumentation 自配路径 |
| `set_tracer_provider` | kernel 唯一入口 `agent_core/tracing.py:478`（仅自建分支）；其余命中均在 tests |
| `telemetry\s*=`（`*.py`） | 0 命中（仅 docs 8 处）⇒ 无既有 telemetry 配置 |
| `build_api_app` 调用方 | 7 处（ks/nl2sql/exhibition×2/agent_server/kefu/federation），仅 agent_server `enable_tracing=True` |

**结论：框架无其它自配 provider 残留路径 ⇒ 最小改动可落地。**

## 3. 改动清单（一项一 commit）

1. **`app_factory.py`**：`FastAPI(**fastapi_kwargs)` 前加 `fastapi_kwargs.setdefault("telemetry", {"tracing": False})`。用 `setdefault` 而非硬编码——调用方（测试）仍可显式开启，工厂只负责**默认关**。
2. **`scripts/opencode_gateway.py`**：`FastAPI(title="opencode-gateway")` → `FastAPI(title="opencode-gateway", telemetry={"tracing": False})`（本地 LLM 网关，无观测消费者；且它是 P2 门禁盲区，新门禁作用域扩到 `scripts/` 后必须合规）。
3. **`lint_architecture.py` 新增 `check_fastapi_telemetry()`**（AST 级，非行级正则——防未来多行调用漏判）：
   - 作用域：`applications/` + `packages/` + `scripts/` 的非测试 `.py`；
   - 判定：`ast.Call` 且 `func` 解析为 `FastAPI` 的实例化，若 keyword `telemetry` 缺失 ⇒ 违规；
   - 白名单：`mock_server/warehouse_mock.py`（dev fixture，与 P2 门禁同口径）；
   - 接入 `scripts/lint_architecture.py` 的 violations 汇总与 rc。
4. **测试**：
   - `packages/agent-core/tests/`：spy 测试（patch `fastapi.FastAPI` 记录 kwargs，断言 `telemetry == {"tracing": False}`）+ 真实构造冒烟（installed fastapi 上不 TypeError）；
   - `tests/governance/`：门禁回归（仿 `test_observability_assembly_gate.py` 模板）——① 仓内现状 0 违规；② **剥掉防线必红**：把 `app_factory.py` 的 telemetry 行删掉 ⇒ 门禁红；③ 在 `applications/` 下探针文件写裸 `FastAPI()` ⇒ 门禁红并指名文件；④ 白名单文件不判。
5. **`docs/TODO.md`**：§0.2 第 4 行 / §6 第 4 项销项（集群端到端复验随网络通道解阻后补，登记不粉饰）。

## 4. 为什么不直接用原生 telemetry 替代 kernel middleware

TODO 定型的就是"关原生 + 保 kernel"最小改动。补充两条实测支撑：
- 框架 `set_tracer_provider()` 会覆盖 kernel provider ⇒ 不关 = kernel 观测状态机被旁路（比双 span 更严重）；
- 当前 0.141.1 上除 agent_server 外**没有任何 app 有 server span**，关原生 = 逐位保持现状 span 拓扑；"其它 app 是否该有 server span"属观测方案按 app 逐个开启的既有决策序列（`app_factory` docstring 已写明），不搭车本项改。

## 5. 验收判据

- `uv run pytest packages/agent-core/tests tests/governance -q` 全绿（含新门禁四条自证）；
- `uv run python scripts/lint_architecture.py` rc=0；
- 探针反证：临时删 `app_factory.py` telemetry 行 ⇒ rc≠0 且指名；还原后 rc=0；
- ruff rc=0、`scripts/check_doc_sync.py` rc=0。

## 6. 回滚

单 commit 完成代码 + 门禁 + 测试，`git revert` 整体回退；无中间态（门禁与防护同生同死）。
