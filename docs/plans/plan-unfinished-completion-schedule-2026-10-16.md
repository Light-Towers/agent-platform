# 排期：未完成计划的收口计划与截止完成日期（2026-10-16）

> 状态：**现行执行排期**（本文件只做「排期 + 已核实进度 + 需拍板清单」，不重复各 plan 的技术方案；技术方案仍以各 plan 为准）。
> 制定日期：2026-10-16 ｜ 分支：`chore/tech-debt-agentic-discovery-test-2026-10-15` ｜ **本批不部署**（夜间 126 关机）。
> 上游锚点：`plan-production-delivery-roadmap-2026-10-09.md`（计划窗口 **2026-10-09 ~ 2026-12-04**，合计 84 人/日，其中 **8 人/日「待环境」，按 roadmap 自身规则不可承诺日期**）。
> 口径纪律：本文所有「已完成」均以**代码 + 测试实跑**为据（逐条附提交号），不以文档状态行、不以复选框、不以口头汇总为据。

## 0. 截止完成日期（先给结论）

| 层 | 截止日 | 内容 | 可否承诺 |
|---|---|---|---|
| **阶段 0 收口** | **2026-10-16**（今天，即 roadmap 原定窗口末日） | 待办清单与代码对齐、逐条补证据 | ✅ 可 |
| **阶段 1 平台收口（本排期主目标）** | **2026-10-30** | 下文 §2 表中「我可独立执行」各行 | ✅ 可（不含待环境行） |
| 阶段 2 / 阶段 3 | 11-13 / **12-04** | 归 roadmap，不由本排期重排 | 部分待环境 |
| 一期交付判定 | **2026-12-04** | roadmap §四 七条标准逐条判定 | — |

**一句话**：本轮排期的截止完成日期 = **2026-10-30**（对齐 roadmap 阶段 1 窗口），整体交付分界仍是 **12-04**；凡依赖 126 真库 / PR / CI / CodeQL 重扫者，**只登记不承诺日期**。

## 1. 已核实完成（证据，非账面）

| roadmap 行 | 判据 | 实测状态 | 证据 |
|---|---|---|---|
| 阶段1 #5「4 个模块主流程未调用」 | 每模块有测试与独立提交 | **4/4 已接线**（state_migration / execution_recovery / payload_externalization / human_task） | `c49ee2dd` `4a7c662e` `6bf15287`；`packages/agent-runtime/tests/test_human_task_wiring.py`(5) + `applications/agent_server/tests/test_human_task_api.py`(12) |
| 阶段1 #4（代码面子项）防覆盖 fence | 保护覆盖 5/5 | **代码面 5/5**；真库拒绝用例仍待环境 | `68a44290`；`packages/agent-runtime/tests/test_receipt_generation_fencing.py` |
| 阶段1 #6 健康检查报四部件 | 开关跟随断言 | 已完成（`18b6954`）+ 残差补强已做 | `d31f247e`（`cost_governance`/`forensic`「输入变则值必变」） |
| P0-4 桶 A（盲捕获安全窄化） | §3 逐站点核对 | **8 站点全部已落地**（此前该 plan 自记「不作结论，需逐个核对」，本批已核对） | `milvus_utils.py:68` `(ValueError, TypeError)`；`node_pdf_to_md.py:134/156/239/339`；`benchmark/locustfile.py:46` `(OSError, ValueError)`；`tests/unit/test_tracing.py:35/41` + `test_security_guards.py:47` `ImportError` |
| T2.2 item5 | 行为等价 + 零回归 | 已落地 | `b35f35a`；federation **176 passed** |
| T2.3（8 项依赖配置） | 逐项对码 | 已重新对码 + 2 项本批落地 | `af2f980`；exhibition **357 passed** |
| 阶段0 文档状态行 | 每条状态有代码/测试依据 | 7 篇漂移状态行已订正 | `06c1b1b` `c05ba0a` `1640f38` `d08a751` `a5eacd4` `75fdabe` |

> **订正一条我上一轮的错判**：P0-4 与 tech-debt T2.2/T2.3 曾被我为「待拍板 / 高风险」而整体归为不可推进。实读后：P0-4 **2026-09-24 已由用户逐站核查批准**（范围=桶 A），T2.3 的多数项是包改名导致的 moot 而非决策悬置。⇒ 教训：判「受阻」前须读方案本体，不能只看状态行或凭印象。

## 2. 剩余工作排期（10/17 → 10/30）

| 日期 | 项 | 来源 | 影响面 | 验收判据 | 归属 |
|---|---|---|---|---|---|
| 10/17–10/18 | **#5 残口：订正 `execution_recovery.py:11` 陈旧 docstring**（仍写「payload_externalization / human_task 仍未接线」，与本批代码矛盾），并加「禁止再退化为孤岛」的装配面自动检查 | roadmap #5 判据「全仓未接线标注归零」 | 仅 docstring + 1 个门禁测试 | 该模块 docstring 不再声称未接线；`test_v3_wiring_assembly.py` 增断言且红→绿 | 我可独立执行 |
| 10/18 | **#D7 桶 A 记账闭合 + 残余定性**：本批实测 `git grep 'noqa: BLE001'` = **37 处**（集中在 `knowledge-service/eval/*.py`、`agent_server/main.py:131`），与 P0-4 §5 硬判据「=0」不符 ⇒ 逐处判定「属 M2 已放弃的逐点 noqa（应迁入整包基线）」还是「桶 C 承重点（应保留）」并写结论 | P0-4 §5 / TODO D7 | 只动 pyproject 基线 + 注释 | `ruff check .` 全绿；§5 判据被逐处定性（不粉饰为 0） | 我可独立执行 |
| 10/19–10/21 | **#10 数据可信度默认值改「待确认」**：无标注响应不得按「完整可信」输出；缺标注则拒绝接入 | roadmap #10 | exhibition 侧 `data_readiness` 消费链 | 造一条无标注响应 ⇒ 输出显示「待确认」（新增用例） | 我可独立执行 |
| 10/22–10/27 | **#7 对外数据格式补健康检查字段与界面所需结构**（**先做消费方影响评估**，不得静默改下游解析形状） | roadmap #7 | shared-schemas / 下游前端与网关 | 跨服务一致性测试 + 打分测试均不破坏下游 | 我可独立执行（评估结论如需改契约⇒转拍板） |
| 10/22–10/27 | **#4 重复实现去重复核**：roadmap 记「同名任务回执存储有两份实现、接线用的是无保护那份」。本批 `git grep 'class .*Receipt.*Store'` **未命中**⇒ 疑已合并；须以实读确认「同名实现只剩一处」是否成立 | roadmap #4 判据 | 若仍在则删重复一份 | 判据「同名实现只剩一处」有实读证据 | 我可独立执行 |
| 10/28–10/30 | **阶段 1 收口对账**：逐条按 roadmap「怎么算改好」列复核 + 全量门禁（`ruff check .` / `check_doc_sync.py` / 相关 pytest session） | roadmap 阶段1 | 文档 | 每行有代码或测试依据；待环境行明确标注「标准环境已验证 / 多物理机待环境」 | 我可独立执行 |
| — | **待环境（只登记，不承诺日期）** | #4 真库两类拒绝用例、#8 KS 15 条报错根因 + 图谱重测、V3 双实例物理故障转移、CodeQL B7b-4/5 重扫、env-var 126 部署脚本同步 | 需 126/PR/CI | roadmap §四第 2 条规则 | 环境解锁后 |

## 3. 需要用户拍板（**请在 10/20 前给方向，否则将阻塞 §2 后半**）

红线「所有代码优化/重构必须先制定方案」+ 我不替你做设计决策。以下 5 项方案已就绪，卡在「选哪条路」而非「有没有路」：

1. `plan-audit-operator-principal-2026-10-03.md` — 审计主体改造是否开工（现：方案已写、零代码）
2. `plan-m11-exception-classification.md` — 状态 `Proposed`，接受 / 修改后再施工
3. `plan-router-keyword-gate-hides-corpus-2026-10-12.md` — 修法三选一
4. `plan-v3-phase-2-4-integration-2026-09-23.md` — v2 方案（含 6 项不变量）确认后施工
5. tech-debt 补充 4 — agentic bridge 默认开 vs 保留 opt-in 但补开启路径测试

## 4. 迁移策略（本排期如何推进，不破坏可回退性）

1. **单分支串行**：全部落在 `chore/tech-debt-agentic-discovery-test-2026-10-15`，一步一提交（共享工作区有并行会话代为提交的风险，动 `docs/` 前先重取 `git log`/`git status`）。
2. **不部署**：任何需 126 的验证一律标「待环境」，**不得写成已验收**；`scheduler_enabled` 等默认关的生效面，接线 ≠ 启用。
3. **每步门禁**：`uv run --with ruff ruff check .` + `uv run python scripts/check_doc_sync.py` + 受影响 session 的 `uv run pytest`（Windows 本机无 `make`）。
4. **红线不破**：禁止删用例 / 收窄断言 / 放宽前置条件凑绿；依赖方向 `application → agent-runtime → agent-core` 单向；审计主体服务端断言、不接受请求体自报。
5. **文档回写**：只改状态列；翻复选框前先声明该文件既有计数口径，按**相对口径**记 ± 并留可核命令。

## 5. 验收标准（本排期何时算「做完」）

- §2 各行按其「验收判据」列逐条有**实跑证据**（提交号 + 测试通过数），而非状态行自称完成。
- `ruff check .` 全绿、`check_doc_sync.py` 0 警告、受影响 pytest session 全绿。
- roadmap 阶段 1 每行要么达标并附证据，要么明确标注「待环境 / 待拍板」；**不出现「已上线 / 已支持几十个业务系统接入」这类未达声明**。
- §3 的 5 项拍板结果写入对应 plan；未拍板者保持开项，不强行闭合。
