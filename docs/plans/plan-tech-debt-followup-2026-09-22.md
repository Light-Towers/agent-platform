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

## D2 zhanggui-zhiku 节点函数裸阈值集中到 conf/

| 字段 | 内容 |
|------|------|
| **现状** | zhanggui-zhiku 的 12 个 LangGraph 节点函数内硬编码检索阈值（top_k、相似度下界、重排数量等） |
| **影响** | 调参须改代码而非配置，实验不可追溯；与 M3「配置外置」目标不一致 |
| **跳过原因** | 涉及 12 个节点函数，需逐个提取阈值、改读 `settings.xxx`、验证调用链不断 |
| **建议推进** | 立独立方案，按节点逐个迁移：① 列出所有硬编码阈值 → ② 在 `core/config.py` 加对应字段 → ③ 逐节点改读 settings → ④ 跑 zhanggui 测试 |
| **优先级** | Medium（影响实验可追溯性，M3 目标） |

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

## D6 agent_server/api/routes.py 按业务域拆分

| 字段 | 内容 |
|------|------|
| **现状** | `agent_server/api/routes.py` 单文件承载所有路由（query/import/sql/session/health） |
| **影响** | 单文件过大，改动互相影响；按域拆分后各域可独立演进 |
| **跳过原因** | 路由拆 5 个子模块（query_router/import_router/sql_router/session_router/health_router），涉及 import 重构 + main.py 注册调整 + 测试 import 路径更新 |
| **建议推进** | ① 按域提取子模块 → ② main.py 改 `include_router` → ③ 测试 import 路径更新 → ④ 跑 agent_server 测试 |
| **优先级** | Low（功能无影响，纯可维护性） |

---

## D7 清理 87 处裸 `except Exception:`

| 字段 | 内容 |
|------|------|
| **现状** | 全仓约 87 处 `except Exception:` 或 `except Exception as e:`，不区分异常类型 |
| **影响** | 可能吞掉编程错误（TypeError/AttributeError/NameError 等），掩盖 bug |
| **跳过原因** | 需逐个区分：可恢复异常（网络/超时/连接）保留宽捕获；编程错误应收窄为具体异常类型。改错会吞掉本该抛的 bug |
| **建议推进** | 分批处理：① 按文件列出所有裸 except → ② 逐个分析上下文判断属于可恢复还是编程错误 → ③ 可恢复加注释说明、编程错误收窄异常类型 → ④ 跑测试确认未误吞 |
| **优先级** | Medium（误吞编程错误会掩盖 bug，但改动风险也高） |

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
| D2 | zhanggui 裸阈值集中 | Medium | 独立方案（M3 目标） |
| D3 | setuptools→hatchling | ✅ 已完成 | 已完成 |
| D4 | ruff ignore 收窄 | Low | 逐包日常改动顺带 |
| D5 | agent_core 注释泛化 | Low | 人工逐条判断 |
| D6 | routes.py 拆分 | Low | 独立小任务 |
| D7 | 清理裸 except | Medium | 分批逐文件处理 |
| D8 | pydantic-settings 评估 | Low | 独立小任务 |
| D9 | exhibition llm_client.py 收敛到 agent_core.llm | Medium | 接口根本不同（httpx 异步 vs langchain ChatOpenAI），需重大重构 |
| D10 | zhanggui ApiReranker 收敛到 agent_core.resilience.retry | Medium | 双实现模式不同（内联 retry vs _post_json 无 retry），风险高 |

---

## D9 exhibition llm_client.py 收敛到 agent_core.llm

| 字段 | 内容 |
|------|------|
| **现状** | `exhibition-agent/skill_loader/llm_client.py` 仍用 httpx 异步直调 OpenAI API，未经 `agent_core.llm.OpenAICompatibleProvider` |
| **影响** | 与 wenda（已收敛）实现不一致；agent_core 的 LLM 抽象层未被 exhibition 复用 |
| **跳过原因** | exhibition 用 httpx 异步直调 OpenAI API，wenda 用 langchain ChatOpenAI，接口根本不同，需重大重构而非简单替换 |
| **建议推进** | ① 评估 exhibition 的 httpx 调用是否可改为 langchain ChatOpenAI → ② 若可，改用 `OpenAICompatibleProvider.build()` → ③ 跑 exhibition 测试确认契约不变 |
| **优先级** | Medium |

---

## D10 zhanggui ApiReranker 收敛到 agent_core.resilience.retry

| 字段 | 内容 |
|------|------|
| **现状** | `zhanggui-zhiku/lm/siliconflow_client.py` 的 ApiReranker 用 `_post_json` 无 retry，与 `agent_server/rag/rerank.py` 的 ApiReranker（已改用 `agent_core.resilience.retry`）是双份实现 |
| **影响** | 同一 rerank 逻辑两套实现，维护成本翻倍；zhanggui 侧无 retry 保护 |
| **跳过原因** | 双实现模式不同（agent_server 内联 retry + resilience.retry，zhanggui 用 _post_json 无 retry），统一需先对齐调用模式，风险高 |
| **建议推进** | ① 对齐 zhanggui ApiReranker 的 `_post_json` 调用为可直接加 `@retry` 的形态 → ② 引入 `agent_core.resilience.retry` → ③ 跑 zhanggui 测试确认 rerank 行为不变 |
| **优先级** | Medium |
