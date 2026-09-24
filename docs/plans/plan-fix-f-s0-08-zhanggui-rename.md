# 修复方案：F-S0-08 — zhanggui-zhiku 包名 app → zhanggui_zhiku 迁移

> 日期：2026-09-21
> 严重度：**P2**（包名遮蔽风险 / 红线 1 关联）
> 来源：[S2 债务诊断](../analysis/2026-09-21/02-debt-diagnosis.md) §2.3 F-S0-08
> 状态：**已实施**（2026-09-21，包目录重命名 + 243 处 import 替换 + 运行时路径/注释更新，8 session 全绿）

## 1. 目标

将 zhanggui-zhiku 的 Python 包名从 `app` 改为 `zhanggui_zhiku`，消除包名遮蔽风险（AGENTS.md 警告"勿在根测试 import app"），并让 Python 包名与 pyproject `name = "zhanggui-zhiku"` 对齐。

## 2. 问题分析

### 2.1 当前状态

- `applications/zhanggui-zhiku/app/` 是包目录（Python 包名 `app`）；
- `pyproject.toml:48` `[project.scripts] zhanggui-zhiku = "app.main:run"`；
- `pyproject.toml:53-55` `[tool.setuptools.packages.find] include = ["app*"]`；
- 全仓 `from app.` / `import app.` 命中 258 处（含注释/字符串），实际 import 语句主要在 zhanggui 内部（`app/` + `tests/` + `eval/`）。

### 2.2 遮蔽风险

包名 `app` 在 sys.path 上会遮蔽其他同名包（历史根 `app/` 已改名 `agent_server/`，但 zhanggui 仍用 `app`）。根测试/共享代码若 `import app` 会命中 zhanggui 而非预期。AGENTS.md 已立禁令："勿在根测试/共享代码中 `import app`"。

### 2.3 根/其他引用核查

根 `tests/` 与 `packages/` 中对 `app` 的引用均为**注释**（如 `tests/planner/test_planner_protocol.py:125` 提旧 `from app.config`）或 **FastAPI 实例变量名**（`from agent_server.main import app` / `from exhibition_agent.server import app`，变量名非包名）。**无实际 `import zhanggui.app`** → 迁移不影响根/其他。

### 2.4 FastAPI 实例 `app`（替换禁区）

| 位置 | 代码 | 性质 |
|------|------|------|
| `app/main.py:44` | `app = FastAPI(...)` + `app.add_middleware` ×2 + `app.include_router` ×2 | FastAPI 实例变量，**不可替换** |
| `tests/unit/test_security_guards.py:445` | `app = FastAPI()` | 测试实例，**不可替换** |

→ 替换必须**限定 import 语句行**（`^\s*(from|import) app\.`），不可全局 `s/\bapp\./.../g`（会误伤 `app.add_middleware`）。

## 3. 影响面

| 范围 | 改动 |
|------|------|
| `applications/zhanggui-zhiku/app/` → `zhanggui_zhiku/` | 包目录重命名（`git mv`） |
| zhanggui 内所有 `.py` 的 import 行 | `from app.` → `from zhanggui_zhiku.`、`import app.` → `import zhanggui_zhiku.` |
| `pyproject.toml` | `scripts` → `zhanggui_zhiku.main:run`；`packages.find.include` → `["zhanggui_zhiku*"]` |
| `tests/unit/conftest.py` / `tests/integration/conftest.py` | sys.path 注释/逻辑更新 |
| `eval/run_eval.py` / `run_ablation.py` | import 行替换 |
| `scripts/flashrag_eval/run_eval.py:21` | 注释更新（非实际 import） |
| `AGENTS.md` | zhanggui 行"包名仍为 app"警告移除 |

### 3.1 不受影响

- 根 `tests/`、`packages/`、其他 `applications/`：无实际 `import zhanggui.app`，零改动。
- pyproject `name = "zhanggui-zhiku"`（发行名，连字符）不变，只改 Python 包名（下划线）。
- FastAPI 实例变量 `app`（main.py:44 等）：保留，不替换。

## 4. 迁移策略

### 4.1 新包名

`zhanggui_zhiku`（下划线，符合 Python 包名规范；与发行名 `zhanggui-zhiku` 对应）。

### 4.2 步骤

1. `git mv applications/zhanggui-zhiku/app applications/zhanggui-zhiku/zhanggui_zhiku`
2. **限定 import 行**替换（不全局 sed）：
   ```bash
   # 只替换 import 语句行，避开 FastAPI 实例 app.add_middleware 等
   rg -l "^\s*(from|import) app\." applications/zhanggui-zhiku/ \
     | xargs sed -i -E 's/^\s*from app\./from zhanggui_zhiku./; s/^\s*import app\./import zhanggui_zhiku./'
   ```
3. `pyproject.toml`：`scripts` → `zhanggui_zhiku.main:run`；`packages.find.include` → `["zhanggui_zhiku*"]`
4. conftest sys.path 注释更新
5. `AGENTS.md` zhanggui 行警告移除
6. `ruff check --fix`（isort 重排）+ 全量 pytest

### 4.3 实施前盘点（必做）

```bash
# 精确 import 语句数
rg -c "^\s*(from|import) app\." applications/zhanggui-zhiku/
# FastAPI 实例位置（禁区，确认不被替换）
rg "app\s*=\s*FastAPI|app\.(include_router|add_middleware)" applications/zhanggui-zhiku/
```

## 5. 验收标准

| # | 命令 | 预期 |
|---|------|------|
| 1 | `uv run pytest applications/zhanggui-zhiku/tests -q` | 全绿（unit 223 + integration `ZHIKU_INTEGRATION=1` 守卫 skip） |
| 2 | `rg "^\s*(from\|import) app\." applications/zhanggui-zhiku/` | 零命中 |
| 3 | `rg "app\s*=\s*FastAPI" applications/zhanggui-zhiku/` | 仍命中 main.py:44 + test_security_guards.py:445（实例保留） |
| 4 | `uv run python -c "import zhanggui_zhiku"` | 成功 |
| 5 | `make test` | 8 session 全绿 |
| 6 | `uv run ruff check applications/zhanggui-zhiku/` | 0 error |

## 6. 回滚策略

`git revert` 单 commit（目录重命名 + import 替换 + pyproject）。建议单独 commit 便于回滚。

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 误替换 FastAPI `app` 变量名 | 中 | 运行时 NameError | **限定 import 行替换**（§4.2），不全局 sed；替换后 grep `app = FastAPI` 复核 |
| 误伤注释/字符串里的 `app.` | 低 | 文档乱 | 限定 import 行；diff 复核 |
| integration 测试需环境 | 已有 | ZHIKU_INTEGRATION 守卫 skip | 不影响门禁 |
| entry script `zhanggui-zhiku` 命令失效 | 低 | CLI 启动失败 | pyproject `scripts` 同步改 `zhanggui_zhiku.main:run` |
| `__pycache__` 残留旧 `app` 缓存 | 低 | 收集期 import 旧包 | 迁移后清 `__pycache__` |

## 8. 工作量估计

约 **半天~1天**（目录重命名 + 全量 import 替换 + conftest + pyproject + 全量回归 223 测试 + diff 复核）。建议在 F-S1-04/05 收敛后做（避免迁移期多线作战），但无硬前置。

## 9. 实施建议

- 单独 PR / commit，便于回滚；
- 替换前先按 §4.3 盘点；
- **限定 import 行替换**，不全局 sed；
- 替换后 `ruff --fix`（isort）+ 全量 pytest + diff 人工复核。
