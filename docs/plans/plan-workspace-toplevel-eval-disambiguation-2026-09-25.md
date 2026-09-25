# 方案：workspace 顶层包名冲突全局治理（eval 消歧义 + 门禁）

> 日期：2026-09-25 ｜ 状态：已确认执行 ｜ 来源：分支评审后环境缺口修复的复盘
> 前次 conftest 补丁（commit c6b60a5）为散点止血，本方案落地后**撤销**。

## 1. 问题与根因

**症状**：`uv sync --all-packages` 统一 venv 下，knowledge-service 单测
`from eval.metrics import ...` 报 ModuleNotFoundError（`eval` 被解析到 agent_federation 版）。

**根因（三层）**：
1. **机制**：uv/hatchling editable 安装以朴素 `.pth` 把**成员源码根整体**加入 `sys.path`，
   于是源码根下**任何带 `__init__.py` 的子目录**都成为可全局 import 的顶层包；
2. **命名冲突**：顶层包名 `eval` 被两处 regular package 占用——
   `applications/agent_federation/eval/`（空 `__init__.py`）与
   `applications/knowledge-service/eval/`（有实质内容），解析结果取决于 `.pth` 顺序（隐雷）；
3. **架构倒挂**（侦查新发现，比测试失败更严重）：ks 生产代码
   `knowledge_service/main.py` 为拿 `compute_config_hash()` 直接 `from eval.run_eval import`，
   把评测 harness 拉进生产启动链路；且 ks wheel `only-include=["knowledge_service"]`
   **不含 eval/** → 打包部署后模块缺失、服务起不来（当前仅 editable 开发环境侥幸能跑）。

## 2. 目标与验收标准

按 AGENTS.md「横切关注点全局优先」三层判定：

| 层 | 措施 | 验收 |
|---|---|---|
| ① 单一实现 | `compute_config_hash`（+ `_RUNTIME_BASELINE`/`_sha256_hex`）从 eval 上收到 `knowledge_service/conf/config_hash.py`（其职责本就是"读 conf/*.yaml 算哈希"，与 `retrieval_config.py` 等同居 conf 包）；main.py 与评测脚本引用同一实现 | `grep "from eval" knowledge_service/` 生产代码零命中；config_hash 单测通过 |
| ② 全局装配（消歧义） | 重命名冲突中引用面较小方：`agent_federation/eval/` → `agent_federation/evaluation/`（语义更准确：评测 harness，非通用 eval 表达式求值）；全仓仅剩 ks 一个顶层 `eval` regular package，遮蔽方向唯一化 | ks/federation 两 session 互不干扰通过；federation `--help`/直跑路径可用 |
| ③ 强制门禁 | `scripts/lint_architecture.py` 新增不变量：扫描各 workspace 成员（`packages/*`、`applications/*`）源码根下含 `__init__.py` 的顶层目录名，**跨成员重名即 CI 失败**（与 `.pth` 暴露机制精准对应）；预期违规集 = ∅，无需白名单 | 门禁在当前树通过；人为造重名目录即报错（自测） |
| 收口 | 撤销 `tests/unit/conftest.py` 的 importlib 重绑补丁（恢复 c6b60a5 之前形态） | conftest 无散点 hack |

## 3. 影响面清单

**ks（①）**：`knowledge_service/main.py`、`eval/run_eval.py`（删本地实现改为导入）、
`eval/run_ablation.py`（改为从 conf 导入）、新增 `knowledge_service/conf/config_hash.py`。

**federation（②，live 引用）**：目录本身（git mv，保留历史）、`evaluation/run_eval.py` +
`run-all.py`（`from eval.*` → `from evaluation.*`、docstring 路径）、
`tests/unit/test_eval_baseline.py`（`agent_federation.eval.*` → `evaluation.*`）、
`pyproject.toml`（ruff per-file-ignores 3 行）、`.gitignore`（`eval/results/` → `evaluation/results/`）。
历史快照文档（CHANGELOG、AUDIT.md、PROPOSAL.md、docs/analysis/**）中的旧路径**不回改**（历史记录原则）。

**根（②③ + 收口）**：`README.md:586`、`docs/TODO.md:85`（live 引用）、`Makefile` eval 目标注释
（冲突已根除，改写注释）、`scripts/lint_architecture.py`（新增门禁）、
`applications/knowledge-service/tests/unit/conftest.py`（撤 hack）、根 `CHANGELOG.md`。

**不做**（明确排除）：federation 其余扁平顶层包（agent/api/tools/… 目前无跨成员重名，
`.pth` 全暴露的打包风格收敛属更大重构，暂不扩大战线）；根 `eval/`（无 `__init__.py`，
脚本按路径直跑，不参与 regular package 竞争）。

## 4. 迁移策略与回滚

纯路径/导入迁移，无数据、无契约变更；每步独立可验证，全量验证 =
ks/federation/根 三 session + `make lint` 等价 + lint_architecture + check_doc_sync + `make eval` 等价。
回滚 = revert 单 commit。

## 5. 风险

- `.pth` 顺序在不同平台/安装顺序下曾决定谁赢 → 本方案后 `eval` 仅剩单一持有者，顺序敏感性消除；
- federation 直跑脚本 `python evaluation/run_all.py` 的使用者（README 命令）需知悉新路径（已同步改）；
- 门禁启发式（扫 `__init__.py`）与 editable 机制同源，若未来 editable 改为显式 finder 映射，门禁仍是更严格的保守集，不误放。
