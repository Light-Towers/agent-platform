# F01 残差：positive 评测路径 mock → 生产（#89）

- 日期：2026-10-19
- 来源：GitHub issue #89 / TODO §4 会展业务骨架第 3 条
- 类型：评测路径收敛（跑生产代码）+ 语义差显式登记

## 1. 问题与语义差（实测对码）

`foundation/evaluation.py::_evaluate_positive` 仍调 MVP 内联 `_mock_scope_filter`；负样本路径已在跑生产 `enforce_scope_filter`（审计 P1-9）。

| 维度 | mock | 生产 `enforce_scope_filter` |
|---|---|---|
| 跨租户 `scope_type=PUBLIC` 项 | **放行** | **剔除**（无 PUBLIC 例外） |
| `ctx.scopes` 非空时 scope_key 收窄 | 忽略 | 收窄 |
| 同租户条目 | 放行 | 放行 |

**语义差的取向（回答 issue 待拍板 1）**：**不在本项给生产补 PUBLIC 例外**。理由：① 那是契约语义变更（"公开知识是否跨租户可见"是产品决策），按红线须先出 ADR，不能搭车评测收敛；② mock 的 PUBLIC 放行从未被任何 positive 用例依赖（实测零出现）⇒ 补例外没有评测面依据；③ 让差距**可见**（生产在评测里跑，语义差写进已知边界）比被 mock 掩盖更接近可运营。**若产品将来要"公开知识跨租户可见"，正确路径是改 `enforce_scope_filter` + ADR + 评测回归，不是把 mock 加回来。**

## 2. 切换爆炸半径（实测）

- `test_evaluation_framework.py` 的 positive 用例候选 = `_published_candidate()`（tenant_A / PRIVATE / exhibition_id=exp_001），tenant_context 无 scopes ⇒ 生产与 mock 输出**逐位相同**（同租户 + scopes 空 ⇒ 租户级全放行）；
- 跨租户 PUBLIC 候选在 positive 用例零出现 ⇒ 无现成判据被打破；
- 重取基线不卡资源：exhibition CI 走 `pytest applications/exhibition-agent/tests`（确定性，无 LLM）。

## 3. 改动清单

1. `_evaluate_positive` 改调生产 `enforce_scope_filter`（ExecutionContext 构造口径与负样本路径对齐：tenant_context 取 tenant_id/user_id/tenant_type/scopes；scope_key 取 `expected.scope_key`，缺省 `exhibition_id`——与负样本路径同缺省）；
2. 删 `_mock_scope_filter`（mock 的存在正是残差根源；负样本路径已无 mock，positive 切换后零消费者）；
3. 新增回归 `test_positive_uses_production_filter_semantics`：跨租户 PUBLIC 候选在 positive 路径被**剔除**（钉死现行生产语义，防未来"顺手补 PUBLIC 例外"不走契约）；同租户 + scopes 收窄行为各一条；
4. 模块 docstring 的 F01 行更新为"已跑生产代码"，并显式登记 PUBLIC 语义差为已知边界；
5. TODO §4 F01 行状态订正（残差从"一处"归零；PUBLIC 例外转"需 ADR 的契约问题"另录）。

## 4. 验收判据

- 既有 positive 用例**断言逐字不改**全绿（中性证明：生产语义对现有数据输出逐位相同）；
- 新回归 3 条全绿；exhibition session 全绿不减分；
- `grep _mock_scope_filter` 全仓 = 0（mock 清零自证）；
- ruff / docsync rc=0；TODO §4 行订正 + 追记（相对口径 open 26→25）。

## 5. 回滚

单 commit（evaluation.py + 测试 + docstring + TODO），`git revert` 整体回退；回滚后 positive 路径回到 mock，负样本路径不受影响（本就独立）。
