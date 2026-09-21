# 00 — 客观清点（S0）

> 纯只读命令产出，四张表。

## 1. workspace 成员表

| # | 路径 | 包名 | build | requires-python | workspace 内依赖 | .py 文件数 |
|---|------|------|-------|----------------|-----------------|-----------|
| 0 | applications/agent_server | agent_server | hatchling | >=3.11 | agent-core, shared-schemas, agent-runtime | ~40 |
| 1 | packages/agent-core | agent_core | hatchling | >=3.11 | 无（dependencies=[]） | ~60 |
| 2 | packages/shared-schemas | shared_schemas | hatchling | >=3.11 | 无 | ~6 |
| 3 | packages/agent-runtime | agent_runtime | hatchling | >=3.11 | agent-core, shared-schemas | ~50 |
| 4 | applications/agent_federation | agent-federation-app | hatchling | >=3.11 | agent-core, shared-schemas, agent-runtime | ~80 |
| 5 | applications/kefu-service | kefu_agent | hatchling | >=3.11 | agent-core[memory-embed-local], shared-schemas | ~10 |
| 6 | applications/wenda-data-agent | wenda_data_agent | hatchling | >=3.11 | agent-core, shared-schemas | ~15 |
| 7 | applications/zhanggui-zhiku | **app** | **setuptools** | >=3.11 | agent-core | ~110 |
| 8 | applications/dialogue-framework | dialogue_framework | hatchling | >=3.11 | agent-core, shared-schemas | ~30 |
| 9 | applications/exhibition-agent | exhibition_agent | hatchling | >=3.11 | agent-core | ~30%20 |

全仓 670 .py（git 跟踪）：packages/ 133 + applications/ 444 + tests/ 82 + eval/ 3 + scripts/ 8。

## 2. 门禁覆盖矩阵

```
make ci = lint + test + eval

lint:
  ruff check .          → 退出码 0（全仓零错误）
  scripts/lint_architecture.py

test0test（4 pytest session）:
  [1] uv run pytest -q                              → tests/(82) + packages/agent-core/tests/(19) = 101 文件
  [2] uv run pytest applications/agent_federation/tests/unit -q  → 15 文件
  [3] uv run pytest applications/kefu-service/tests -q           → 1 文件
  [4] uv run pytest applications/exhibition-agent/tests -q       → 12 文件
  门禁内总计：129 文件

eval:
  eval/run_eval.py --fail-below 0.8

CI workflow（.github/workflows/agent-platform-ci.yml）:
  job ci  → make install + make ci
  job ha  → PostgreSQL + pytest tests/ha -m requires_pg + ha_real_kill_verify.py
```

### 门禁盲区（--collect-only 实测确认）

| 目录 | .py 文件数 | --collect-only 实测 | 严重度 |
|------|-----------|-------------------|--------|
| packages/agent-runtime/tests/ | 12 | **62 tests collected** ✓ | P1 |
| applications/zhanggui-zhiku/tests/ | 23 | **223 tests collected** ✓ | P1 |
| applications/agent_federation/tests/（根级） | 2 | 含在 19 文件中 | P2 |
| applications/dialogue-framework/tests/ | 1 | — | P2 |

门禁外总计：40 文件 / 285 实际测试（62 + 223）。

**packages/agent-runtime/tests/ 是否被执行？否。** Makefile L25-29 四 session 未引用，根 pyproject.toml L62-65 testpaths 未包含。`--collect-only` 实测确认 62 tests 可收集但不在 CI 内。

## 3. 陈旧目录清单

`git status --porcelain -uall` + `find <dir> -name "*.py"` 确认：

| 目录 | .py 文件数 | git 跟踪文件数 | 判定 |
|------|-----------|--------------|------|
| app/ | 0 | 0 | 残留残骸 |
| agent_federation/ | 0 | 0 | 残留残骸 |
| agent-core/ | 0 | 0 | 残留残骸 |
' | 0 | 0 | 残留残骸 |
| kefu-service/ | 0 | 0 | 残留残骸 |
| shared-schemas/ | 0 | 0 | 残留残骸 |
| wenda-adapter/ | 0 | 0 | 残留残骸 |
| wenda-data-agent/ | 0 | 0 | 残留残骸 |
| zhanggui-zhiku/ | 0 | 0 | 残留残骸 |

9 个目录全部 `py_files=0, git_tracked=0`，仅含 __pycache__/.ruff_cache/egg-info 残留。

exhibition-agent：**已 commit**（d0c3800），44 跟踪文件，非未跟踪新工程。

## 4. 量化指标

### 4.1 复杂度（ruff --select C901,PLR0913,PLR0915 --statistics）

| 规则 | 数量 | 含义 |
|------|------|------|
| PLR0913 | 48 | too-many-arguments |
| C901 | 29 | complex-structure（圈复杂度） |
| PLR0915 | 14 | too-many-statements |
| **合计** | **91** | — |

### 4.2 import 边（workspace 内部依赖）

```
agent-core      ← (零依赖，底层)
shared-schemas  ← (仅 pydantic，底层)
agent-runtime   ← agent-core, shared-schemas
agent_server    ← agent-core, shared-schemas, agent-runtime
agent_federation← agent-core, shared-schemas, agent-runtime
kefu-service    ← agent-core[memory-embed-local], shared-schemas
wenda-data-agent← agent-core, shared-schemas
dialogue-framework← agent-core, shared-schemas
zhanggui-zhiku  ← agent-core
exhibition-agent← agent-core
```

agent-runtime 仅被 agent_server + agent_federation 消费；5 个应用不依赖 agent-runtime。

### 4.3 重复符号矩阵

| 符号 | 出现位置 | 层数 | 判定 |
|------|---------|------|------|
| `class CircuitBreaker` | agent-core/resilience.py:408, agent-runtime/circuit_breaker.py:21, agent_federation/circuit_breaker.py:45 | 3 | agent-runtime 继承 agent-core（合规），agent_federation 独立（违规） |
| `class _NoOpTracer` | agent-core/tracing.py:137, agent-runtime/otel.py:57 | 2 | 独立实现，接口不一致 |
| `class Planner` | agent-runtime/planner/protocol.py:561, agent-runtime/admission_gateway.py:50 | 2 | ABC vs Protocol，同包不同上下文 |

### 4.4 TODO/FIXME/Deprecation 清点

| 类型 | 数量 | 位置 |
|------|------|------|
| TODO | 1 | agent-runtime/mcp_client.py:211（MVP 桩） |
| FIXME | 0 | — |
| DeprecationWarning | 7 | agent-core/config.py:106（env 旧名）+ events.py:92（LegacyStreamSink）+ test_config.py:58 |
| **合计** | **8** | — |

（plan 预期~35 处，实际 8 处，预期偏高。）
