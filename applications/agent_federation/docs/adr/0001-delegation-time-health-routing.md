# 子服务健康路由采用委派时过滤，而非重建 agent

## Status

accepted（2026-08-12，production-action-plan.md P3.1 评审定案）

## Context

production-action-plan.md P3.1 要求"`config.healthy` 接入路由，子服务宕机 30s 内自动降级"。但 P1.1 已把 `_main_agent` 提前到 lifespan 预初始化并全局缓存——若在 `_build_subagents()` 构造时过滤健康状态，过滤只在启动时生效一次，运行中宕机永不降级，验收标准不可达。

## Decision

健康过滤在**委派时（delegation-time）**生效：agent 构建时挂全部远程 subagent，在委派调用层（AsyncSubAgent wrapper / 熔断器同族）每次调用前读 `config.healthy`，不健康即走本地 fallback。配套后台探活回路（复用 `zhiku_tools.py` 探活模式）周期性 ping `/health`，驱动 `mark_unhealthy`/`mark_healthy`。

验收口径：**子服务宕机 → 30s 内被标记；下一次委派即走 fallback**（而非"路由表实时重建"）。

## Considered Options

- **健康状态变化时重建 agent 缓存**（否决）：重建瞬间的置脏竞态正是 P1.1 要消灭的懒加载竞态；子服务短暂抖动即触发整图重建（middleware/prompt/checkpointer 绑定），重试风暴下放大为性能事故；且与 P1.2 的 checkpointer lifespan 管理纠缠。
- **仅重启时生效**（否决）：达不到生产级降级要求。

## Consequences

- 委派层 wrapper 成为健康/熔断的统一决策点，与 `gateway/circuit_breaker.py` 的 per-call 模式一致（参照 gRPC/Envoy 客户端负载均衡的请求时剔除惯例）。
- agent 单例终身缓存的前提得以保持，P1.1 预初始化收益不被破坏。
- 探活回路成为新的后台常驻任务，需纳入 lifespan 生命周期管理。
