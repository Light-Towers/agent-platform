# PR #79 处置（dependabot minor-and-patch 组，甲档口径复刻）

- 日期：2026-10-19
- 对象：dependabot PR #79（minor-and-patch 组 15 项更新，`ci` FAILURE）
- 先例：`docs/plans/plan-pr55-disposition-2026-10-04.md`（2026-10-04 用户拍板**甲档**：关 dependabot PR + 自建「lock-only + 仅可抬项」PR，#55→#71 流程）
- 本文件只记**与先例的差异**，不重复先例论证。

## 0. 复发与结构性修法（2026-10-19 追加，#84 同签名复发后）

**#79 关掉后 dependabot 当周即重开 #84（17 项），ci 再次 L-4 红，签名逐字同病**：根因不是"哪一项该抬"，而是 **dependabot 的 uv workspace 组只抬根 manifest 的下界**——实测 #84 的 diff 覆盖全部 9 个 pyproject.toml，但 otel trio 的下界只在 `pyproject.toml [otel]` 被抬到 `>=1.45.1`，`packages/agent-core/pyproject.toml [tracing]` 仍是 `>=1.24` ⇒ L-4（多处下界必须一致）**每次刷新必红**，手工处置只是治症。

**结构性修法（本批落地）**：`.github/dependabot.yml` 对 otel trio 设 `ignore`（minor+patch；major 仍单独出 PR 必然人工全审）。理由链：① 自动组无法做到"抬全部声明位"（这是 L-4 的存在前提）；② OTel 版本归一由 L-4 门禁 + 人工按方案抬（同一 PR 内抬全部声明位 + lock）管理，安全更新若重要走人工 lock-only PR；③ 与 2026-10-05「不新增 Dependabot alerts 门禁」的知情接受同族——**依赖告警的被动性已拍板接受，此处只是把同一取舍前移到更新提议面**。**改判入口**：若 dependabot 未来支持 workspace 级一致 bump（或改用一个 manifest 声明位），删 ignore 恢复自动流。

**#84 处置（同甲档）**：关 #84；自建 lock-only PR 精确复刻其 14 项非 otel 更新（含 #79 之后新增的 pydantic-settings 2.16.0 与 langgraph-checkpoint-postgres 3.2.0 两个 minor），otel trio 保 1.45.0。

## 1. 失败根因（与 #55 同一条 L-4）

`ci` 日志实取（run `38547229605`）：`'opentelemetry-api' 下界不一致（pyproject.toml[otel]: >=1.45.1 vs packages/agent-core/pyproject.toml[tracing]: >=1.24）`。

#79 把 otel trio（api/sdk/exporter-otlp 1.45.0→1.45.1）连同根 pyproject 下界抬到 `>=1.45.1`，而 agent-core `[tracing]` 仍是 `>=1.24` ⇒ L-4（多处声明下界必须一致，`scripts/lint_architecture.py:686`）红。

**处置（甲档口径）**：不抬 otel trio——锁版保持 1.45.0、根 pyproject 保持 `>=1.24`，与 agent-core 一致 ⇒ L-4 通过。其余 12 项全部在现有 pyproject 下界范围内，**纯 lock-only，零 pyproject 改动**。

## 2. 与 #71 先例的差异

| 维度 | #71（2026-10-04） | 本批（#79→新 PR） |
|---|---|---|
| pyproject 改动 | 有（回退 otel 1 处 + 抬 17 处下界） | **无**（12 项均在既有下界内） |
| 版本选取 | 组内可抬即抬 | **精确复刻 #79 提议的 12 个版本**（`--upgrade-package X==<ver>` 逐个 pin，不取更新版——处置的忠实性优先：这就是"#79 减去违规组"） |
| 附带 remediation | 无 | **R19 前置防护同分支落地**（见下） |

## 3. 关键时序：fastapi bump 必须晚于（或同批于）R19

#79 含 `fastapi 0.141.1 → 0.143.0`，**跨过 0.142 原生 telemetry 阈值**。若先合 bump 后修 R19，窗口期内全部 app 双 SERVER span + provider 被框架覆盖。故本分支顺序：R19 落地（commit `2efe83e`）→ fastapi bump（本 commit）。门禁 `check_fastapi_telemetry` 在 bump 前已常驻。

## 4. 版本清单（uv.lock 实取，17 项 ALL MATCH 断言）

| 包 | 从 | 到 | | 包 | 从 | 到 |
|---|---|---|---|---|---|---|
| fastapi | 0.141.1 | 0.143.0 | | sqlglot | 30.20.0 | 30.22.0 |
| pydantic | 2.13.5 | 2.14.0 | | pypdf | 6.19.0 | 6.20.0 |
| langgraph | 1.2.12 | 1.2.14 | | mcp | 2.2.0 | 2.3.0 |
| langchain-core | 1.6.5 | 1.6.9 | | ruff | 0.16.9 | 0.17.0 |
| langchain-openai | 1.6.6 | 1.7.0 | | transformers | 5.17.0 | 5.19.0 |
| pgvector | 0.5.0 | 0.5.1 | | asyncpg | 0.31.0 | 0.32.0 |
| **opentelemetry trio** | 1.45.0 | **1.45.0（不抬）** | | multidict（#77 已合） | 6.7.1 | 6.9.1 |
| **langgraph-sdk** | 0.4.2 | **0.4.7** | | | | |

**langgraph-sdk 0.4.7 的来历（传递依赖，非直接更新）**：langgraph 1.2.14 要求 sdk ≥0.4.7 ⇒ 把 sdk pin 在 #78 合入的 0.4.4 会把 langgraph 拽回 1.2.13（实测）；#79 自己的 uv.lock 解析出的正是 0.4.7（`git show origin/pull/79:uv.lock` 实取）⇒ 取 0.4.7 与 #79 逐位一致。rebase 时 uv.lock 冲突按「取上游版 + 重跑 pin」解决，不手编冲突标记。

## 5. 验收判据（本分支实取）

- `uv lock --check` rc=0；15 项目标版本逐包断言 ALL MATCH；
- `scripts/lint_architecture.py` rc=0（L-4 通过、R19 门禁通过）；
- `ruff check .`（ruff 0.17.0）全绿；
- 全量 pytest：**1049 passed / 31 skipped / 1 failed**——唯一失败 `test_k8s_manifest_wiring.py::test_local_mode_model_id_is_the_one_kernel_falls_back_to` 经 stash 隔离证明为**存量环境失败**（根 `.env` 的 `EMBEDDING_VECTOR_DIM=1024` 泄漏进 agent_server settings，CI 无该文件故不现），与本批零因果。

## 6. 执行动作

1. 合 #75（actions/checkout 4→7，ci/ha/assembly 全 SUCCESS）、#77（multidict，lock-only）、#78（langgraph-sdk，lock-only）——均绿且与本 PR 无文件交集（#75 只动 workflow）；
2. 本分支（含 R19 + lock-only）开 PR 合入；
3. 关 #79（关闭说明指向本 PR：同 12 项版本 + otel trio 守 L-4 的理由）；
4. `docs/TODO.md` §0.5 账面订正（open PR / 远端分支读数回填）。
