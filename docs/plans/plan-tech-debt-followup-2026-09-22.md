# 后续技术债务追踪（T3.1 跳过项）

> 来源：`docs/plans/plan-tech-debt-cleanup-2026-09-22.md` T3.1 Low 19 项中跳过的 8 项。
> 跳过原因：改动面大或需逐条人工判断，不适合在批量清扫中混做，应各自立独立方案推进。
> 创建日期：2026-09-22

---

## D1 产品代码单字母变量改语义名

| 字段 | 内容 |
|------|------|
| **现状** | 全仓产品代码中散布单字母变量 `q`/`p`/`s`/`v`/`k` 等，语义不明 |
| **影响** | 可读性差，新读者需逐处推断含义；grep 难以按语义定位 |
| **跳过原因** | 全仓散布，改动面极大且纯命名性，风险高于收益 |
| **建议推进** | 分包逐步改：先 agent-core → agent-runtime → 各 application，每包改完跑该包测试确认绿 |
| **优先级** | Low（纯可读性，无功能影响） |

---

## D2 knowledge-service 裸阈值集中到 conf/（已完成）

| 字段 | 内容 |
|------|------|
| **现状** | 15 个硬编码阈值已全部外部化到 retrieval.yaml + Settings |
| **影响** | 调参须改配置而非代码；实验可追溯；与 M3 目标一致 |
| **完成方式** | retrieval.yaml channels.* 加 top_k/candidate_limit + item_confirm 段 + Settings 加 knowledge_max_context_chars；节点改读配置 |
| **优先级** | ✅ 已完成 |

---

## D3 zhanggui-zhiku setuptools → hatchling 迁移（已完成）

| 字段 | 内容 |
|------|------|
| **现状** | knowledge-service（原 zhanggui-zhiku，已改名）已从 setuptools 迁移到 hatchling |
| **影响** | 构建后端统一（全仓 9 包均 hatchling） |
| **完成方式** | 改 `build-backend` 为 `hatchling.build` + `[tool.hatch.build.targets.wheel] only-include = ["knowledge_service"]` + 删 `[tool.setuptools.*]` |
| **优先级** | ✅ 已完成 |

---

## D4 ruff ignore 存量基线逐包收窄

| 字段 | 内容 |
|------|------|
| **现状** | 各包 pyproject.toml 有 ruff ignore 基线（如 E402/E731/F841 等），部分豁免可能已不需要 |
| **影响** | 豁免过宽会漏掉新引入的违规；豁免不可全清（存量代码依赖豁免才绿） |
| **跳过原因** | 需逐包逐条评估：每条 ignore 删除后跑 ruff，看是否仍有违规 |
| **建议推进** | 逐包处理：① 删一条 ignore → ② `ruff check` → ③ 若绿则永久删，若红则修复违规或保留豁免 → ④ 提交。记忆 `project_agent-runtime-ruff-ignore-baseline` 有基线记录 |
| **优先级** | Low（豁免本身不违规，只是理想收窄） |

---

## D5 agent_core 注释中应用名改泛化表述

| 字段 | 内容 |
|------|------|
| **现状** | agent_core 中 81 处注释引用 `app` / `deepagents` 等具体应用名 |
| **影响** | 注释读起来像 agent_core 依赖具体应用，实际是框架无关内核 |
| **跳过原因** | 81 处中多数是历史溯源注释（"下沉自 deepagents..."、"此前实现在 app/..."），有档案价值，不应改 |
| **建议推进** | 仅改"当前时态"引用（如"app 专属"→"宿主应用专属"），保留"历史溯源"注释不动。需人工逐条判断属于哪类 |
| **优先级** | Low（注释准确性，无功能影响） |

---

## D6 agent_server/api/routes.py 按业务域拆分（已完成）

| 字段 | 内容 |
|------|------|
| **现状** | routes.py 已拆分为 5 个子模块（health/query/import/sql/session），本文件为聚合入口 |
| **影响** | 各域可独立演进，单文件不再过大 |
| **完成方式** | 按域提取子模块 → routes.py 聚合 include_router → 测试 mock 路径更新为 query_router |
| **优先级** | ✅ 已完成 |

---

## D7 清理裸 `except Exception:`（✅ 门禁已恢复为启用态 + ratchet 基线；存量待逐文件烧除 —— 见 `arch-audit-2026-09-24.md` P0-4 / `plan-p0-4-blind-except-ratchet-2026-09-24.md`）

| 字段 | 内容 |
|------|------|
| **现状（2026-09-24 复核更正）** | 本条原记录「全仓 211 处 BLE001 违规已全部标注 `# noqa: BLE001` + 上下文注释」**已失效**：提交 `92ba46f`（标题「清理 358 处 BLE001 死代码 noqa」）主动删除了这些 noqa 留痕，改由根 `pyproject.toml` 的 `ignore = [..., "BLE001", "S110", ...]` **全局关闭**该规则。当前受管代码（`packages/`、`applications/`、`tests/`、`scripts/`、`eval/`）中 `# noqa: BLE001` = **0 处**，`courses/`（未入库）亦为 0。 |
| **影响（倒退风险）** | 全局 `ignore` 使仓内**不再有任何痕迹**标明哪些位置做了宽捕获及原因，后续审查只能 `grep "except Exception"`；且**新写的裸 except 不再被任何门禁拦截**，同类问题可无限复发 —— 与 D4「逐包收窄 ruff ignore」方向相反。 |
| **原始完成方式（历史记录，已被上述反转覆盖）** | 自动脚本批量添加 `# noqa: BLE001` + 手动修复 7 处脚本未覆盖模式 + 修复 control_plane.py 缩进回归。 |
| **优先级** | 🟡 **M1-only 稳态**（2026-09-24 策略修订，经用户复核）：已抛弃「全局豁免」，改为 6 份配置均**启用** `BLE001/S110` + legacy 入各包 `per-file-ignores` 文件级基线。**放弃逐点烧法**：曾对 agent-core/agent-runtime 逐点加 `# noqa: BLE001` 并删基线，但逐点 noqa 依附 `BLE001` 是否常驻 select（历史 `3ccc90e` 加 → 移出 → `92ba46f` 清 → 反复 churn），故已 `git restore` 回退源码、基线由 ruff 真值重建。现态：**6 包源码干净 + 文件级基线豁免**，仅保留**无 noqa 的安全窄化**（纯导入守卫→`except ImportError`、`json.loads`→`except (ValueError, TypeError)`）。agent-core `pytest 200 passed`、agent-runtime `539 passed`。🔧 **真实降量轮次（2026-09-24，`plan-p0-4-blind-except-real-reduction-2026-09-24.md`）**：经用户逐站核查后执行桶 A 安全窄化——knowledge-service 5 文件 9 站点（requests/IO/import 探测/`int()`），其中 locustfile/node_pdf_to_md/test_tracing 3 文件清零脱基线（ks 基线 24→21），`pytest 41 passed/6 skipped`；桶 B（删冗余交全局 handler）因丢 session_id 日志上下文、收益边际→本轮跳过；桶 C（后台任务/SSE/探针/可选通道降级，含 `import_exhibition_corpus:217` HTTP 批次降级）维持豁免。全局 handler 实测仅 1/6 应用有→仓库级大降量需先补各应用 handler（P2 独立）。门禁常驻防新增盲捕获，存量宽捕获为文件级豁免，**不再追求逐点清零**。 |

---

## D8 zhanggui-zhiku/core/config.py 评估引入 pydantic-settings

| 字段 | 内容 |
|------|------|
| **现状** | zhanggui-zhiku 用手写 `Settings` 类 + `os.getenv` 读取环境变量 |
| **影响** | 无类型校验、无默认值集中管理、与 agent_core 的 `KernelConfig`（类型化 env）风格不一致 |
| **跳过原因** | 评估性任务，迁移需改 Settings 基类为 `pydantic_settings.BaseSettings` + 调整所有字段定义 + 验证 env 加载顺序 |
| **建议推进** | ① 加 `pydantic-settings` 依赖 → ② Settings 改继承 `BaseSettings` → ③ 字段加类型注解和默认值 → ④ 验证 `.env.example` 所有变量仍正确加载 → ⑤ 跑 zhanggui 测试 |
| **优先级** | Low（功能无影响，纯配置风格统一） |

---

## 汇总

| ID | 任务 | 优先级 | 建议批次 |
|----|------|--------|----------|
| D1 | 单字母变量改语义名 | Low | 可随各包日常改动顺带改 |
| D2 | knowledge-service 裸阈值集中 | ✅ 已完成 | 已完成 |
| D3 | setuptools→hatchling | ✅ 已完成 | 已完成 |
| D4 | ruff ignore 收窄 | Low | 逐包日常改动顺带 |
| D5 | agent_core 注释泛化 | Low | 人工逐条判断 |
| D6 | routes.py 拆分 | ✅ 已完成 | 已完成 |
| D7 | 清理裸 except | 🟡 M1-only 稳态 + 桶 A 窄化（真实降量轮次） | 全局豁免已改**启用 + 文件级基线豁免**（见 `plan-p0-4-blind-except-ratchet-2026-09-24.md`）；逐点 noqa 已回退；**真实降量**：agent-core 6 处 + knowledge-service 桶 A 5 文件（3 文件脱基线，见 `plan-p0-4-blind-except-real-reduction-2026-09-24.md`）；余下承重降级维持豁免 |
| D8 | pydantic-settings 评估 | Low | 独立小任务 |
| D9 | exhibition llm_client.py 收敛到 agent_core.llm | ✅ 已完成 | OpenAICompatibleProvider.build() 替代直接 ChatOpenAI |
| D10 | zhanggui ApiReranker 收敛到 agent_core.resilience.retry | ✅ 已完成 | 已完成 |

---

## D9 exhibition llm_client.py 收敛到 agent_core.llm（已完成）

| 字段 | 内容 |
|------|------|
| **现状** | `exhibition-agent/skill_loader/llm_client.py` 已改用 `agent_core.llm.OpenAICompatibleProvider.build()` 构造 ChatOpenAI，经 `FallbackChatModel` 包装主备降级 |
| **影响** | 与 wenda 实现一致；agent_core 的 LLM 抽象层被 exhibition 复用；无残留直接 `langchain_openai` 导入 |
| **完成方式** | `_build_llm()` 中 `ChatOpenAI(...)` → `OpenAICompatibleProvider().build(model=..., api_key=..., base_url=..., temperature=...)`；`chat_completion()` 接口不变，ExhibitionAgent 无需改 |
| **优先级** | ✅ 已完成 |

---

## D10 zhanggui ApiReranker 收敛到 agent_core.resilience.retry（已完成）

| 字段 | 内容 |
|------|------|
| **现状** | `knowledge-service/lm/siliconflow_client.py` 的 `_post_json` 已改用 `agent_core.resilience.retry` 装饰器，消除手写重试循环 |
| **影响** | 与 `agent_server/rag/rerank.py` 的 ApiReranker 重试策略统一（均经 agent_core.resilience.retry） |
| **完成方式** | `_post_json` 内部 `@retry` 装饰器替代手写循环；429/5xx 转 RuntimeError（被 retry 重试），4xx 抛 HTTPError（不重试）；函数签名与异常类型向后兼容 |
| **优先级** | ✅ 已完成 |
