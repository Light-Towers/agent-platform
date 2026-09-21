# 修复方案：F-S1-03 — agent-core.memory 模块级硬依赖 langgraph 惰性导入改造

> 日期：2026-09-21
> 严重度：**P0**（红线 3 违规 / 生产安全）
> 来源：[S2 债务诊断](../analysis/2026-09-21/02-debt-diagnosis.md) §3 P0
> 状态：**方案待确认**（未动代码）

## 1. 目标

恢复 agent-core 红线 3「内核零宿主依赖」铁律：在无 langgraph / langchain_core 环境下 `import agent_core.memory` 不报 ImportError。

## 2. 问题分析

### 2.1 当前状态

```
import agent_core.memory
  → __init__.py:34  from agent_core.memory.mongo_checkpointer import MongoCheckpointer
    → mongo_checkpointer.py:24  from langgraph.checkpoint.base import BaseCheckpointSaver, ...
    → mongo_checkpointer.py:31  from langchain_core.runnables import RunnableConfig
      → ImportError（无 langgraph 环境）
```

### 2.2 根因

`memory/__init__.py:34` 以**模块级** import 引入 `MongoCheckpointer`，导致 `import agent_core.memory` 必然触发 `mongo_checkpointer.py` 加载，而后者模块级依赖 langgraph + langchain_core。

`mongo_checkpointer.py` docstring（:11）声称"导入时懒加载，缺包时给出明确错误"，但 langgraph/langchain_core 实为模块级 import，文档与代码不一致。

### 2.3 为什么不能只改 mongo_checkpointer.py

`MongoCheckpointer` 继承 `BaseCheckpointSaver[str]`（:62），基类在类定义时必须可用，无法将 langgraph import 移入函数内或 `TYPE_CHECKING` 块。因此 `mongo_checkpointer.py` 本身必须保留模块级 langgraph import——它是**可选模块**，只有需要 Mongo checkpointer 时才应被加载。

真正的修复点是 `__init__.py`：不应在模块级 import 这个可选模块。

## 3. 影响面

### 3.1 直接影响（改动文件）

| 文件 | 改动 |
|------|------|
| `packages/agent-core/agent_core/memory/__init__.py` | 删除 :34 模块级 import；添加 `__getattr__` 惰性入口；`get_checkpointer` 内改为函数内 import |

`mongo_checkpointer.py` **不改**——它本身就是可选模块，需要 langgraph 才能用，符合 extra + 惰性入口模式。

### 3.2 调用方影响（不改但需验证）

| 调用点 | 引用方式 | 影响 |
|--------|---------|------|
| `tests/test_memory_backend.py:9` | `import agent_core.memory as mem_pkg` | **正面**：不再因缺 langgraph 失败 |
| `tests/test_checkpointer.py:41` | `from agent_core.memory import MongoCheckpointer` | 通过 `__getattr__` 惰性加载，行为不变 |
| `tests/test_mongo_checkpointer_async.py:75,181` | `from agent_core.memory.mongo_checkpointer import MongoCheckpointer` | 不受影响（直接 import 子模块） |
| `agent_server/main.py:54` | `from agent_core.memory import get_checkpointer` | 不受影响（不 import MongoCheckpointer） |
| `agent_federation/agent/main_agent.py:61` | `from agent_core.memory import get_checkpointer` | 不受影响 |
| `agent_federation/agent/memory/semantic_memory.py:28` | `from agent_core.memory import (...)` | 不受影响（不 import MongoCheckpointer） |

### 3.3 不受影响的理由

`get_checkpointer` 函数内只有在 `MONGO_URL` 配置时才实例化 `MongoCheckpointer`（:94），改为函数内 import 后：
- 无 MONGO_URL → 走 InMemorySaver 路径，不触发 langgraph
- 有 MONGO_URL → 函数内 import MongoCheckpointer，触发 langgraph（此时环境必然已装 langgraph，因为用户主动配置了 Mongo 持久化）

## 4. 迁移策略

### 4.1 改动 1：删除模块级 import

```python
# __init__.py:34 删除此行
from agent_core.memory.mongo_checkpointer import MongoCheckpointer
```

### 4.2 改动 2：添加 `__getattr__` 惰性入口

在 `__init__.py` 末尾（`__all__` 之前）添加：

```python
def __getattr__(name: str):
    """惰性加载 MongoCheckpointer——避免 import agent_core.memory 硬依赖 langgraph。

    MongoCheckpointer 需要 langgraph + langchain_core 作为基类，仅在显式访问时才加载。
    """
    if name == "MongoCheckpointer":
        from agent_core.memory.mongo_checkpointer import MongoCheckpointer as _MC

        return _MC
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### 4.3 改动 3：`get_checkpointer` 内改为函数内 import

```python
# __init__.py:94 当前
return MongoCheckpointer(
    mongo_url=mongo_url,
    ...
)

# 改为
from agent_core.memory.mongo_checkpointer import MongoCheckpointer as _MC

return _MC(
    mongo_url=mongo_url,
    ...
)
```

### 4.4 `__all__` 保留 `MongoCheckpointer`

`__all__` 列表保留 `"MongoCheckpointer"`（:123），`__getattr__` 会处理惰性加载。这保证 `from agent_core.memory import MongoCheckpointer` 仍可工作。

### 4.5 不改 `mongo_checkpointer.py`

该模块的 langgraph/langchain_core 模块级 import 保留——它是可选模块，只有显式 import 时才加载，符合 extra + 惰性入口设计模式。

## 5. 验收标准

### 5.1 功能验收

| # | 命令 | 预期 |
|---|------|------|
| 1 | `python -c "import agent_core.memory"` | 成功（无 langgraph 环境下），且 `sys.modules` 无 langgraph / langchain_core / mongo_checkpointer |
| 2 | `python -c "from agent_core.memory import get_checkpointer; get_checkpointer()"` | **（2026-09-21 二审修订）** 本命令要求环境**已装 langgraph**——无 MONGO_URL 时的降级路径本身（`from langgraph.checkpoint.memory import InMemorySaver`）仍需 langgraph，故预期"返回 InMemorySaver"仅在已装 langgraph 时成立。原表述"无 langgraph 环境下返回 InMemorySaver"不成立，已更正 |
| 3 | `python -c "from agent_core.memory import MongoCheckpointer; print(MongoCheckpointer)"` | 成功（有 langgraph 环境下） |
| 4 | `uv run pytest packages/agent-core/tests -q` | 全部通过（含 AST 防复发守卫 + 子进程 sys.modules 断言） |

### 5.2 架构验收

- `ruff check packages/agent-core/` 0 error
- `python -c "import agent_core.memory"` 不触发 `langgraph` / `langchain_core` 的任何 import（可用 `python -v` 或 `sys.modules` 检查）

### 5.3 回归验收

- `uv run pytest tests -q`（根测试套件）
- `uv run pytest applications/agent_federation/tests/unit -q`

## 6. 回滚策略

改动仅涉及 `__init__.py` 单文件 3 处（删 1 行 import + 加 `__getattr__` 函数 + 改 1 处函数内 import）。如出问题，`git revert` 单 commit 即可回滚，无数据迁移、无接口变更。

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `__getattr__` 与某些静态分析工具不兼容 | 低 | IDE 跳转可能失效 | `__all__` 已声明，type checker 可识别 |
| 下游显式 `from agent_core.memory import MongoCheckpointer` 在无 langgraph 环境下失败 | 低 | 仅 test_checkpointer.py:41 一处 | 该测试本就需要 langgraph（:15 `from langgraph.checkpoint.memory import InMemorySaver`），非新增风险 |
| `dir(agent_core.memory)` 不含 `MongoCheckpointer` | 低 | 极少数反射场景 | `__all__` 已声明，`__getattr__` 会响应 |

## 8. 工作量估计

单文件 3 处改动，约 15 分钟编码 + 测试验证。
