# 架构边界建议：agent-core 与 dialogue-framework

> 调研日期：2026-08-15
> 范围：仅梳理职责边界，**未改动任何代码**。
> 结论：两者无实质性功能重复，依赖单向（DF → AC），无需合并；仅需统一两处接口冗余。

## 1. 依赖方向（已确认）

```
dialogue-framework  ──依赖──▶  agent-core
        │                          │
        └──依赖──▶ shared-schemas ─┘
```

- `dialogue-framework/pyproject.toml` 显式声明 `dependencies = ["agent-core", "shared-schemas"]`
  （`[tool.uv.sources]` 以 `editable` 本地安装）。
- 实际 import：`dialogue_framework` 多处 `from agent_core...`
  - `shared/llm/langchain_client.py` → `from agent_core.llm.fallback import FallbackChatModel`
  - `agent/graph/nodes/guard.py` → `from agent_core.sql.guard import validate_sql`
  - `agent/agent.py`、`api/server.py` → `agent_core.logging`
- 反向：**`agent-core` 绝不 import `dialogue-framework`**（内核层框架无关）。

## 2. 职责划分（清晰，无重叠）

| 能力 | agent-core（运行时内核，零硬依赖） | dialogue-framework（对话引擎） |
|------|-----------------------------------|-------------------------------|
| LLM client 封装 | `llm/providers.py` `BaseLLMProvider` / `fallback.py` `FallbackChatModel` / `registry.py` | `shared/llm/` **复用** `FallbackChatModel` + 自有 `BaseChatClient` 协议 |
| tracing | `tracing.py` `init_tracing`/`start_span`/`traced_span`（OTel 懒导入） | 无自实现，复用 `agent_core.logging` |
| guardrails | `guardrails/` auth·ratelimit·web；`sql/guard.py` `validate_sql` | 无自实现，`guard.py` 节点**复用** `validate_sql` + 加敏感词过滤 |
| memory | `memory/base.py` `ConversationMemory`（消息级记忆协议） | `core/tracker.py` `Tracker`（对话状态机，引擎级，接口不同） |
| 配置 | 无（由宿主注入，刻意零依赖） | `shared/config.py` `Settings` 继承 `shared-schemas` 的 `BaseLLMSettings` |
| tool registry | `tools/registry.py` `ToolRegistry` + `guarded.py` + `adapters/mcp.py` | 无 |
| graph 编排 | 无 | `agent/graph/` LangGraph 5 节点编排（核心职责） |
| policies/retrieval/nlg/channels/training | 无 | 自有全套对话引擎设施 |

**结论**：DF 对内核能力一律复用 AC，未重写；AC 不含 graph 编排/Tracker 状态机，是 DF 独有。
两者是**内核 vs 上层引擎**的纵向分层，不是平行重复。

## 3. 待统一的接口冗余（低风险，建议登记待办）

仅两处"软重复"，不影响运行，建议后续迭代收敛：

1. **LLM 客户端协议并存**
   - `agent_core.llm.providers.BaseLLMProvider`（Protocol）
   - `dialogue_framework.shared.llm.base_client.BaseChatClient`（Protocol）
   - 二者方法签名不兼容、互不对接。建议以 `agent-core` 的协议为单一事实来源，DF 逐步对齐。

2. **会话状态/记忆抽象两套**
   - `agent_core.memory.ConversationMemory`（消息级：`save/get_recent/clear/update`）
   - `dialogue_framework.core.Tracker`（引擎级：slots/events/stack）
   - DF 当前未使用 AC 的 memory 协议。若未来要统一会话历史，需决策由谁主导（建议 AC 提供存储协议，DF 的 Tracker 适配之）。

## 4. 生态采纳度差异

- `agent_core`：被 `deepagents` / `zhanggui-zhiku` / `app` / `dialogue-framework` 等 5+ 包引用，是事实公共内核。
- `dialogue_framework`：**仅包内部自引用 + 自身测试**，全仓库无其他宿主直接 import。
  属"待推广的对内基础设施"，非废弃对象。

## 5. 行动建议

| 优先级 | 项 | 动作 | 是否改代码 |
|--------|----|------|-----------|
| 低 | 双 LLM 协议 | 以 `agent_core.llm.providers.BaseLLMProvider` 为准，DF 弃用 `BaseChatClient` | 后续迭代 |
| 低 | 双 memory 抽象 | AC 提供存储协议，DF `Tracker` 适配 | 后续迭代 |
| 无需 | 合并/拆分两包 | **不推荐**，边界已清晰，强行合并反而破坏内核零依赖约束 | 否 |
| 无需 | 删除 dialogue-framework | **不推荐**，其为合法上层引擎，仅暂未被其它包消费 | 否 |

## 6. 一句话结论

`agent-core` 是零依赖运行时内核，`dialogue-framework` 是其上层对话引擎，二者单向依赖、职责无重叠。
**无需架构调整**，仅登记两处协议冗余为后续技术债即可。
