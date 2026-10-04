# Plan：评审遗留项收口修复（回溯补录）

> **性质：回溯补录（retrospective）。** 本批改动于 2026-10-04 20:14 在会话中先给出方案表并经用户确认后实施
> （「是的，继续」），当时未落 `docs/plans/`；本文件为事后按 AGENTS.md「先方案后编码：有文档/issue 记录」
> 红线补记，内容与实施零偏差。来源：同日对 `ffd86ab...HEAD` 28 提交的三轴评审（Standards/Spec/Correctness）。

## 目标

闭合评审发现的两条 P1 与四条 P2，全部为评审/取证工具自身的可信度缺口，不触产品代码。

## 改动清单（6 代码项 + 1 文档项，均已实施）

| # | 文件 | 改动 | 对应评审发现 |
|---|---|---|---|
| 1 | `scripts/check_doc_sync.py` | `check_architecture_paths` 对 `http` 开头**无条件 continue**（旧逻辑 http+尾斜杠会落到存在性校验必误红）；原三行嵌套条件化简为等价两行（逐形态核验等价） | P2 URL 误报 |
| 2 | 同上 | `check_doc_file_refs` docstring 漏报面补第三条「无反引号普通文本」——AGENTS.md 口径的逃生舱而非缺陷，代价是坏引用可静默逃逸 | P1 逃生舱未登记 |
| 3 | `tests/governance/test_doc_sync_file_refs.py` | +「普通文本不校」用例（钉逃生舱行为，防未来好心补全成扫普通文本打红全仓） | P1 零回归保护 |
| 4 | 同上 | + agents/architecture 两面 fail-closed 自证用例（补齐 plan-doc-sync-tracked-scope §5.3 三面自证欠账） | P2 spec 欠账 |
| 5 | `scripts/evidence/verify_main_tip.py` | `verify()` 开头 HEAD==tip 守卫：漂移即 RuntimeError → 既有 rc=2 PRECONDITION_FAIL 通道（预期集取自本地工作区 workflow 的隐式假设显式化、强制化） | P1 预期集漂移 |
| 6 | `scripts/evidence/normalize_dump.py` | 输入已是 `.utf8` 产物 → 跳过 rc=1（防 `.utf8.utf8` 链式）；`except` 并入 `ValueError`（`..` 类输入裸栈） | P2 |
| 7 | testing-playbook §2.3/§2.4、audit-operator-principal-runbook | 反引号包裹的 gitignored 路径改普通文本（对齐 AGENTS.md 文档防漂移口径） | 低（口径一致性） |

配套回归钉 5 条（其中 URL 专用钉 1 条在实施中补入，属改动 1 意图内）：
`test_plain_text_ref_is_deliberately_not_checked` / `test_fail_closed_covers_agents_and_architecture_faces` /
`test_url_with_trailing_slash_is_not_a_repo_path` / `test_verify_fails_closed_when_head_is_not_tip` /
`test_dump_main_skips_already_utf8_product`。

## 非目标（明确不做）

per_page 分页翻页、`verify_main_tip.REPO` 硬编码改 git remote 派生、workflow 硬钉测试松绑、
普通文本 warn 级探测器（噪音 > 价值）——均已在评审报告中台账化，后续按需另起方案。

## 影响面

仅评审/取证工具与其测试 + 两份运营文档措辞；零产品代码、零依赖变更、零接口变更。

## 迁移/行为变化

唯一对外可见行为变化：`verify_main_tip.py` 现要求本地 checkout 停在被复核 tip，否则 rc=2
（把隐式假设变成 fail-closed 强制，方向安全）。

## 验收标准与实测

governance session 340 passed（含新增 5 条；`-k` 定点 6 passed）· check_doc_sync rc=0 ·
ruff rc=0（5 个改动 py 文件）· lint_architecture rc=0。实施后又经二轮双轴复审
（Standards/Spec 子代理 + 逐 hunk 人工核对）通过；parametrize 修复区与改动前逐字节一致。
