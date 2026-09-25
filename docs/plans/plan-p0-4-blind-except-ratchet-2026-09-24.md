# 方案 P0-4：恢复盲捕获门禁（BLE001 / S110）——ratchet + 分批烧除

> 来源：`docs/plans/arch-audit-2026-09-24.md` P0-4 / 技术债 D7（当前标 reopened）。
> 满足 AGENTS.md「先方案后编码」红线：含目标 / 影响面 / 迁移策略 / 验收标准。
> 逐处原始清单（262 行，`file:line:col CODE msg`，斜杠路径）：`docs/plans/p0-4-blind-except-inventory.txt`。
>
> **执行状态（2026-09-24）**：✅ **M1 棘轮已落地并验证** —— 6 份配置全部启用 `BLE001/S110`、103 文件 legacy 入 `per-file-ignores` 基线、`ruff check .`（CI 命令）全绿；对 agent-core / agent-runtime / knowledge-service 三处非基线干净文件做防回归探针均报 `BLE001+S110`。
> 🔁 **M2 策略修订（2026-09-24，经用户复核，取代下方“逐点烧除”原方案）**：**放弃「逐点 `# noqa: BLE001` + 删文件基线」的烧法**，改回**整包 `per-file-ignores` 基线豁免 + 源码零逐点 noqa**。理由：逐点 noqa 的存废完全依附于 `BLE001` 是否常驻 `select`——历史上该规则被 `3ccc90e`（加）→ 移出 select → `92ba46f`（当死注释清除）反复开关，逐点 noqa 是加-删-加 churn 的根源。现态：6 份配置均启用 `BLE001/S110`、legacy 全在整包基线、`ruff check .` 全绿；仅保留**无 noqa 的安全窄化**（纯导入守卫 `except Exception`→`except ImportError`、`json.loads`→`except (ValueError, TypeError)`）。agent-core `pytest 200 passed`、agent-runtime `539 passed`。

## 0. 结论先行

- 存量 = **262**（BLE001 盲捕获 **241** + S110 try/except/pass **21**），散落在 **103** 个文件。
- 门禁当前**整体未启用**：根 + 5 子包共 **6** 份 ruff 配置的 `select` 均为 `["E4","E7","E9","F","I"]`，不含 `BLE`/`S`；根 `ignore` 里的 `BLE001/S110` 只是防御性冗余（未 select 也就无所谓 ignore）。
- 一刀切「全修完再开门禁」= 多会话量级，且会长期无保护；**不采用**。
- 采用业界标准 **ratchet（棘轮）**：一次性把规则纳入 `select`，对**现有** 103 文件生成 **per-file-ignores 基线**锁死 legacy，令 `ruff check .` 保持**绿**；此后任何**新**盲捕获、或在**已烧净**文件里的盲捕获**直接 fail**。然后按优先级**逐文件**从基线删除条目 = 净减少、可计数、不可回潮。

## 1. 目标

| # | 目标 | 度量 |
|---|------|------|
| G1 | 门禁**真正启用**且**防回归** | 在干净文件新增 `except Exception:` → `ruff check .` 立即 fail |
| G2 | legacy **显式可见**（非全局静默豁免） | 债务 = 基线条目数，可 grep、单调递减 |
| G3 | Tier-1 **静默吞异常**清零 | S110 21 → 0（改为 `logger.warning/debug` 或窄化 except） |
| G4 | CI 全程绿 | `uv run --with ruff ruff check .` 0 错误；`make lint` 等价 |

## 2. 影响面（配置拓扑）

规则启用点按「就近配置」分区——**每个子树改它自己的配置**，root 只覆盖无独立配置者：

| 生效配置 | 覆盖文件数(违规) | 关键子树 | 备注 |
|----------|----------------|----------|------|
| `packages/agent-core/pyproject.toml` | 63 | tracing(12)、tracing_propagation(8)、memory/*、tools/* | 内核，**最高爆炸半径**，优先 |
| `packages/agent-runtime/pyproject.toml` | 28 | db(7)、admission_gateway、planner/protocol、control_plane | 内核运行时 |
| `applications/agent_federation/pyproject.toml` | 84 | agent/main_agent(13)、agent/cache/layers(12)、api/server | 应用，量大 |
| `applications/knowledge-service/pyproject.toml` | 62 | clients/milvus_utils、*process/agent/nodes/* | 应用，量大 |
| `applications/exhibition-agent/pyproject.toml` | 10 | skill_loader/app、observability/trace | |
| **根 `pyproject.toml`** | ~15 | agent_server(6)、scripts(4)、eval(1)、tests(1)、kefu(1)、nl2sql(2) | 长尾；含 2 个无独立配置的应用 |

> 注意：`agent-core` 与 `agent_federation` 配置 `extend-exclude` 掉 `tests`；基线只需覆盖**实际被检查**的文件，勿给 excluded 路径写条目。

**Tier-1 S110（21 处，全部应处置）**：
`agent_federation`: `agent/db.py:86`、`agent/health_check.py:30`、`api/monitor.py:33`
`exhibition-agent`: `observability/trace.py:164`
`agent-core`: `intent/classifier.py:83`、`memory/embedder.py:86`、`memory/vector_backend.py:294`、`tools/adapters/mcp.py:152`、`tools/guarded.py:113`、`tracing.py:362,432,449,460`
`agent-runtime`: `admission_gateway.py:256,286`、`control_plane.py:295`、`db.py:428,440`、`planner/protocol.py:556`、`trajectory/replay.py:161`
`scripts`: `lint_architecture.py:60`

## 3. 分类法（BLE001 逐处归入其一）

盲捕获即便**已记日志**仍会被 BLE001 命中（它管的是「捕获过宽」而非「是否静默」），故 241 里多数是**合理的降级/兜底**，需人工归类：

- **A 窄化**（首选）：能判定具体异常类型（如 `except (ValueError, KeyError)`、网络 `except httpx.HTTPError`）→ 直接改，**从基线删除**。
- **B 记日志/降级但保留宽捕获**：兜底路径确需宽捕获 → 保留 `except Exception` 并**带 `logger`**，加行内 `# noqa: BLE001: <一句话理由>`；从**文件级基线**降级为**行级豁免**（更精确，逐步可审计）。
- **C 有意吞**（S110 专属）：`except: pass` 若确为「尽力而为、失败可忽略」→ 至少 `logger.debug` 或注释化 `pass`；否则改 A。
- **D 待议**：跨服务/契约相关、需领域判断 → 暂留基线，标注 owner。

## 4. 迁移策略（执行步骤，逐步可回退）

**M1 建立棘轮**（✅ 已完成，2026-09-24）
1. ✅ 对 6 份配置：`select` 追加 `"BLE001","S110"`；根 `ignore` 移除 `BLE001/S110`。
2. ✅ 为每份配置生成 `[tool.ruff.lint.per-file-ignores]` 基线（103 文件：agent-core 16 / agent-runtime 13 / federation 31 / knowledge 24 / exhibition 7 / 根 12）。
3. ✅ `uv run --with ruff ruff check .` **All checks passed**（=CI 命令）。`courses/` 经 `.gitignore` 被 ruff 默认 `--respect-gitignore` 跳过，故不影响门禁。
4. ✅ 防回归探针：agent-core / agent-runtime / knowledge-service 三处干净临时文件均触发 `BLE001`+`S110`（`Found 3 errors`），探针文件已删除、全树复验 `ruff check .` 仍绿。

基线生成脚本（PowerShell，产出可直接粘贴的 per-file-ignores 片段，按生效配置分桶）：
```powershell
# 依赖 docs/plans/p0-4-blind-except-inventory.txt
$inv = Get-Content docs/plans/p0-4-blind-except-inventory.txt
$map = @{}
foreach ($l in $inv) {
  $f = ($l -split ':')[0]; $code = if ($l -match 'S110') {'S110'} else {'BLE001'}
  if (-not $map[$f]) { $map[$f] = @{} }; $map[$f][$code] = $true
}
$map.GetEnumerator() | Sort-Object Name | ForEach-Object {
  $codes = ($_.Value.Keys | Sort-Object) -join '", "'
  '  "{0}" = ["{1}"]' -f $_.Name, $codes
}
```
> 再把各行按 `packages/agent-core/**` 等前缀路由到对应 pyproject 的 `[tool.ruff.lint.per-file-ignores]`；基线路径用 glob（如 `"agent_core/**/*.py"`，相对该配置文件目录）以免跨机漂移。

**M2 策略修订（2026-09-24，经用户复核，覆盖上述原烧法）**

复核 `git log` 发现：`# noqa: BLE001` 历史上被 `3ccc90e` 全量加入（当时 `BLE001` 在 `select`）→ 该规则被移出 `select` → `92ba46f` 把 358 处 noqa 当“死代码”清除。**逐点 noqa 的存废完全依附于规则开关**，是加-删-加 churn 的根源，且把豁免从配置搬进源码是污染。故修订如下：

- **保留整包 `per-file-ignores` 基线**作为 legacy 宽捕获的豁免载体（集中在 pyproject，可 grep、单调递减），**源码不再写任何逐点 `# noqa: BLE001`**。
- 已把 **agent-core / agent-runtime / knowledge-service** 三包的 M2 源码改动 `git restore` 回退到 HEAD（去掉逐点 noqa），并按 `ruff check` 实况**重建各自整包基线**（agent-core 16 文件、agent-runtime 13 文件、knowledge-service 24 文件）。
- **仅保留无 noqa 的安全窄化**（真 bug 修复，不改降级行为）：纯可选依赖导入守卫 `except Exception`→`except ImportError`（agent-core：tracing×2、tracing_propagation、tokenizer、events）、`json.loads`→`except (ValueError, TypeError)`（llm_judge）。**含函数调用的 try 体不窄化**（monitor、tracing_propagation 的 is_tracing_enabled 调用点等），避免让本应被兜底的运行时异常逃逸。
- 验收：`ruff check .` 全绿；`pytest packages/agent-core` 200 passed、`packages/agent-runtime` 539 passed。

> 说明：整包基线粒度下，一个文件只有其**全部**盲捕获被真修/窄化后才会脱离基线；多数降级兜底点（客户端调用、用户回调、后台任务标失败）宽捕获是**有意为之**，长期留在基线属正常终态，不强求清零。D7 由「逐文件烧除」重定义为「安全窄化 + 基线常守」。

## 5. 验收标准

1. 6 份配置 `select` 均含 `BLE001` 与 `S110`；根 `ignore` 不再含二者。
2. `uv run --with ruff ruff check .` **0 错误**（legacy 已入基线）。
3. **防回归探针**：新净文件引入盲捕获 → CI fail（G1 的核心证据，须截图/记录一次）。
4. 基线条目数 == `p0-4-blind-except-inventory.txt` 去重文件数（103，减去各配置 excluded tests 命中者）；此后**只减不增**（新增即回潮，PR 阻断）。
5. M2 每批次：就近 `ruff check` 绿 + 受影响包 `pytest -q` 绿；**禁止**为凑绿而 `except: pass` 或删用例（红线）。
6. 完成时把 D7 从 reopened 复位为闭合、审计 §8.2 P0-4 划除、更新 `p0-4-blind-except-inventory.txt` 指向残余。

## 6. 风险与回退

- **风险**：per-file-ignores 路径 glob 写错 → 漏锁使 CI 假红，或多锁掩盖新违规。缓解：M1 步骤 3/4 双向验证（整体绿 + 探针必红）。
- **风险**：误用 `--add-noqa` 退回到「逐处 noqa 噪声」（D7 曾因此反转过）。缓解：基线走 **per-file** 而非逐行；仅 B 类**降级后**才允许行内 noqa 且带理由。
- **回退**：M1 为纯配置增量，revert 6 份 pyproject 即恢复「门禁关闭」现状；M2 每文件改动独立可 revert。
- 规模：262 处 / 103 文件不可能单轮完成；本方案交付**棘轮机制 + 分类法 + 批次顺序**，使后续烧除自动化、可计量、防回潮。
