# 先验素材采信表

> R3 定义的 A/B/C 三级分级 + 路径映射规则。

## A 级（背景直接引用）

1. `ARCHITECTURE.md §4`（:79-85）— 五条红线，D审计判据源
  - 红线 1：Package 互不可反向依赖
  - 红线 2：Application 不得互相 import 内部模块
  - 红线 3：agent-core 内核零宿主依赖
  - 红线 4：禁止再造 Runtime
  - 红线 5：跨进程通信必须走 shared-schemas

2. `AGENTS.md` — 术语/门禁/禁止行为
  - 禁止行为：重构必须先出方案
  - zhanggui-zhiku 包名仍为 app（@ 警告

## B 级（结论可用、路径需翻译、逐条复验）

| 文档 | 登记编号 | 路径映射 | 复验状态 |
|------|---------|---------|---------|
| docs/tech-debt/tech-debt-hardcoded-logic.md | TD-0~14 | kefu-service/ → applications/kefu-service/ 等 | 5 条抽查确认 |
| docs/architecture/architecture-improvement-plan.md | TB-1~14, U-1 | app/ → applications/agent_server/ 等 | 5 条抽查确认 |
| docs/operations/runtime-governance-roadmap.md | P2-P5 | 顶部自警示"部分过时" | P4-1 实测确认已落地 |
| CHANGELOG.md 前 3 节 | WS-1~8, Runtime 闭环 | — | 测试数标 UNVERIFIED |
| docs/handoff-2026-08-21.md | — | — | 未深入引用 |

## C 级（仅历史登记，禁作当前状态）

| 文档 | 说明 |
|------|------|
| CODE_REVIEW_CHECKLIST.md | 2026-08-15，全篇旧路径 |
| README.md「已知待拍板项」 | 部分已闭环，不作当前状态依据 |

## 路径映射规则（R2 第 3 条）

| 旧路径 | 新路径 | 生效日期(日期 |
|--------|--------|--------|
| app/ | applications/agent_server/ | 2026-08-19 |
| deepagents/ | applications/agent_federation/ | 2026-08-19 |
| agent-core/ | packages/agent-core/ | 2026-08-19 |
| shared-schemas/ | packages/shared-schemas/ | 2026-08-19 |
| kefu-service/ | applications/kefu-service/ | 2026-08-19 |
| 其余应用 | applications/ 下同名 | 2026-08-19 |
| docs/<X>.md（平铺） | docs/{architecture\|plans\|operations\|tech-debt\|research\|adr\|ha}/ | 2026-08-20 |

## 采信原则

- A 级：直接引用作判据，不标 UNVERIFIED
- B 级：结论可用但每条需逐条复验，✅ 状态不照抄
- C 级：仅作历史参考，不作为当前状态依据
- 所有测试通过数（如 541 passed）未经本次实跑 → 一律标 UNVERIFIED + 附复现命令
