# 修复 `validate_config` 缺失（阻塞 agent-core 测试集收集）

## 背景
- `packages/agent-core/tests/test_resilience.py` 顶部 `from agent_core.resilience import ... validate_config` 导入失败 → 整个 agent-core 测试集无法收集，`make ci` 的 `packages/*/tests` 门禁实际为红。
- `agent_core/resilience.py` 模块 docstring（第 10 行）已将 `validate_config：轻量配置校验与默认值填充` 列为对外能力，但自提交 `426e251` 起从未实现（纯遗漏，非设计变更）。

## 目标
- 在 `agent_core.resilience.py` 实现 `validate_config`，使 `test_resilience.py` 全部 4 个 `validate_config` 用例通过，解除 agent-core 测试集收集阻塞。

## 影响面
- 仅新增一个纯函数（无依赖、无副作用），不影响既有 `retry/retry_async/timeout/CircuitBreaker` 行为。
- 修复后 `make ci` 中 `pytest packages/agent-core/tests` 恢复收集与执行。

## 契约（来自现有用例，不可偏离）
- 签名：`validate_config(data: dict, defaults=None, required=None, types=None) -> dict`
- 语义：
  1. 以 `defaults` 为底，`data` 覆盖（仅填充缺失键）→ 返回合并后的 dict。
  2. `required` 中任一键在合并结果中缺失 → 抛 `ValueError`（消息含「必填项」）。
  3. `types` 中任一键的值类型不符 `isinstance` → 抛 `TypeError`（消息含「类型错误」）。
- 用例断言：
  - `validate_config({"a":1}, defaults={"b":2}) == {"a":1,"b":2}`
  - `validate_config({}, required=["api_key"])` → `ValueError` "必填项"
  - `validate_config({"port":"abc"}, types={"port":int})` → `TypeError` "类型错误"
  - `validate_config({"host":"localhost","port":8080}, required=[...], types={...}) == {"host":"localhost","port":8080}`

## 迁移策略
- 单文件新增函数，置于 `timeout` 之后、`CircuitBreaker` 段之前，与 docstring 顺序一致。
- 不改动任何其他代码；不新增公开符号（除 `validate_config` 本身）。

## 验收标准
- `pytest packages/agent-core/tests/test_resilience.py` → 全绿（含 4 个 validate_config 用例）。
- `pytest packages/agent-core/tests` → 全量收集且通过（解除导入阻塞）。
- `ruff check .` 仍通过；`pytest tests/`（根）无回归。

---

## 附带修复：`resolved_state()` 误突变内部状态（同文件隐藏缺陷）

修复 `validate_config` 导入后，`test_resilience.py` 恢复收集，暴露第二个预存失败
`test_breaker_resolved_state_readonly`：`resolved_state()` 实现中调用了
`self._policy.check_transition(self)`，而 `check_transition` 会在冷却到期后**把内部
`_state` 从 OPEN 改写为 HALF_OPEN**（副作用），破坏「只读投影」语义。用例断言
`resolved_state()` 返回 HALF_OPEN 后 `breaker.state` 仍应为 OPEN，故失败。

### 影响面
- 生产调用方 `agent_runtime/circuit_breaker.py:42`（`state` 属性只读映射）、
  `agent_core/llm/fallback.py:97`（状态判定）均只读取等效状态，本应是只读查询；
  原实现却在读取时顺带推进了内部状态，属于不正确行为（观测/健康探针会误翻转状态）。
- `allow()` 仍依赖 `check_transition` 做真正的状态转换，行为不变。

### 修复
- 在 `_Policy` 协议新增 `resolved_state(breaker) -> str`（只读投影）；
- `ConsecutiveFailurePolicy` / `SlidingWindowPolicy` 分别实现该只读投影
  （与各自 `check_transition` 的冷却判定一致，但只返回、不写 `_state`）；
- `CircuitBreaker.resolved_state()` 改为委托 `self._policy.resolved_state(self)`，去掉
  `check_transition` 调用，实现真正只读。

### 验收
- `test_breaker_resolved_state_readonly` 通过；`test_resilience.py` 29 passed；
  `packages/agent-core/tests` 198 passed；`packages/agent-runtime/tests` 62 passed；
  `ruff check .` 通过。
