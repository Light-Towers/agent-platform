# 自研 Runtime 分析 · 概览

> 完整报告见 `docs/runtime-self-build-analysis.md`。

## 一句话结论
本项目自研 Runtime（零依赖 `agent-core` + 执行治理 `agent-runtime`）是**受监管 + 厂商中立 + 多部署收敛**语境下的正确选择，不应推翻；优化重心在"核心握在手里、商品化能力借力成熟生态"。

## 自研五大动机
1. **厂商中立**：`agent-core` 零依赖，内核不 import langgraph/宿主；任何编排框架可作 `Planner` 策略挂入。
2. **可控失败模式**：retry/超时/熔断/取消归属显式划清（Plan-F R0），针对懒加载竞态、降级不复位、会话劫持逐一设防。
3. **合规脱敏**：准入不存问题全文、OTel 仅记长度+哈希、会话按密钥派生、跨用户回退禁止。
4. **零依赖 + 零配置**：纯 stdlib 内核，攻击面小、冷启快、`DATABASE_URL=` 空即跑。
5. **多部署收敛**：Plan-F 把双轨编排收敛为"单 Runtime + 多 Planner"。

## 业界现状（2026）
- 开源七强：LangGraph / CrewAI / AutoGen(维护) / OpenAI SDK / Google ADK / MS Agent Framework / Claude SDK。
- 云原生三强：AWS Bedrock AgentCore / Azure AI Foundry / Vertex AI Agent Builder。
- 共识：**框架重要性低于其上层的训练/沙箱/可观测**；多数是 workflow+agent 混合体。

## 对比要点
| 维度 | 自研 | 开源框架 | 云托管 |
|------|------|---------|--------|
| 可控性/合规 | ★★★★★ | ★★★ | ★★★★(黑盒) |
| 开发/维护成本 | 高 | 中 | 低 |
| 性能 | 优 | 良 | 中(弹性优) |
| 厂商中立 | ★★★★★ | ★★★★ | ★ |

## 三条行动建议
1. **保持自研核心**，强化"Runtime 不变、引擎可换"（已具备，试点用 ADK/OpenAI SDK 实现某 Planner）。
2. **商品化能力借力**：可观测接 Langfuse/OTel Collector；跨进程接 A2A/MCP；多副本协调接 Redis/Temporal。
3. **清理代码债**：`CircuitBreaker` 重复赋值、`_LegacyCircuitBreaker` 兼容层、`Plan.notes` 迁移债、`uv sync` 环境脆弱。

## 反模式
- ❌ 推翻自研全面迁框架（丢 PII/中立核心资产）
- ❌ 简单场景引入完整 Runtime
- ❌ 自研可观测/跨进程协议轮子
