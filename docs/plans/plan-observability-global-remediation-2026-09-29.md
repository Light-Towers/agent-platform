# 观测链路全局治理方案（复盘驱动，2026-09-29）

> 状态：**方案（待确认，未动产品码）**。触发源：2026-09-29「观测链路补证（OTel/Jaeger + 真实 LLM + 端到端取证）」演练。
> 原则（AGENTS.md 横切关注点全局优先）：三层齐备——单一实现（kernel）/ 全局装配（构造保证不可漏接）/ 强制门禁（lint 入 CI）。缺一层须说明理由。
> 纪律：本方案不放宽断言、不删用例、不用注释掩盖根因；凭据只进 Secret/.env。

## 0. 一页结论

本轮 Jaeger 出 trace 前踩中的 2 个 bug（otel.py 符号、span 生命周期误用）不是孤立缺陷，而是同一结构性问题的三个投影：**观测能力存在双套并行实现、靠调用点自觉接线、真实路径从未进过 CI**。全仓扫描共登记 17 个问题（R1-R17），其中 **4 个属"修复前从未真正生效"的长期潜伏缺陷**（R4 OTel 初始化、R6 traceparent 透传、R1 agent_server 侧 Langfuse、R7 NoOp 掩盖），3 个属**本轮局部修复后仍然存在的残留缺口**（R6 未修、R8 knowledge-service 同款误用未修、R10 旁路丢 span 未修）。

## 1. 问题清单表

| # | 现象 | 根因与证据 | 影响面 | 分类 | 潜伏/本轮暴露 |
|---|------|-----------|--------|------|--------------|
| R1 | agent_server 配置 Langfuse key 也永远无效 | `agent_runtime/tracing.py:17` 用 v2-only `langfuse.callback`；agent_server 栈 `langgraph>=1.2.10`（langchain-core 1.x）与 v2 不可共存（本轮 pip 无限回溯实测）；而 federation `pyproject:52` 声明 `langfuse>=4.0.0` 用 v3+ `get_client/observe`（`langfuse_adapter.py:51,93`）、exhibition `llm_obs.py:104` 又用 v2 路径——**共享包内一个 API 代际三种口径** | agent_server（永久无效）、exhibition（同上）、agent-runtime 共享包契约 | 依赖契约 | 长期潜伏 |
| R2 | OTel 依赖声明三处不一致 | 根 `pyproject:33-36` `otel=[sdk>=1.20,exporter>=1.20]`（下界过宽无上限）；agent-core `tracing=[api>=1.24,sdk>=1.24]`；**实际 import OTel 符号最多的 agent-runtime 自身零声明**（其 pyproject 仅 ruff 豁免）| 任何安装组合（uv / pip / 各 app requirements.txt 双源）版本解析结果不同 | 依赖契约 | 长期潜伏 |
| R3 | CI 从未执行真 SDK 路径 | `Makefile:7` `uv sync --all-packages --extra dev`（不装 otel extra）；`packages/agent-runtime/tests/test_otel.py:34` 注释自证"本机无 SDK 的默认路径"；`tests/api/test_query_lifecycle.py:91` 只设 `otel_tracer=None` | R4/R6/R7/R8 全部因此不可见；未来任何"仅真 SDK 才走到"的分支同盲 | 架构缺陷（测试基座） | 长期潜伏 |
| R4 | `TraceIdRatioBasedSampler` 不存在 → OTel 静默 NoOp，OTel opt-in 历史上从未生效 | `otel.py` 旧 L26 import 符号在 opentelemetry-sdk 全版本不存在（pod 内逐条 import 实测：`TraceIdRatioBasedSampler` ImportError / `TraceIdRatioBased` OK）；被 `try/except ImportError` guard 吞成 `_OTEL_AVAILABLE=False`，且 L48 文案 "SDK not installed" 与真因矛盾 | 所有经 `agent_runtime.otel` 的 trace（本轮修复，本地+126 双侧）；曾计划用它的任何应用 | 产品码缺陷 | 长期潜伏（本轮触发） |
| R5 | 失败路径只 warn 不 fail 且文案失真 | `otel.py:48`（"not installed"实际可能已装但 import 失败）；`otel.py:104-106`（宽 Exception→NoOp，BLE001 已在 pyproject 豁免）；`agent_core/tracing.py:370`（init 失败降级 no-op）；`agent_runtime/tracing.py:25-27`（Langfuse 失败 warn 空列表）| 四个观测入口同模式：**"显式关闭"与"启用但坏了"不可区分**，运维无信号 | 产品码缺陷×架构缺陷 | 长期潜伏 |
| R6 | **traceparent 跨服务透传在 agent_server 实际断裂（本轮未发现，复盘新证）** | `agent_core/tracing_propagation.py:40,64,115` 的 inject/extract 以 `agent_core.tracing.is_tracing_enabled()` 为门（读 `_enabled`）；但 agent_server 只调 `agent_runtime.otel.init_otel()`（另一状态机 `_OTEL_AVAILABLE/_tracer`），从不调 `init_tracing` → `_enabled` 恒 False → **extract 恒 None、inject 恒 no-op**。联邦→子服务链路 context 静默丢失；本轮 commit cca9223 中"保留 W3C 父链接"的表述在 agent_server 实际不成立 | agent_server 全部入站/出站传播；knowledge-service/federation 若依赖 inject 同样失效 | 架构缺陷（双状态机） | 长期潜伏（复盘新发现） |
| R7 | NoOp shim 的 `__getattr__` 兼容 hack 掩盖 app 层误用 | `agent_core/tracing.py:136-140` 注释点名 "agent_server/api/routes.py:196-198" 的手动 CM 用法，在内核层转发兜底 → NoOp 态一切正常、真 SDK 态才崩（R3 因此 CI 全绿）| 内核替身语义不再"与真实现同形"，测试替身给出假安心 | 架构缺陷（替身失真） | 长期潜伏 |
| R8 | span/CM 手动生命周期误用（散点） | ① agent_server `query_router.py` 旧 L218-221/330-333（本轮已修：改 `start_span(context=)+finally end()`）；② 126 旧版 `routes.py:196-198` 对 CM 对象直接 `set_attribute`（`/query` 500 直接触发点，已在部署侧等价修）；③ **knowledge-service `query_router.py:195-196,237,260,283,314` 同款 `use_context(...).__enter__()/__exit__()` 未修**——attach/detach 跨 handler/background_task 边界，traceparent 上下文进不了后台图执行 | 每个"记得手写"的调用点都可能再犯；ks 的 /query 流式与 /retrieve 已在错误模式下运行（真 SDK 装进 ks 即复现 500 类问题） | 产品码缺陷（多点复发） | ①②本轮暴露；③长期潜伏未修 |
| R9 | tracer "关闭"语义两套：`None` vs NoOp 对象 | `main.py:242` else 分支置 `app.state.otel_tracer=None`；`otel.py:111-112` 未初始化返回 noop；router `if otel_tracer is not None` 时**跳过属性设置**（None 态连脱敏属性都不写）| 同一开关关/坏产生不同行为，下游断言/排障口径不一 | 架构缺陷 | 长期潜伏 |
| R10 | 旁路路径丢 span（覆盖缺口清点） | agent_server `/query`：admission REJECTED `raise 429/503`（L107-111，span 前）、coordinator reject `raise 409`（L135-140）、**cache_hit 提前 return**（L152-166）、排队等待段不在 span 内（L176-209 在 span 创建后之前完成等待才建 span）；`session_router/health_router/callback/control/import_router/sql_router` 零 span；单 `query` span 无子 span（plan/execute/LLM/检索未埋点）| 限流/拒绝/挂起/缓存命中在生产 trace 里"不可见"，恰是排障最需要的路径 | 架构缺陷（覆盖设计缺失） | 长期潜伏 |
| R11 | `/health` 报配置意图而非初始化结果 | `health_router.py:30` `otel=settings.otel_effective_enabled`（=enabled&&exporter!=none）；与 `otel.py` 实际 `_OTEL_AVAILABLE`/init 结果无关 → R4 期间长期显示 otel=true | 运维面板/冒烟判据失真 | 产品码缺陷 | 长期潜伏 |
| R12 | 横切关注点接线散落（service-locator） | `query_router.py` 一个 handler 内 14 处 `getattr(request.app.state, ...)`；OTel 接线三 app 三样：agent_server=`init_otel`（main.py:233）、federation=`init_tracing`+langfuse_adapter（server.py:60-63）、ks=`init_tracing`+手写 `__enter__`（main.py:86）；`build_api_app`（app_factory.py:23）只管错误 handler，不管观测 | 可观测/request_id/鉴权/限流/审计同类关注点都靠"调用点记得接一次"——AGENTS.md 判定的"接线散落反模式" | 架构缺陷 | 长期潜伏 |
| R13 | lint 门禁无观测类不变量 | `lint_architecture.py` 现有 5 条（P4-2/P2/P5/批3/C1）证明"choke-point+全仓 lint"路径成熟可行，但对 `__enter__` 手动滥用、`app.state.otel_tracer` 散点取用、观测 extras 版本区间漂移**零拦截** | R8/R12 类问题未来仍会新增 | 架构缺陷（门禁缺失） | 长期潜伏 |
| R14 | 构建源与验证对象版本漂移 | 126 `/opt/agent-platform`@`031c89a`（routes.py 426 行）vs 本地 HEAD（routes.py 24 行拆分后）；本地 grep 定位与镜像内 traceback 行号错位两天；任务前提亦与部署不符（应用=agent_server 非 federation；env 为 pydantic 字段名非 OTel 官方名；无 `/metrics`） | 证据可信度：VERIFICATION 写的"验证通过"必须绑定 git rev 才有意义 | 流程卡点+文档失真 | 本轮暴露 |
| R15 | 镜像分发链路手工且隐性要求多 | save→gzip→scp→`ctr --address /run/containerd-k8s/... import` 三台 + `IfNotPresent` 同 tag 必须 `rollout restart` 才换镜像；无固化脚本、无成功判据，全靠会话内临场 | 任何"改了 Dockerfile/包重验证"的流程都走这条链，下次仍会漏步 | 流程卡点 | 本轮暴露 |
| R16 | Windows PowerShell/sandbox 操作卡点 | 长合并命令触发 base64 EncodedCommand 回显风暴且 scp 静默未落地（本轮实际发生，靠远端 grep 才发现）；嵌套引号必坏；CRLF；port-forward 内联起不来 | 远程演练类任务通用；已有对策（脚本化+sed 去 CRLF+落地校验）未入库 | 流程卡点 | 本轮暴露 |
| R17 | 文档口径失真 | ARCHITECTURE.md 包职责表只列 agent-core tracing，agent-runtime 的 `otel.py/tracing.py` 双实现无记载；AGENTS.md "agent-core 零依赖运行时内核：tracing…" 与 "agent-runtime … tracing/cache" 表述并存但未说明关系与状态机边界；cca9223 VERIFICATION"保留 W3C 父链接"表述因 R6 不成立 | 读文档的人/agent 会按失真口径决策 | 文档失真 | 长期潜伏+本轮新增 |

**分类汇总**：产品码缺陷 R4/R5(码面)/R8/R11；架构缺陷 R3/R6/R7/R9/R10/R12/R13；依赖契约 R1/R2；流程卡点 R14/R15/R16；文档失真 R14(半)/R17。
**"修复前从未真正生效"清单**：R4（OTel init）、R6（traceparent 透传）、R1（agent_server/exhibition 的 Langfuse callbacks）、R7（NoOp 态测试全绿≠真实现可用）。

## 2. 为什么局部修不够（逐条论证）

- **R4/R8 的共性根因是 R3+R7+R12**：真 SDK 路径不在 CI（R3）、NoOp 替身与真实现语义不同形（R7）、接线靠各 app 自觉（R12）。只修 otel.py 符号与 query_router 一处，knowledge-service 两处同款误用（R8③）原样存在，下一个新 app 还会第 N+1 次手写。
- **R6 直接推翻本轮已提交修复的声称效果**：`start_span(context=extract_traceparent(...))` 在 agent_server 提取结果恒 None（门在另一状态机上）——修了生命周期，没修状态机，W3C 链路依旧断。这正是"只让当次验证变绿"的反例，必须全局收口。
- **R1 的三种代际并存**说明共享包把"可选集成"写进了 import 路径却没有版本契约，任何单点升 langfuse 都会在另外两个 app 处破。
- **R5/R9/R11 是同一条设计缺失的三个面**：没有"观测子系统的真实健康状态"这一可查询对象，关闭/坏了/正常三态混同，warn 文案还指错方向。

## 3. 全局方案（三层齐备）

### 3.1 单一实现：观测状态机收敛为一个（解 R4/R5/R6/R7/R9）

**落点：`agent_core`（kernel 实现）+ `agent_runtime.otel`（退役为兼容门面）**

- `agent_core.tracing` 为**唯一**初始化/状态实现（已有幂等 init、contextvars 属性合并、`traced_span` 装饰器、正确的 `with` 用法，工程最完整）。统一三态语义：`DISABLED`（显式关）/ `DEGRADED`（启用但 init 失败，**每次调用点都可通过 health 查询到**）/ `ACTIVE`；guard 的 warn 文案区分"包未安装 / 已安装但 import 失败(附原始异常) / 显式关闭"（R5）。
- `agent_runtime/otel.py` 改为**薄门面**：`init_otel(...)` 参数映射后委托 `agent_core.tracing.init_tracing(...)`；`get_otel_tracer()` 委托 `get_tracer()`；保留原函数签名与 env 字段兼容（agent_server 现有 main.py 调用不改即可切到底层单状态机）。模块 docstring 标注 DEPRECATED 路径与退役版本。
- `tracing_propagation.inject/extract` 的门改读**统一状态机**（`agent_core.tracing.is_tracing_enabled()` 仍成立，因为 agent_server 经门面最终 init 的就是这个状态机）→ R6 断裂消除。
- NoOp shim：删除 `_NoOpSpanContextManager.__getattr__` 兼容 hack（其存在的唯一理由 R8① 本轮已修），让 NoOp 与真实现**同样**对非法用法抛错——替身失真即缺陷放大器（R7）。删除前须全仓 grep `__getattr__` 依赖点并逐一迁移到显式 span API。
- 异步流式安全 span 生命周期提供**内核级标准形**：`agent_core.tracing.start_request_span(name, headers)` 返回 `(span, finish_fn)`，内部用 `start_span(context=extract(headers))`，`finish_fn()` 幂等 end——**不做任何 context attach**，天生免疫 SSE/后台任务跨 Context 问题（R8/R10 的正确姿势由构造给出，而非靠约定）。

### 3.2 全局装配：由构造保证不可漏接（解 R8/R10/R12）

**落点：`build_api_app`（kernel 工厂）扩展 `observability` 装配位**

- 工厂新增可选装配（默认关闭以保持现有对外行为零变化，按 app 逐个开启）：`observability={"tracer_getter": ..., "span_namer": ...}` 或直接接 `KernelConfig`：装配统一 **`TracingMiddleware`**——为**每个** HTTP 请求创建 server span（覆盖 429/409/cache_hit/异常/断连全路径，R10 的旁路问题由"请求级 span 在 middleware 创建"根上消除；handler 内不再手写 span，R8 失去再生土壤），入站 traceparent 提取为父、出站经 httpx 客户端钩子注入。
- agent_server 的 `query_router.py` handler 内手写 span **退役**：切到 middleware span 的 `trace.get_current_span()` 补业务属性（thread_id/priority/脱敏 question——这些在 cache_hit/reject 路径同样写入，覆盖面反超现状）。
- `/health` 增 `otel_status: ACTIVE|DEGRADED|DISABLED`（读真实状态机，R11 修复；**响应体只增字段不改形状**，消费者审计见 §5）。
- 各 app lifespan 统一调 `shutdown_tracing()`（kernel 提供，flush+shutdown provider），替换 agent_server 手写 `otel_force_flush`（main.py:480）。

**三层缺一层说明**：本项不做"强制所有 app 开 middleware"的 big-bang——对外可见 span 数量/形状是行为变更，采取"工厂提供装配 + lint 要求新代码走装配 + 存量逐个迁移摘除手写"的兼容顺序。

### 3.3 强制门禁：lint 不变量入 CI（解 R3/R8 复发/R12/R2 漂移）

**落点：`scripts/lint_architecture.py` 新增 4 条（模式沿用 P2/批3/C1 成熟骨架：全仓正则 + 白名单 + make ci）**

- **L-1**：`applications/**` 生产代码禁止出现 `\.__(?:enter|exit)__\s*\(`（手动 CM 生命周期）；白名单仅限 kernel 兼容层与 contextlib 自身实现。
- **L-2**：`applications/**` 生产代码禁止 `getattr\((?:request\.)?app\.state,\s*"(?:otel_)?tracer"`（tracer 散点取用）——迁移完成后白名单清零，逼新代码走 `trace.get_current_span()`。
- **L-3**：`init_tracing|init_otel` 只允许在 `<app>/main.py`（或 lifespan 装配点）出现，业务模块禁止调 init（防第二状态机私起）。
- **L-4（依赖契约，脚本非正则，`make lint` 或独立 check）**：校验三处 OTel/langfuse 声明版本区间一致（根 `otel`、agent-core `tracing`、agent-runtime 需新增 `otel` extras 并在 `pyproject` 显式声明其 import 的可选依赖面）；agent-runtime 对 langfuse 的 import 必须有对应 extras 声明，否则 CI 红（R1/R2 防回归）。
- **CI 真路径补盲（R3）**：`make test` 增设 session：`uv sync --extra otel` 后跑 `tests/observability/`（新增）——用 `ConsoleSpanProcessor`/in-memory exporter 断言：① init 成功态 `is_tracing_enabled()==True`；② middleware 在 cache_hit/429/409/异常路径各产出 1 个 span（终结 R10）；③ traceparent 头进→span parent id 与头一致（终结 R6 复发面）；④ 无 SDK 环境下三态降级为 DISABLED 而非假 ACTIVE。不装 SDK 的默认 CI 仍全绿（opt-in 铁律不破）。

### 3.4 Langfuse 契约分代治理（解 R1）

- `agent_runtime/tracing.py` 的 v2 `langfuse.callback` import 二选一（方案评审定）：
  - **(a) 推荐**：把 Langfuse 接线**移出共享包**，下沉为 federation 应用层自有 adapter（已存在且是 v3+）；agent-runtime 保留 `get_langfuse_callbacks` 签名但内部改为 `from langfuse.langchain import CallbackHandler`（v3+ 路径）+ extras 声明 `langfuse>=3`；agent_server 侧凭据配置保留，装了才生效。
  - (b) 或共享包只定义 Protocol（回调提供者注入点），实现留在各 app——依赖方向最干净，但改动 agent_server 构造点。
- 无论 (a)/(b)：exhibition `llm_obs.py` 的 v2 import 同步迁 v3+ 或改用注入点；README 踩坑表已登记的 v2/v3 冲突证据作为依据。
- 验收标准：在 agent_server venv `uv sync --all-packages --extra dev --extra otel` 后追加 `--extra langfuse-agent`（新 extras 名评审定）可解析成功且 `get_langfuse_callbacks` 返回非空——**首次真正可测**（此前该组合 pip 必回溯）。

### 3.5 流程与工具入库（解 R14/R15/R16）

- **构建源绑定 git rev**：镜像构建脚本记录 `git rev-parse HEAD` + `git status --porcelain` 摘要写入 VERIFICATION/镜像 label（`--build-arg GIT_REV`），杜绝"验证对象与提交不一致"；同步 126 工作区固定为 `git -C /opt/agent-platform fetch && checkout <rev>` 或 tar 全量同步 + md5 清单校验（本轮 126 Dockerfile 假同步事故的根治）。
- **分发/取证脚本入库**：本轮 16 个 scratch `_*.sh` 的等价固化版放 `deploy/k8s/scripts/`（build/distribute/jaeger/port-forward/e2e/verify 六件套），每个带成功判据与退出码，README 增"可复跑取证"章节。
- **Windows 远程操作守则**：短命令 + 脚本文件承载复合逻辑 + `sed -i 's/\r$//'` + 落地后 grep/md5 校验——写入 `docs/operations/testing-playbook.md`（已有该文档，追加"远程演练"节）。

### 3.6 与既有治理面的关系（避免重复建设）

- 批 3（`monitor.report_tool` choke-point）与 C1（get_tool 直引）已确立"唯一出口+lint"范式，本方案 L-1/L-2/L-3 是同范式的观测面延伸；`agent_core.observability.observe_tool` 的 tool 事件与 OTel span 的关系在实现期明确（span 为传输层、monitor 事件为业务层，不合并，避免语义纠缠）。
- Plan-F「单 Runtime 多 Planner」：观测门面归 agent-runtime 装配层、实现在 agent-core，与"统一 Runtime"方向一致。

## 4. 迁移策略（分步 · 向后兼容顺序 · 回滚）

| 步 | 内容 | 依赖 | 回滚路径 |
|----|------|------|---------|
| S0 | 止血（小 PR）：knowledge-service R8③ 两处 `use_context.__enter__/__exit__` 改内核标准形或显式删除（ks 未 init 真 tracer 时本就无效，行为中性）；VERIFICATION/README 勘误 R6 表述 | 无 | revert 即回 |
| S1 | kernel 状态机统一：三态语义 + 文案修正 + `start_request_span` 内核 API + 删 `__getattr__` hack（先补全仓误用点再删）+ 单测（含真 SDK 路径 in-memory exporter） | S0 | `agent_runtime.otel` 门面保持旧行为一版（feature flag `OBS_UNIFIED=False` 默认旧路径） |
| S2 | `build_api_app` 装配 `TracingMiddleware`（opt-in 参数）；agent_server 切装配位、退役 handler 手写 span；`/health` 增 `otel_status` 字段（只增不改） | S1 | 中间件装配是工厂参数，置空即回 S1 态 |
| S3 | lint L-1..L-4 入 `make lint`/CI + `tests/observability` 真 SDK session；CI 默认矩阵加 `--extra otel` | S1/S2 | lint 白名单过渡（先警告期一个迭代再强制） |
| S4 | Langfuse 契约 (a) 或 (b) 落地 + exhibition 同步迁 | S1（Protocol 注入点若选 b） | 各 app 独立开关，互不阻塞 |
| S5 | 流程入库：GIT_REV 构建脚本 + deploy/k8s/scripts 六件套 + playbook 追加节 | 独立可并行 | 纯增量 |

**兼容顺序**：kernel API（只增）→ 门面委托（签名不变）→ 装配（opt-in 参数）→ 门禁（警告期→强制）→ 契约变更（Langfuse，需消费者审计后）。

## 5. 消费者契约审计清单（改动前必审，不得静默破坏）

- `/health` 响应体：只**增** `otel_status` 字段；审计联邦网关/前端/dashboard 是否严格 schema 校验。
- 对外端点：`POST /query` SSE 事件序**不变**（cache_hit 路径是否补 `type:"trace"` 事件需先审计前端兼容性，列为可选不默认）。
- federation↔子服务：traceparent 透传从"恒断"变"通"是修复，但下游若曾基于"无 traceparent 头"写死 root span 逻辑需知会（ks/federation 内 extract 门本来就读 agent_core，S2 后行为变化点在此）。
- 错误体形状：本方案不动（P2 已收口）。
- langfuse extras：agent_federation `observability=[langfuse>=4.0.0]` 保持；agent-runtime 新增声明不得抬高 federation 解析结果（uv lock diff 审查）。

## 6. 验收标准（可执行）

```bash
# 1. lint 门禁（新增 L-1..L-4 全绿）
uv run python scripts/lint_architecture.py            # 期望新增 4 行 "观测约束通过"
# 2. 真 SDK 路径 session（CI 与本地 --extra otel）
uv run --extra otel pytest tests/observability -q      # 期望：三态/旁路 span/traceparent 父子一致/in-memory 断言全绿
# 3. traceparent 端到端（真实集群补盲项）
#    port-forward 后带 -H 'traceparent: 00-<32hex>-<16hex>-01' POST /query
#    Jaeger API: /api/traces?service=agent-platform → 新 trace 的 traceID == 请求头 trace-id 段
# 4. cache_hit 可观测（终结 R10）
#    连发同一唯一 query 两次：第二次 Jaeger 亦出现 span 且 attribute cache_hit=true
# 5. 三态可查询（终结 R5/R11）
#    不装 otel 而设 OTEL_ENABLED=true → /health 返回 otel_status=DEGRADED 且日志含原始 ImportError
# 6. Langfuse 契约（S4 后）
#    uv sync --all-packages --extra otel --extra <lf-extra> 解析成功（无回溯）；
#    agent_server 单测真 import 路径 callbacks 非空
# 7. 文档同步门禁
uv run python scripts/check_doc_sync.py                # 必须通过
```

## 7. 文档同步修订清单

| 文档 | 修订 | 时点 |
|---|---|---|
| `deploy/k8s/VERIFICATION.md` | 勘误："保留 W3C 父链接"表述改注为"生命周期修复已落地；父链接透传受 R6 双状态机影响实际未生效，S2 修复后复验" | **S0 立即**（本轮已随方案提交） |
| `deploy/k8s/README.md` 踩坑表 | 增 R6 行（双状态机致透传断） | S0 立即 |
| `ARCHITECTURE.md` | 包职责表补记 agent-runtime 观测门面与"单状态机在 kernel"的目标态 | S1 |
| `AGENTS.md` | 目录表 agent-runtime 行补"otel 门面（deprecated 中）"；红线不变 | S1 |
| 本方案 | 状态改"已实施"，登记 commit 链 | S5 后 |

## 8. 验证计划（分层 · 又快又准）

- **本地窄分层**（每步 PR 必跑）：`ruff check` + `lint_architecture` + 受影响子集 pytest（S1→`packages/agent-core/tests` + `packages/agent-runtime/tests/test_otel.py`；S2→`tests/api` + `applications/agent_server/tests`；S3→`tests/observability` 新 session）。
- **需真环境补盲（本地不声称覆盖）**：① traceparent 父子一致 e2e（真集群 + Jaeger，用 §6-3 命令）；② `--extra otel` 与 langfuse extras 的组合解析（本地 uv 即可验证回溯消除，真集群复跑镜像构建）；③ cache_hit 出 span 后 Jaeger UI 截图存档 VERIFICATION。
- **长任务后台化**：镜像重建/分发（~4min/轮）setsid 后台 + 标记文件轮询；真 SDK 依赖解析测试 `uv lock --check` 先行。
- **卡点与对策**（本轮实测）：跨网验证一律脚本承载 + 落地校验（R16 守则）；行号定位先确认构建源 rev（R14）；测试 query 强制唯一化绕缓存（R10 方法学）。
- **诚实标注基线**：Langfuse 面在 S4 落地前维持"不可用"标注；本轮业务面已通过（真实 LLM，ModelScope DeepSeek-V4.1-Flash，SSE 全事件流无异常），不回收。

## 9. 非目标 / 边界

- 不合并 `agent_core.observability`（业务事件总线）与 OTel（传输层 tracing）——语义分层保留，仅明确关系。
- 不改错误体/`/query` 对外契约形状（消费者审计通过前）。
- 不在本方案内处理无关旁路发现（memory embedder `dim=` 参数错误、coroutine not subscriptable——已另行登记为独立缺陷，建议进 tech-debt 追踪）。
- 集群 kubeadm reset 清理仍待用户二次确认，与本方案解耦。

## 10. 实施进度（2026-09-29 S0+S1 已落地）

**已实施**（commit 见 git log，本轮范围内全部本地实跑验证）：

| 项 | 内容 | 验证证据 |
|---|---|---|
| L-3 门禁 | `lint_architecture.py` 新增观测 init 散点禁令（装配点/过渡门面/eval 白名单；注释行过滤） | 首跑即抓到真实违规 exhibition（定性为合法装配封装入白名单）；终跑 7 条全过 |
| L-1 门禁 | 禁止手动 `.__enter__()/.__exit__()`（全仓生产码，白名单空） | 通过；存量违规随 S0 修复清零 |
| kernel 单状态机 | `agent_core.tracing` 新增：三态 `get_tracing_status()`（UNINITIALIZED/DISABLED/DEGRADED/ACTIVE+reason，R5）、`sampling_rate` 参数（门面能力下沉）、`force_flush()`；删 `_NoOpSpanContextManager.__getattr__` hack（R7，删前全仓 grep 确认零依赖） | agent-core 全套 + runtime 全套 259 passed |
| 门面化（R6 消除） | `agent_runtime/otel.py` 重写：销毁 `_OTEL_AVAILABLE/_tracer` 第二状态机，`init_otel/get_otel_tracer/force_flush` 全部委托 kernel；签名兼容，agent_server main.py 零改动 | 真 SDK smoke（`--with opentelemetry-sdk`）：门面 init→status=ACTIVE、`is_tracing_enabled()`=True、inject 出真 traceparent、extract 非 None——R6 链路物理贯通；`exporter=none`→DISABLED |
| R18（本轮新发现） | 旧门面 `parse_traceparent` import 不存在类名 `TraceContextFormat`（真名 `TraceContextTextMapPropagator`），ImportError 被吞→从诞生起恒返回 None（生产零调用点，仅测试钉住）；已修 | test_otel 伴随用例更新（原断言钉的是缺陷行为，据实改写并说明） |
| S0 止血（R8③） | knowledge-service `query_router.py` `/query`+`/retrieve` 4 处手动 enter/exit 改 `with use_context(...)` 标准形；流式分支 background_task 不继承上下文的限制如实注记（父链透传属 S2） | ks unit 376 passed；tests/api 16 passed；ruff 全仓过；check_doc_sync 0 警告 |

**未完成（后续批次）**：S2 尾项（ks 开启中间件：ks main.py 尚未迁 build_api_app，裸 FastAPI 白名单现状；ks 流式父链透传；ks/federation/exhibition lifespan 接 shutdown_tracing——仅 agent_server 已接，随各 app 开启节奏）；S4（Langfuse 代际契约）；S5（构建 rev 绑定/部署脚本入库）；R6 真集群端到端复验（本地已由 tests/observability 真 SDK 钉住父子一致，Jaeger 现场复验待集群重验后更新 VERIFICATION L141 勘误注）；门面退役（L-2 白名单已空，otel.py 本体+白名单行待后续删除）。

## 11. 实施进度（S2+S3 已落地，2026-09-29）

| 项 | 内容 | 验证证据 |
|---|---|---|
| kernel 中间件（R10/R12） | 新增 `agent_core/tracing_middleware.py`：纯 ASGI `TracingMiddleware`，每请求 SERVER span（finally 恒 end，含断连 CancelledError）；入站 traceparent 提取为父（R6 唯一挂载点）；关闭态逐请求门控透传零开销 | 真 SDK 钉用例：200/429/500 旁路各产出 1 span；trace_id/parent_span_id 与头段一致 |
| 全局装配（构造保证） | `build_api_app` 新增 `enable_tracing` 参数（默认关，opt-in 逐 app 开启，方案 §4 兼容顺序）；agent_server 已开 | 工厂单测路径（tests/observability 经工厂建 app）全部绿 |
| 手写 span 退役（R8） | agent_server `query_router` 删 `app.state.otel_tracer` 散点取用与手写 request span（含 finally end）；切 handler 早段 `record_request_attributes`（thread_id/priority/脱敏 question 覆盖 429/409/cache_hit 旁路）+ cache_hit 专属属性 | tests/api 25 passed；agent_server session 44 passed；lint L-2 白名单空通过 |
| lifespan 统一退出（R9） | kernel 新增 `shutdown_tracing()`（flush+shutdown provider）；agent_server 替掉手写 `otel_force_flush`；门面 `force_flush` 保留供过渡 | 真 SDK session 无尾批丢失告警 |
| /health 真状态（R11） | `shared_schemas.HealthResponse` 只增 `otel_status` 字段（不改形状，§5 审计）；health_router 读 `get_tracing_status()` 真值非 settings 意愿值 | shared-schemas session 入 881 passed 全套 |
| L-2/L-4 门禁 | L-2：禁 app.state 取 tracer（白名单空）；L-4：OTel/langfuse extras 声明齐备且多处下界一致（根[otel]与 core[tracing]/runtime[otel] 归一 >=1.24；agent-runtime 新增 otel+langfuse extras；langfuse import v2→v3 迁面属 S4 已注记）；`uv lock` 重生 | lint 9 条全过；`uv lock --check` RC=0 |
| S3 真 SDK session（R3 补盲） | Makefile `test` 新增 `uv run --extra otel pytest tests/observability -q`（不计入标准 session 计数，仍 9）；新建 `test_tracing_middleware.py`（旁路/父子/三态 5 钉）；`test_otel.py` 环境自适应（autouse reset + 无 SDK 前提用例按 _SDK_AVAILABLE 分支 skip） | 真 SDK session 14 passed；无 SDK 根 session 自动 skip（1 skipped）；check_doc_sync 0 警告 |

本地全套验证（无 SDK 窄层 + 真 SDK 补盲均实跑）：lint 9 条、ruff 全仓、agent-core+runtime+shared-schemas 881 passed、tests/api+observability 25 passed/1 skipped、--extra otel session 14 passed、agent_server 44 passed、federation 146 passed、check_doc_sync 0 警告。

## 12. 实施进度（S4+S5 已落地，2026-09-30）

| 项 | 内容 | 验证证据 |
|---|---|---|
| S4 代际契约（§3.4 选项 a） | `agent_runtime.tracing.get_langfuse_callbacks` 签名不变，内部迁 v3+/v4：凭据进 `Langfuse()` 客户端构造 + `langfuse.langchain.CallbackHandler(public_key=)` 绑定（langfuse 4.14.4 实探签名：handler 不再收 secret_key/host，旧 v2 写法真装必 TypeError）；exhibition `llm_obs.py` 同步迁 `langfuse.langchain`（无参 env 驱动形态不变） | 新钉用例 `test_get_langfuse_callbacks_real_import_path`（未装自动 skip）；`uv run --extra otel --with langfuse pytest packages/agent-runtime/tests` **608 passed**（方案 §6-6 组合首次可测）；默认 session 607 passed/2 skipped |
| S4 伴随修复（实跑揭出的两个存量缺陷） | ① `test_tracing.py` 两用例模拟点 `sys.modules["langfuse.callback"]` 随 import 面切 `langfuse.langchain`（旧模拟点钉 v2 路径，真装环境下前提失效非断言放宽）；② exhibition `test_server.py` traceparent 守卫用例 `InMemorySpanExporter` 错误导入路径修正（venv 装了 otel extras 后 skip 遮蔽消失暴露；同 S2 钉用例踩过的同一坑） | 修复前后失败链定性存档；exhibition **344 passed**（含 SDK 环境下 traceparent 回归守卫实跑通过） |
| S4 L-4 扩展 | exhibition pyproject 新增 `[langfuse] >=4.0.0` extras（此前无任何声明位）；L-4 作位增至 6 处 | lint 9 条全过（含 exhibition）；`uv lock` RC=0 无回溯 |
| S5 GIT_REV 绑定（R14/126 假同步根治） | Dockerfile 新增 `ARG GIT_REV` + OCI revision label + `/srv/agent-platform/GIT_REV` 文件（置于依赖层之后防缓存失效）；注释中「Langfuse 不可共存」叙事更新为 S4 已终结；`build.sh <rev>` 构建源 HEAD 不匹配即 exit 2 拒绝构建 + 镜像内回读校验 | `bash -n` 六脚本语法全过（Git Bash） |
| S5 六件套入库（R16） | `deploy/k8s/scripts/`：build/distribute/jaeger/portforward/e2e_traceparent/verify（本轮 16 个 scratch `_*.sh` 等价固化），每个头部自带用法/成功判据/退出码；README 增「可复跑取证」节（六件套表 + 典型复跑序列 + OTel env） | 语法检查 RC=0；与 VERIFICATION 现场形态对齐（隔离 containerd sock、IfNotPresent+rollout restart、sleep≥8 flush、唯一 query 绕缓存） |
| S5 playbook 远程演练节 | `testing-playbook.md` 新增 §5：短命令+脚本承载、LF 行尾（.gitattributes 已强制）、落地验证不凭 RC、PowerShell 假阳性定性套路、验证对象绑定提交、共用机纪律 | 文档落位；check_doc_sync 0 警告 |

本地全套验证：lint 9 条、ruff 全仓、根 700 passed/26 skipped、core+schemas 273 passed、agent_server 44、agent-runtime 默认 607/2s + otel+langfuse 组合 608、exhibition 344、check_doc_sync 0 警告。

**未完成（收口前剩）**：R6 真集群端到端复验（可直接走 `deploy/k8s/scripts/` 六件套序列：同步 126 → build.sh <rev> → distribute → e2e_traceparent.sh → 关 VERIFICATION L141 勘误注；本地层面父子一致已由 tests/observability 钉住）；S2 尾项（ks 迁工厂+开中间件、流式父链、各 app lifespan）；门面退役（otel.py 本体+L-3 白名单行）；集群 kubeadm reset 待用户确认。
