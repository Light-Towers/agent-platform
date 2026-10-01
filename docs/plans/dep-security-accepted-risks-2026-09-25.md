# 依赖安全风险接受登记（2026-09-25）

> 背景：v3 → main 合并后 Dependabot 报 23 个告警。经逐项对照 uv.lock 锁定版本与官方修复版本：
> - **weasyprint 69→70.0 已升级修复**（agent_federation docs extra），告警已翻转 fixed；
> - **anyio / asyncmy / mcp / transformers 共 13 个为 manifest-range 误报**：uv.lock 实际锁定版本已 ≥ 官方 first_patched，但 pyproject 声明下界低于修复版，Dependabot 依赖图按「声明范围可引入漏洞版本」判定故保持 open。已于 main 经 `fix/main-dep-security-floors` 主动收紧下界（见下「本轮主动修复」），Dependabot 重扫后关闭；
> - **asyncmy 不在 uv.lock**（依赖图陈旧条目），重扫后自动关闭；——【2026-09-30 证伪】5 天后仍 open：该告警的 manifest 是 `courses/zhanggui-wenda/data-agent/uv.lock`，该文件已从 main 删除，属「孤儿告警」，不会自动关闭（详见 2026-09-30 方案文档）；
> - 剩余 9 个为**上游无补丁**的依赖，全部为 dev-only（生产运行时不安装），本文件登记接受理由。

## 本轮主动修复（收紧下界，fix/main-dep-security-floors → main）

Dependabot 依赖图按 pyproject 声明的版本范围判定，不读 uv.lock 锁定版本；故锁定已安全但声明下界过低时告警保持 open。以下改动把声明下界抬到 ≥ first_patched，重扫即关闭。

| 包 | 改动 | 关闭告警（severity×n） | first_patched | 锁定版本 | 引入位置 |
|---|---|---|---|---|---|
| mcp | `>=0.9` → `>=2.0.0` | high×3（DNS 重绑定 / WebSocket / HTTP session） | 1.28.1 | 2.0.0 | 根 `mcp` extra + `packages/agent-runtime` `mcp` extra |
| anyio | （原未声明，纯传递）→ `>=4.14.2` | critical×1 + medium×1（TLSStream IDNA 2003 / process-pool 阻塞） | 4.14.2 | 4.14.2 | 根 `[project].dependencies` |
| transformers | eval 边经 `flashrag-dev` 传递（松散）→ eval extra 显式 `>=5.15.0` | high×3 + medium×1（RCE / 路径遍历） | 5.10.0 | 5.15.0 | 根 `eval` extra（prod `knowledge-service` 早已 `>=5.15.0`） |
| asyncmy | 不在 uv.lock，无需改动 | critical×1（SQL 注入） | 无补丁但非依赖 | — | 依赖图陈旧条目，重扫自动关闭 |

> 验证：`uv lock --check` 通过（锁定版本已满足新下界，无传递漂移）；`ruff` 干净。

## 接受清单

| 包 | 锁定版本 | 告警 | 来源（反向依赖） | 上游状态 | 接受理由 |
|---|---|---|---|---|---|
| fschat (FastChat) | 0.2.36 | 4 high（SSRF ×2 / DoS ×2）+ 2 medium | 仅 `flashrag-dev` extras | 无补丁，上游近两年未发版 | 仅检索回归评测本地使用，不部署为服务，SSRF/DoS 暴露面≈0 ——【2026-09-30 已改为从 lock 真剔除，不再依赖接受判断】 |
| nltk | 3.10.3 | 1 high（模型工件路径穿越） | 仅 `flashrag-dev` extras | 无补丁（3.10.3 已是最新） | 仅加载本地受信模型文件时使用，不处理不可信来源工件 ——【2026-09-30 已改为从 lock 真剔除】 |
| accelerate | 1.14.0 | 2 medium | 仅 flagembedding / peft（RAG extras） | 无补丁 | 训练/推理加速库，漏洞面不在网络路径 ——【2026-09-30 核实：根 lock 已经 PR #16（`a65c564`）升至 1.15.0（≥ 当时声明的 1.14.0）；本轮重报的 accelerate 告警（alert #19，`≤1.14.0`，medium）manifest 属 `courses/zhanggui-zhiku/uv.lock`，为孤儿告警】 |

## 更新记录（2026-09-30）

push 时 GitHub 回显默认分支仍有 21 项告警（4 critical / 11 high / 6 moderate），逐项重扫后的结论变化（取证与实施全量记录见 `plan-dependabot-21-alerts-closure-2026-09-30.md`）：

1. **14 项是孤儿告警**：其 `manifest_path` 指向 `courses/zhanggui-wenda/data-agent/uv.lock` 与 `courses/zhanggui-zhiku/uv.lock`，这些文件已从 main 删除（git tree 里不存在、`contents/` 返回 404），只存在于历史 commit。无可改代码，只能人工 dismiss（`not_used`）——本登记上一轮「重扫后自动关闭」的预期已被五天未关闭的事实证伪（`.github/dependabot.yml` 只配 `directory: "/"`，已删目录永不再扫）。
2. **7 项（fschat 6 + nltk 1）由「接受风险」改为「从 lock 真剔除」**：上游无补丁，升版无解；经同一 commit 的 import 闭包分析证明评测入口不引用这两包，改用根 `pyproject.toml` 的 `[tool.uv] override-dependencies` 假 marker 摘除（lock 306→295 包，零版本漂移）。本文上方「接受清单」中这两行作为历史判断保留，不再代表当前状态。
3. **PR #24 合入后重扫的回报（同日二轮）**：原 7 项被扫描器判为 `fixed`（非人工关闭），但同一轮重扫**新暴露 10 项 PyJWT 告警**（#27–#36，critical×1 / high×5 / medium×4，`first_patched` 均为 2.14.0）。这 10 项**不列入接受风险**：属「有补丁版本的常规可修项」，走 `[tool.uv] constraint-dependencies` 加 `pyjwt>=2.14.0` 升版（lock 解析为 2.15.1，包集合 295 不变、仅 1 条版本漂移）。取证与收口判据见 `plan-dependabot-21-alerts-closure-2026-09-30.md` §11。
4. **新形态记录**：今后遇到「告警指向的 manifest 已不在默认分支」时，不得等待自动关闭，需人工 dismiss；判定方法：`gh api /repos/{o}/{r}/git/trees/{branch}?recursive=1` 查 `truncated=false` 后比对 `manifest_path` 是否存在。另：一次重扫可能同时「关闭旧项 + 新开新项」（本轮 #27–#36 就是原 21 项清单里没有的全新 PyJWT 告警），因此不能以「旧告警已处理」推断总体已清零，每轮都需重拉 open 清单重新取证。

## 复核触发条件

出现任一情况应重新评估并升级/替换：
1. 上游发布补丁版本（`uv lock --upgrade-package <pkg>` 即可跟进）；
2. 上述 extras 被用于生产路径（ dev-only 前提失效）；
3. 告警严重级别上调至 critical。

## 排查方法备忘

uv.lock 反向依赖解析：按 `[[package]]` 分块，取每块 `dependencies = [` 段中的 `{ name = "X" }` 条目（非版本约束格式），可定位任意传递依赖的真实引入方。

`uv tree -i <pkg>` 可直接拉反向依赖树，但需加 `--python 3.12` 规避 deepagents 改名残留导致的多 Python 版本解析失败（默认解析到 py3.14/win32 split 时会报 deepagents 不可达）。（此条随 v3 身份层合流并回，来源 `origin/v3` 版本文档。）
