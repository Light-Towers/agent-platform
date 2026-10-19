# U-1 销项：QueryRequest 双写兼容层移除

- 日期：2026-10-19
- 来源：`docs/TODO.md` §0.2 C 组第 3 条 / §6 清单第 3 项（README「已知待拍板项（技术债）」U-1）
- 类型：契约收敛（删兼容层），非新功能

## 1. 背景

U-1 登记的双写兼容层有两半：
- `query`/`question`：2026-08-16 收敛批已删（`applications/agent_server/schemas.py` 与 ks `query_router.py` 均改为纯字段）；
- `session_id`/`thread_id`：唯一残留 `packages/shared-schemas/shared_schemas/query.py:21-25` 的 `validation_alias=AliasChoices("session_id","thread_id")`。

## 2. 取证结论（2026-10-19 只读审计，命令与计数可复跑）

| 取证项 | 结果 |
|---|---|
| `AliasChoices` 全仓命中（`rg -n 'AliasChoices' --glob '*.py'`） | 仅 `query.py` 2 处（import + 使用）；agent_server 零命中 |
| `"thread_id":` 22 个文件中 QueryRequest 入站消费 | 仅 `packages/shared-schemas/tests/test_contracts.py:50-65` 两个自家契约测试；其余均为 checkpoint 配置键 / SSE 回包 / DB 列 / Form/WS 参数 |
| `"question":` 34 个文件中 QueryRequest 入站消费 | **0**；README:221 与 docs/project-introduction-2026-10-12.md:359 是 curl 漂移示例（agent_server 实际已 422）；README:258/369 属 SqlTrainRequest/IngestExample 另一套契约 |
| 生产调用方发旧名 | 0（`run-all.py`/`chat.html:693-694`/`e2e_traceparent.sh:28` 全部新名） |
| 静态 OpenAPI 文件 | 零命中（schema 运行时生成，删 alias 后 `/openapi.json` 自动收敛，无规范文件需手工同步） |
| 历史普查佐证 | `CHANGELOG.md:1166` + `docs/architecture/architecture-improvement-plan.md:290`（2026-08-16：无生产调用方发旧名，仅两个测试） |

**结论：无真实外部生产者，唯一消费者是自家测试 ⇒ 直接删除，不设弃用窗口。**

## 3. 为什么不设弃用窗口（判据）

兼容层的存在理由是"老客户端仍在发旧名"。取证显示：
1. 仓内全部调用方（含课程脚手架的 chat.html、e2e 脚本、批量 runner）已用新名；
2. 唯一读旧名的两个用例是验证"兼容层本身在工作"的自指测试——删层后它们的存在理由随之消失；
3. 设弃用窗口需要"迁移期报错文案 + 发布周期公告 + 回滚开关"，其成本高于零消费者下的删除成本；
4. 万一日后发现外部消费者：pydantic 默认 `extra="ignore"` ⇒ 旧客户端发 `thread_id` 会被**静默忽略**（session_id=None）而非 422。行为变化已在此登记，属知情取舍（原双写下旧客户端"碰巧工作"，删后 session 丢失但请求不失败）。

## 4. 改动清单（一项一 commit）

1. `packages/shared-schemas/shared_schemas/query.py`：删 `AliasChoices` import、兼容注释与 `validation_alias`；docstring 注明"2026-10-19 U-1 销项，旧字段名不再接受"。
2. `packages/shared-schemas/tests/test_contracts.py`：`test_legacy_thread_id_alias` 改为反义断言（旧名被忽略、`session_id is None`）；`test_alias_serialization_uses_session_id` 相应简化（无 alias 后序列化本就用字段名，保留断言防未来再加回）。
3. 文档勘误 5 处：`packages/shared-schemas/README.md:18`、`README.md:237-239`（/query 参数表）、`README.md:482`、`README.md:594`（**顺带修正指错的位置**——原文指向 `schemas.py:41-54`，U-1 收敛后该段已不存在，改指 shared-schemas/query.py）、`docs/runtime-self-build-analysis.md:208`。
4. `docs/TODO.md`：§0.2 表第 3 行 + §6 清单第 3 项销项（计数按相对口径更新）。

## 5. 验收判据

- `uv run pytest packages/shared-schemas/tests -q` 全绿（含改写的反义断言）；
- 受影响 app 的 schema 消费方零回归：agent_server / knowledge-service / nl2sql / federation / kefu 五个 session 合跑不减分；
- 勘误后 `rg 'thread_id' README.md docs/runtime-self-build-analysis.md packages/shared-schemas/README.md` 不再声称"入站兼容"；
- `scripts/check_doc_sync.py` rc=0、ruff rc=0。

## 6. 回滚

单 commit 内完成删除 + 测试 + 文档，`git revert <sha>` 整体回退，无中间态。
