# Spike 报告：TodoListMiddleware 默认栈挂载验证

> 日期：2026-08-11
> 方法：pip install deepagents==0.7.5 + 源码级阅读 `graph.py:create_deep_agent`
> 目标（D12）：确认 0.7.5 默认栈是否已挂载 TodoListMiddleware，决定 Phase 4 是"启用"还是"调参"

---

## 结论

**TodoListMiddleware 未挂载在 deepagents 0.7.5 默认栈中。Phase 4 需显式传入。**

---

## 证据

### 1. 默认中间件栈（`graph.py:817-893`）

`create_deep_agent` 构建的默认栈（按顺序）：

| # | 中间件 | 条件 | 来源 |
|---|--------|------|------|
| 1 | `SkillsMiddleware` | `skills is not None` | deepagents |
| 2 | `FilesystemMiddleware` | 无条件 | deepagents |
| 3 | `SubAgentMiddleware` | 有 inline_subagents | deepagents |
| 4 | `SummarizationMiddleware` | 无条件 | deepagents（`create_summarization_middleware`） |
| 5 | `PatchToolCallsMiddleware` | 无条件 | deepagents |
| 6 | `AsyncSubAgentMiddleware` | 有 async_subagents | deepagents |
| — | *用户 middleware 插入点* | — | — |
| 7 | profile `extra_middleware` | profile 有 | deepagents |
| 8 | PromptCachingMiddleware | 无条件 | langchain_anthropic 等 |
| 9 | `MemoryMiddleware` | `memory is not None` | deepagents |
| 10 | `HumanInTheLoopMiddleware` | `interrupt_on is not None` | langchain |
| 11 | `_ToolExclusionMiddleware` | profile 有 excluded_tools | deepagents |

**TodoListMiddleware 不在上述任何位置。**

### 2. 全文件搜索

`graph.py` 全文 944 行，`TodoListMiddleware` 仅出现 1 次（第 634 行注释）：

```python
# `TodoListMiddleware` is from langchain and
# defaults to its full prompt, so it is the one middleware passed
# `system_prompt=""` here to trim it.
```

这是注释，说明 deepagents 对用户传入的 TodoListMiddleware 有 prompt 修剪处理，但**不会自动挂载**。

### 3. `__init__.py` 导出列表

`deepagents/__init__.py` 的 `__all__` 不含 `TodoListMiddleware`，不直接导出。

### 4. 导入路径

```python
from langchain.agents.middleware import TodoListMiddleware
```

来自 langchain（非 deepagents 自有），`__init__(self, *, system_prompt, tool_description)`，提供 `write_todos` 工具。

---

## Phase 4 行动项

1. **显式传入**：`create_deep_agent(middleware=[TodoListMiddleware(...)])`
2. **prompt 修剪**：deepagents 注释说会传 `system_prompt=""` 修剪 TodoListMiddleware 的默认 prompt，实际行为需在 Phase 4 集成时验证
3. **与 RubricMiddleware 共存**：两者都通过 `middleware=[...]` 传入，无冲突
4. **不影响现有栈**：显式传入会插入到用户 middleware 位置（核心栈之后、tail 之前），不替换任何默认中间件

---

## 环境信息

- deepagents==0.7.5
- langchain==1.3.14
- langgraph==1.2.10
- Python 3.11（miniconda3）
- 验证方式：`inspect.getsource(deepagents.graph)` + 逐行阅读 `create_deep_agent` 实现
