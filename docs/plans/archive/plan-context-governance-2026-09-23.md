# Plan: Context Governance — 信息层编译器

> 日期：2026-09-23
> 状态：已完成（2026-09-23）
> 前置：四类 Memory 架构 + 记忆闭环 + 9 项隐性问题修复 均已完成

## 1. 问题

Context 治理不是 Agent 的"辅助能力"，而是决定 Agent 能不能稳定做对事情的核心基础设施。
LLM 只能基于它当前看到的 Context 做决策——Context 污染会消耗模型能力（90 分模型 + 垃圾输入 → 60 分）。

核心问题不是 "More Context" 而是 "Right Context at the Right Time"。

## 2. 现状

已有（相当成熟）：
- ContextAssembler 五步管线（collect → rank → budget → compress → assemble）
- ContextBudget 动态预算 + 余量回流
- MemoryGate 去重 + 冲突消解 + 排序 + 预算内取 top-N
- ToolResultCompressor 外置 + 头尾截断
- compact_messages LLM 摘要压缩
- ContextManager（ConversationContext + TaskState + ExecutionState）
- MemoryRetriever + ContextSelector（四类 Memory 召回 + 按任务类型选择）
- SkillInvocationContext 嵌套 context slicing
- Skill 级权限过滤 + 脱敏

缺：
1. **Validate**：召回信息是否与当前 State 一致（跨来源一致性校验）
2. **Authorize**：Memory 级权限过滤（租户/用户隔离）
3. **Quality**：信息质量评分（相关性/新鲜度/冲突度）
4. **Governor**：统一编排管道（当前各组件零散，未被统一调度）

## 3. 架构

```
                    query + state + task_type + permissions
                              │
                    ┌─────────▼─────────┐
                    │  ContextGovernor  │
                    └─────────┬─────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    ContextSelector     MemoryRetriever     State (snapshot)
          │                   │                   │
          └───────────┬───────┘                   │
                      ▼                           │
                Collect candidates                │
                      │                           │
                      ▼                           │
                Validate ◄───────────────────────┘
                (与 State 一致性)
                      │
                      ▼
                Authorize
                (权限过滤)
                      │
                      ▼
                ContextAssembler
                (rank → budget → compress → assemble)
                      │
                      ▼
                Quality Score
                (相关性/新鲜度/冲突度)
                      │
                      ▼
                CompiledContext → LLM
```

## 4. 任务

| # | 任务 | 产出 | 状态 |
|---|------|------|------|
| 1 | ContextValidator | `context/validator.py`：跨来源一致性校验（召回信息 vs State） | ✅ |
| 2 | ContextAuthorizer | `context/authorizer.py`：Memory 级权限过滤（租户/用户隔离） | ✅ |
| 3 | ContextQualityScorer | `context/quality.py`：信息质量评分（相关性/新鲜度/冲突度） | ✅ |
| 4 | ContextGovernor | `context/governor.py`：统一编排管道 | ✅ |
| 5 | 测试 + lint + 全量回归 | `test_context_governance.py`（28 passed） | ✅ |

## 5. 约束

- 不破坏现有 ContextAssembler 接口（在其之上编排，不替换）
- 不自建权限系统（复用现有 Skill permissions + tenant 机制）
- 向后兼容：Governor 不可用时退化为直接调 Assembler
