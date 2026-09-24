# 修复方案：F-S1-06 — _NoOpTracer 双实现收敛（agent-runtime 复用 agent-core no-op shim）

> 日期：2026-09-21
> 严重度：**P2**（红线 4 违规 / 内核能力重复实现）
> 来源：[S2 债务诊断](../analysis/2026-09-21/02-debt-diagnosis.md) §2.2 F-S1-06
> 状态：**已确认并实施**（2026-09-21；二审修订补 `_NoOpSpanContextManager.__getattr__` 转发以兼容 agent_server 手动 CM 用法）

## 1. 目标

消除 `_NoOpSpan` / `_NoOpTracer` 两套独立 no-op 实现（红线 4：内核能力不得重复实现），agent-runtime 的 `otel.py` 改为复用 `agent_core.tracing` 的 no-op shim，保持行为零变更。

## 2. 问题分析

### 2.1 当前状态（两套实现）

| 维度 | `agent_core/tracing.py:98-151` | `agent_runtime/otel.py:35-64` |
|------|-------------------------------|-------------------------------|
| `_NoOpSpan` 方法 | set_attribute / set_attributes / record_exception / set_status / end / is_recording（`__slots__` 零开销） | set_attribute / record_exception / add_event / end（**自身兼作 context manager**） |
| CM 语义 | `_NoOpSpan` 非 CM，由 `_NoOpSpanContextManager` 包装 | `_NoOpSpan` 直接 `__enter__/__exit__` |
| `_NoOpTracer` | start_span / start_as_current_span | start_span / start_as_current_span |

### 2.2 历史背景（H-S1-03 假设已验证）

- 两文件均诞生于 2026-08-12（b546aa5，同日并存）；
- 2026-08-13 f8a328e「H2/H3/H4 消除模块重复」已把 otel hash 上提 agent-core（otel.py:14 复用 `user_query_hash`），但 **no-op shim 未纳入该轮收敛**——本方案是 f8a328e 的补完。

### 2.3 调用方盘点（收敛兼容面）

| 调用点 | 用法 | agent-core `_NoOpSpan` 兼容性 |
|--------|------|------------------------------|
| `agent_runtime/context/assembler.py:508-519` | `get_otel_tracer().start_span(name)` → `set_attribute` ×6 → `end()`（**非 with**） | ✅ set_attribute / end 均有 |
| `agent_server/main.py:154,160` | `init_otel(...)` + `get_otel_tracer()` 存 `app.state` | 与 shim 无关（init 路径） |
| `agent_server/api/routes.py:196-198,258` | `span = start_as_current_span("query")` → **手动** `span.__enter__()` / `span.set_attribute(...)` ×N / `span.__exit__()`（**非 with**，且直接在 CM 对象上调 span 方法） | ⚠️ **不兼容，须补 CM 转发**（见 §2.4） |
| `otel.py:78,82,135,141` | 降级路径赋值 `_tracer = _NoOpTracer()` | 改为 `noop_tracer()` 即可 |

**差异项核查**：
- `add_event`（仅 runtime 版有）：全仓零调用 → 不迁移，YAGNI；
- `set_attributes` / `set_status` / `is_recording`（仅 core 版有）：超集能力，无风险；
- **CM 语义（二审修订，原方案漏判）**：runtime 版 `_NoOpSpan` **自身兼作 CM**（同时具备 `__enter__/__exit__` 与 span 方法），故 `routes.py` 的"取 CM 对象 → 手动 `__enter__` → 直接调 `set_attribute`"可用；core 版 `_NoOpTracer.start_as_current_span` 返回的 `_NoOpSpanContextManager` **只有** `__enter__/__exit__`，直接调 `set_attribute` 会 `AttributeError`。原方案"runtime 无 with 调用方，语义等价"的结论**不成立**。
- 触发条件：`routes.py` 该分支仅在 `otel_effective_enabled=True` 且（SDK 未装 或 `exporter="none"`）走 no-op 降级时进入；默认 opt-out（`app.state.otel_tracer=None`）不触发，故属"配置开启后才暴露"的行为差异。

### 2.4 二审修订：CM 兼容补丁

为保证"行为零变更"，agent-core 侧给 `_NoOpSpanContextManager` 增加 `__getattr__` 属性转发到内部 `_NoOpSpan`：

- 覆盖 `routes.py` 手动 CM 用法（`cm.set_attribute(...)`）；
- 不改变既有 `with _NoOpSpanContextManager() as span` 语义（`__enter__` 仍返回内部 span，`__getattr__` 不参与）。

### 2.4 现状事实补充

`get_otel_tracer` 的唯一 span 使用点是 `assembler.py`（生产路径）；`otel.py` 无独立测试覆盖。

## 3. 影响面

### 3.1 直接影响（改动文件）

| 文件 | 改动 |
|------|------|
| `packages/agent-core/agent_core/tracing.py` | **纯增量**：新增公开工厂 `noop_tracer()`（薄封装既有 `_make_noop_tracer`）；`_NoOpSpanContextManager` 增 `__getattr__` 转发（兼容 agent_server 手动 CM 用法，见 §2.4） |
| `packages/agent-runtime/agent_runtime/otel.py` | **纯删减**：删除 `_NoOpSpan`（:35-54）、`_NoOpTracer`（:57-64）共约 30 行；`from agent_core.tracing import noop_tracer, user_query_hash`；4 处 `_NoOpTracer()` 改 `noop_tracer()` |

`assembler.py` / `agent_server/main.py` **不改**（接口兼容，消费方无感知）。

### 3.2 依赖方向

`agent-runtime` → `agent-core` 为既有正向依赖（otel.py:14 已 import），无新增依赖边。

## 4. 迁移策略

### 4.1 改动 1：agent-core 公开 noop 工厂（tracing.py，`_make_noop_tracer` 之后）

```python
def noop_tracer() -> Any:
    """公开 no-op tracer 工厂：供下游包（agent-runtime 等）复用，避免各自再造 shim。

    语义与 :func:`_make_noop_tracer` 一致：零开销、绝不抛异常。
    """
    return _make_noop_tracer()
```

### 4.1b 改动 1b（二审修订）：`_NoOpSpanContextManager` 增属性转发

```python
class _NoOpSpanContextManager:
    __slots__ = ("_span",)

    def __init__(self) -> None:
        self._span = _NoOpSpan()

    def __enter__(self) -> _NoOpSpan:
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        # 兼容下游"手动进入 CM 后直接调 span 方法"用法（agent_server/api/routes.py:196-198）；
        # with ... as span 路径不触发 __getattr__，语义不变。
        span = object.__getattribute__(self, "_span")
        return getattr(span, name)
```

### 4.2 改动 2：agent-runtime otel.py 删减

```python
# 删除 :35-54（_NoOpSpan）与 :57-64（_NoOpTracer）
# :14 改为
from agent_core.tracing import noop_tracer, user_query_hash
# :78 / :82 / :135 / :141 四处 _NoOpTracer() 均改为 noop_tracer()
```

### 4.3 范围外（后续项，本次不做）

- `init_otel`（自管 `_tracer` + `set_tracer_provider`）与 `agent_core.tracing.init_tracing` 是**两套 tracer 管理状态**，属更深层的收敛（对应诊断 §2.2「再造 Runtime」主题），涉及 agent_server 启动路径，需单独立项评估。本次仅收敛 no-op shim。

## 5. 验收标准

### 5.1 功能验收

| # | 命令 | 预期 |
|---|------|------|
| 1 | `uv run pytest packages/agent-runtime/tests -q` | 62 passed（assembler 路径由 lifecycle/middleware 测试覆盖） |
| 2 | `uv run pytest packages/agent-core/tests -q` | 198 passed（core 侧纯增量无回归） |
| 3 | `uv run python -c "import agent_runtime.otel as o; t=o.get_otel_tracer(); s=t.start_span('x'); s.set_attribute('k','v'); s.end(); print('OK')"` | OK（no-op 链路可用） |
| 4 | `uv run python -c "import agent_runtime.otel as o; t=o.get_otel_tracer(); c=t.start_as_current_span('q'); c.__enter__(); c.set_attribute('k','v'); c.__exit__(None,None,None); print('OK')"` | OK（agent_server 手动 CM 用法兼容，二审修订新增） |

### 5.2 架构验收

- `rg "_NoOpTracer|_NoOpSpan" packages/` 仅命中 `agent_core/tracing.py`（单一实现）；
- `uv run ruff check packages/agent-runtime/ packages/agent-core/` 0 error。

## 6. 回滚策略

单文件删减 + 1 个公开工厂，`git revert` 单 commit 回滚，无接口变更、无数据迁移。

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 下游未来使用 `add_event` | 低 | AttributeError | 全仓现状零调用；若后续需要，在 core `_NoOpSpan` 补该方法（集中实现反而在正确位置） |
| OTel SDK 可用时行为差异 | 无 | — | 本次只动 no-op 降级路径，SDK 启用路径（init_otel :90-131）不变 |
| 双 init 状态混乱 | 现状已有 | — | 范围外声明（§4.3），不因本次改动恶化 |

## 8. 工作量估计

约 15 分钟编码 + 测试验证（core +5 行工厂 +3 行 CM 转发，otel.py -30 行 +1 行 import +4 处替换）。
