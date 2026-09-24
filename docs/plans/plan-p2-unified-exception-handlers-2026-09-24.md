# P2 方案：为其余 5 应用补统一脱敏异常 handler（2026-09-24）

> 承接 P0-4 真实降量轮次的结论：本仓 6 应用**仅 knowledge-service** 注册了 FastAPI 全局
> `add_exception_handler`。"删冗余 except → 冒泡给全局 handler"（桶 B）的**三重前提**里，
> 第 ① 条（目标应用真注册 handler）在其余 5 应用不成立，故那条降量路被堵死。
> P2 = 补齐第 ① 条前提，让 5 应用具备"未捕获异常 → 统一 500 脱敏"能力，为后续仓库级降量解锁。
>
> 关联：`p0-execution-retrospective-2026-09-24.md` §3/§4、`plan-p0-4-blind-except-real-reduction-2026-09-24.md` §7。

## 1. 目标与非目标

**目标**
- 5 应用（agent_server / agent_federation / kefu-service / nl2sql-service / exhibition-agent）注册统一异常处理器，使未捕获异常返回**脱敏 500**（详情仅入服务端日志，不外泄堆栈/内部路径/密钥）。
- 复用而非 5 份复制：把 knowledge-service 已验证的错误信封纯逻辑上提到共享层，避免实现漂移。

**非目标（本轮明确不做）**
- 不改各应用**现有 4xx 业务错误的对外信封形状**（见 §4 决策，Phase 2b 另行评估）。
- 不删除任何 `except Exception`（桶 B 降量是 P2 落地**之后**的独立轮次）。
- 不动 knowledge-service（已有 handler，保持）。

## 2. 勘察结论（各应用现状）

| 应用 | app 创建 | 现有全局 handler | 现有错误信封 | 备注 |
|------|---------|:---:|------|------|
| agent_server | `main.py::create_app()` | ❌ | FastAPI 默认 `{detail}`，detail 常为语义码（`BUDGET_EXCEEDED`/`CONCURRENCY_REJECTED`/`SCHEDULER_SLOTS_EXHAUSTED`） | 前端(vite:5173)消费 detail |
| agent_federation | `api/server.py` 模块级 `app` | ❌（但有 middleware） | 已挂 `SecurityGuardsMiddleware`，401/429/413 已是 `{code,msg,request_id}`；业务 HTTPException 仍 `{detail}` | 复用 agent_core guardrails 最顺 |
| kefu-service | `kefu_agent/__main__.py` 模块级 `app` | ❌ | `/invoke` 返回 `QueryResponse`；错误走 FastAPI 默认 | 被联邦网关按状态码调用 |
| nl2sql-service | `api/server.py::create_app()` | ❌ | 返回 shared_schemas；错误走默认 `{detail}` | 被联邦网关调用 |
| exhibition-agent | **两个 app**：`server.py` + `skill_loader/app.py` | ❌ | 大量 `HTTPException(detail=中文可读)`，detail **即产品文案**（前端控制台展示） | 双入口都要注册 |

**可复用底座（已在共享包）**
- `agent_core.tracing.get_request_id()` ✅ 存在 → handler 可直接取当前请求 request_id。
- `agent_core.guardrails.web._default_error_response` 已产出 `{code, msg, request_id}` + `X-Trace-Id` 头，与 knowledge-service 信封**同构**。
- `knowledge_service/utils/error_response_utils.py`：`ERROR_CODES` / `error_code_for_status()` / `error_body()` —— **纯逻辑无 web 依赖**，是上提共享的现成候选。

**两条实测纠偏（决定"全局"该怎么解）**
- **无人开 `debug=True`** → Starlette 内置 `ServerErrorMiddleware` 已在**框架层**拦截未捕获异常返回裸 500，堆栈/内部路径**本就不外泄**。故"脱敏防泄露"其实已全局兜底；真正缺的是统一 JSON 信封 `{code,msg,request_id}` + request_id 回传 + 服务端结构化日志。
- **全仓无统一 app 工厂**：6 个生产 app 各自裸调 `FastAPI(...)`（ks/agent_server/nl2sql 有 `create_app`，federation/kefu/exhibition×2 是模块级）。仅 `install_error_handlers` 在 6 处各调一次 = 逻辑收敛但**接线仍散落**，是"每处各自实现"的反模式，须从架构上消除（见 §3.2/§3.3）。

## 3. 设计：全局优先（单一实现 → 全局装配 → 强制门禁）

> 定性：入站错误处理是**框架/架构级横切关注点**，不是各 app 的业务细节。"全局"必须同时满足三件事——实现只有一份、装配不可漏、未来漂移被门禁拦截。v1 只做了第一层，本节补齐三层。

### 3.1 单一实现（kernel 拥有入站错误层）
入站横切（鉴权/限流/载荷/request_id/错误信封）本就是 `SecurityGuardsMiddleware` 的职责域，**错误处理是同一层的另一面**，实现集中到 `agent_core.guardrails`：
- 新建 `packages/agent-core/agent_core/guardrails/errors.py`（纯逻辑 + starlette 软依赖，与 web.py 同级）：
  - `ERROR_CODES` / `error_code_for_status()` / `error_body()`（从 knowledge-service 上提，逻辑不变）。
  - `make_error_response(status, code, msg, request_id, headers=None)`（等价现 `_default_error_response`）。
  - `install_error_handlers(app, *, get_request_id, logger, sanitize_5xx_msg=..., include_validation_error=True)`：注册 `Exception`→500 脱敏（4xx 是否改写见 §4）；`get_request_id`/`logger` **注入**，agent-core 不 import applications（守红线 1）；`RequestValidationError` 仅当 fastapi 可导入时注册（import-guard）。

### 3.2 全局装配（消除"每处接线"）—— 统一 app 工厂
让"漏接不可能"的根本手段是**kernel 拥有的 app 工厂** `agent_core.guardrails.web.build_api_app(...)`：
- 内部一次性装配 `FastAPI(...)` + CORS + `SecurityGuardsMiddleware` + `install_error_handlers`，返回 app；参数化 `lifespan=` / `**fastapi_kwargs` / 各护栏阈值，app 拿到返回值后仍可 `include_router`。
- 6 个生产 app 全部改为经此工厂创建（exhibition 两 app 亦然）→ 错误处理**由构造保证**，非靠每个开发者记得调。
- **代价（须你知悉并批准）**：agent-core 将**软依赖 fastapi**（现仅软依赖 starlette），沿用 `web` extra 的 import-guard 模式隔离，不污染零依赖核心路径；且需把 6 app 的 lifespan/中间件差异参数化，装配面比 v1 大。

> **轻量替代（若不愿给内核加 fastapi 依赖）**：各 app 仍各自 `FastAPI(...)`，但唯一入口收敛为复合函数 `install_guardrails(app, ...)`（middleware + exception handler 一把装配），接线仍是"1 处/app"但**完整不可半装**。这是 3.2 的降级版，配合 3.3 门禁同样能防漂移。

### 3.3 强制门禁（让"全局"可持续，拦未来漂移）
复用本仓已确立的架构不变量范式 `scripts/lint_architecture.py`（P4-2 即"全仓扫描 + 白名单"式 CI 门禁），新增一条不变量：
- **生产代码 `applications/**` 出现裸 `FastAPI(` 字面量即 CI 失败**（白名单：工厂自身所在文件 + 各 `tests/`）。
- 使"所有 app 经工厂/复合装配创建"从"约定"升级为"架构保证"，新 app 无法静默绕过。

> knowledge-service 保持自己的 `api/errors.py` 不强行迁移（避免扰动已绿测试），仅**注明**其纯逻辑与共享层等价，留给后续收敛轮（见 §8 D-3）。

## 4. 关键契约决策（**需你拍板**）

统一 handler 要不要**改写现有 4xx 的对外信封**，是本轮唯一真正的破坏性风险点：

- **方案 A（推荐，保守/零破坏）**：只注册 `Exception → 500 脱敏`。
  - 现有 `HTTPException`（4xx/显式 5xx）保持 FastAPI 默认 `{detail}` 不变 → exhibition/agent_server 前端**零影响**。
  - 已足够解锁 P2 目标（前提 ①）：未捕获异常从此有兜底脱敏 500，为桶 B 铺路。
  - federation 的 401/429/413 已由 middleware 给 `{code,msg,request_id}`，与 A 不冲突。
- **方案 B（彻底统一，破坏性）**：额外把 `StarletteHTTPException` + `RequestValidationError` 也改写成 `{code,msg,request_id}`（对齐 knowledge-service）。
  - 4xx `msg` 透传原 detail（沿用 `_sanitize_detail`：4xx 保文案、5xx 通用），但**外层信封从 `{detail}` 变为 `{code,msg,request_id}`**。
  - 需先审计 5 应用的前端/网关是否解析错误体形状（exhibition 前端展示 detail、联邦网关是否读 body）——**消费者协同**，风险外溢。

**建议：本轮走 A**，把 B 的"4xx 信封统一 + 消费者审计"降级为独立后续（P2b）。A 用最小改动闭合 P2 的核心目的，且不赌任何未验证的消费者假设（呼应复盘 §4"先实测再动手"）。

## 5. 测试

- **共享层单测**（`packages/agent-core/tests`，无 web 依赖部分 + starlette skipif）：
  - `error_code_for_status` / `error_body` 纯逻辑；
  - `install_error_handlers`：最小 ASGI/FastAPI app 抛未捕获异常 → 断言返回 500 + `{code:INTERNAL_ERROR, msg:脱敏文案, request_id}` + `X-Trace-Id` 头 + 响应体不含堆栈关键字（`Traceback`/文件路径）。
- **各应用接入 smoke**（对应应用 test 目录）：断言 `Exception in app.exception_handlers`（对齐 knowledge-service `test_register_exception_handlers_registers` 的写法）。
- 全绿门禁：`uv run --with ruff ruff check .` = 0；`uv run python scripts/check_doc_sync.py` = 0 警告；受影响 pytest session 通过。

## 6. 验收标准

1. 5 应用（exhibition 计 2 app = 6 个 app 实例）均注册 `Exception` handler；未捕获异常返回脱敏 500。
2. 复用共享 `agent_core.guardrails.errors`，无 5 份复制逻辑。
3. 现有对外响应契约**零破坏**（方案 A 下 4xx detail 不变；QueryResponse/HealthResponse 成功路径不变）。
4. lint / doc_sync / 相关 pytest 全绿；不新增逐点 noqa。

## 7. 影响面与红线自查

- 依赖方向：agent-core 新增模块只依赖 starlette(软) + 注入的 callable，**不 import applications** ✅。
- 先方案后编码：本文档即方案，**待批准后实施**（§impl 任务保持 PENDING）。
- 不凑绿：不改断言/删用例；测试红则修产品代码到契约。

## 8. 待决策清单（请你确认）

> ✅ **已定（2026-09-24，用户拍板）**：**D-1 = ①**（统一 app 工厂 `build_api_app`，真·全局、由构造保证）；**并保留 D-4 ③ lint 门禁**（工厂+门禁双保险）；**D-2 = A**（仅注册 `Exception→500` 兑底，不动 4xx `{detail}` 现有契约）；**D-3 = 不动** knowledge-service（避免扰动已绿测试，其 `main.py` 入 lint 门禁白名单，留后续收敛）。下方保留原选项供追溯。

- **D-1（装配层级，本轮核心）**：选哪个"全局"粒度？
  - **① 统一 app 工厂 `build_api_app`（真·全局，由构造保证）** —— 代价：给 agent-core 软依赖 fastapi + 6 app 参数化迁移，装配面最大。
  - **② 复合 `install_guardrails(app,...)`（轻量，1 处/app 但完整）** + **③ 裸 `FastAPI(` lint 门禁** —— 不加 fastapi 内核依赖，靠门禁保证不可漏。【我推荐 ②+③：拿到全局保证又不改内核依赖形态】
  - （v1 的"6 处各调 install_error_handlers"已废弃——接线散、无门禁，不算全局）
- **D-2（信封契约）**：方案 A（仅 `Exception→500` 兑底，零破坏，推荐）vs 方案 B（连 4xx 也统一为 `{code,msg,request_id}`，破坏性，需消费者审计）。
- **D-3（knowledge-service）**：本轮**不动**（推荐，避免扰动已绿测试），仅注明其纯逻辑与共享层等价，留后续收敛。
- **D-4（lint 门禁范围）**：确认采用 §3.3 "裸 `FastAPI(` 即失败"作为常驻不变量（参加 `make ci`/`lint_architecture.py`）。

## 9. 执行结果（2026-09-24，D-1=① 已落地）

**kernel（单一实现 + 全局装配）**
- 新增 `agent_core/guardrails/errors.py`：`ERROR_CODES`/`error_code_for_status`/`error_body`（纯逻辑零依赖）+ `make_error_response`/`install_error_handlers`（starlette 懒导入）。D-2=A：仅注册 `Exception→500` 脱敏。
- 新增 `agent_core/guardrails/app_factory.py`：`build_api_app(**fastapi_kwargs, get_request_id=, logger=, install_handlers=True)`，构造即装 handler。
- `agent-core` `web` extra 补声明 `fastapi`（诚实软依赖，无未声明不可达风险）。

**全局装配迁移**（6 个 app 实例改经 `build_api_app`）
- agent_server `create_app` / nl2sql `create_app` / agent_federation 模块级 / kefu 模块级（并删冗余 `FastAPI` import）/ exhibition `server.py` + `skill_loader/app.py`。knowledge-service 按 D-3 未动。

**强制门禁**
- `scripts/lint_architecture.py` 新增不变量：`applications/**` 生产代码裸 `FastAPI(` 即失败（白名单：ks `main.py`、exhibition `mock_server/warehouse_mock.py`、各 `tests/`），与 P4-2 并列计入 `make ci`。

**验证（全绿）**
- 全局 `ruff check .` = 0；`lint_architecture.py` 双不变量通过；`check_doc_sync.py` 0 警告。
- `agent-core` 全包 **209 passed**（含新增 `test_guardrails_errors.py` 9：纯逻辑 + 未捕获异常→脱敏 500 + 4xx detail 不变）。
- 迁移 app 导入即构造验证：nl2sql 18 / kefu 43 / agent_server 41 / exhibition 343(+1skip) / **federation 134** 全 passed。

**净效果**：入站错误处理从"1/6 手写、其余裸默认"收敛为 **kernel 工厂统一装配 + 门禁防漂移**；为后续仓库级"删冗余 except → 冒泡 handler"（桶 B）补齐了前提 ①。
