# 刀 4 施工清单（LLD）：config_hash 扩展 + run 快照（dev 侧）+ golden 重标（需环境）

> 状态：🟡 部分施工（2026-11-21，HEAD=0f3a26b0 工作区未提交）——**环境无关部分已落地并通过验证**；**golden 绑真实 chunk_id（×3）+ 基线重取需真 Milvus/126，未跑，留作部署步骤** ｜ 依据：主方案 `docs/plans/plan-kb-chunking-profile-2026-11-20.md` §9 刀 4 / §6

## 0. 范围拆分

刀 4 原内容 = golden 真实重标（×3 策略）+ config_hash 扩展 + 基线重取 + 文档回写。其中：

- **环境无关（本轮已落地）**：config_hash 纳入切分参数、run 快照读取与落盘、对应单测。
- **需真环境（本轮未跑，留部署步骤）**：golden 用真实 chunk_id 重标（3 策略各一套，基准 56 条 ×3）、三种策略各跑一遍检索指标、基线重取并登记 HEAD+config_hash、compare_runs 显著性门禁。

## 1. 已落地：config_hash 扩展（F-15 地基）

| 文件 | 改动 |
|---|---|
| `knowledge_service/conf/config_hash.py` | `compute_config_hash(chunk_config=None)`：新增可选参数，传入时把切分参数 JSON 并入哈希输入；不传时哈希不变（向后兼容生产 `init_tracing` / 旧评测脚本） |
| `eval/run_eval.py` | 新增 `_read_chunk_config_snapshot(collection)`：从 `index_registry[collection].chunk_params`（刀 2 导入时写入）读本次生效切分参数，缺失/旧占位值时 graceful 回落 None；`main` 用它算扩展 hash 作 run_id，并把 `chunk_config` 快照写进 `metrics.json` |
| `tests/unit/test_config_hash_chunk_config.py`（新） | 5 例：无参向后兼容、切分参数改变哈希、不同参数可区分、key 顺序稳定、快照读取（命中/缺失/占位回落） |
| `eval/ablation.py` + `tests/unit/test_ablation.py` | **降级路径回归修复（交付前自检发现）**：`fallback_config_hash()` 同步接受可选 `chunk_config` 参数——否则旧部署镜像缺 `conf/config_hash` 时，`run_eval.py:362` 传 `chunk_config=` 给无参 fallback 会 TypeError 崩溃。补 1 例 |

**效果**：同 yaml + 同集合下，不同切分参数的两次 run 现在得到不同 config_hash，run 目录与 metrics.json 都记录当次切分参数——解决 F-15"同 hash 不可区分"。

## 2. 未跑：golden 真实重标 + 基线重取（需部署环境）

按主方案 §6 的 F-14/F-15 前置，以下步骤**必须**在真环境做，本机无 Milvus/Mongo/真实语料，如实留白：

1. 用 `eval/gen_golden.py` / `remap_golden_ids.py` 把 `golden_queries.jsonl` 的假设 chunk_id（`c_101` 等）重标为真实 Milvus chunk_id，产出 `golden_queries.real.jsonl`（`eval/README.md:81` 明说玩具集 Recall 全 0 属预期，不能用它做门禁）。
2. 三种策略（title/char/line）各按真实 chunk_id 标一套 `relevant_chunk_ids`/`grade`（基准 56 条 ×3）。
3. 各跑一遍 `eval/run_eval.py --golden golden_queries.real.jsonl`，新 run_id 已自带切分参数快照与扩展 hash。
4. `compare_runs.py` 做 baseline vs candidate 配对显著性比较，显著回归非零退出；新基线登记 HEAD sha + 件名 + **含切分参数的 config_hash**（AGENTS.md 观测面硬规矩 #9）。
5. 若出现"切分劈答案"badcase，开发回头调策略实现/补 golden 用例，重跑——全程开发侧，不进界面、不拦用户改配置。

**复审触发**：完成上述后回写主方案 §8 P-2 状态与本文状态行。

## 3. 验证读数（环境无关部分，HEAD=0f3a26b0 工作区未提交）

- **rev**：`0f3a26b0`（未提交；提交后复取）。
- **KS 全量单测**：`uv run pytest applications/knowledge-service/tests/unit -q` → **526 passed, 7 skipped**（刀 2 后 520，本部分 +5 快照测试 +1 fallback 签名测试）。
- **lint**：`uv run --with ruff ruff check .` → rc=0，`All checks passed!`。
- **eval 可导入**：`uv run python eval/run_eval.py --help` → 正常输出参数列表（新增逻辑未破坏脚本入口）。
- **doc-sync**：`uv run python scripts/check_doc_sync.py` → rc=0，0 警告。
- **未跑（如实标注）**：golden 真实重标 ×3、三策略检索评测、基线重取、compare_runs 显著性门禁——均需真 Milvus/126 环境，留部署步骤；不声称已验。
