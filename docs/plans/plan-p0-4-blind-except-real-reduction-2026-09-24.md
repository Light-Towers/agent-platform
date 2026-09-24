# P0-4 盲捕获「真实降量」轮次方案（2026-09-24）

> 前置：M1 棘轮已落地（6 份配置启用 `BLE001/S110` + 整包 `per-file-ignores` 文件级基线豁免）；M2「逐点 noqa 烧除法」经用户复核**已放弃**（见 `plan-p0-4-blind-except-ratchet-2026-09-24.md` 策略修订）。
> 本方案是**取代逐点烧法**的第三条路：不做无意义的 noqa 标注，而是**真实降低盲捕获存量**——只在「改了对正确性有净收益且不改变行为」处动手，全程**零逐点 noqa**。
> 状态：**✅ 已批准（2026-09-24，经用户逐站实地核查后修订）——本轮执行范围 = 桶 A（只做安全窄化）**；桶 B 不做（删后丢 session_id 可观测性、收益边际）；桶 C 维持基线豁免。下表已修正初稿的 **1 处 P0 定性错误（`import_exhibition_corpus.py:217` 误判为文件读）+ 2 处行号/依据错误（`node_pdf_to_md` 156/239 对调、:134 漏计显式 `raise RuntimeError`）**。

## 1. 目标

把 legacy 盲捕获（`except Exception` / `try…except…pass`）从「豁免存量」转化为三类**有依据的处置**，让基线单调下降，且不引入依赖 `BLE001` 是否常驻 `select` 的逐点 noqa：

1. **可窄化** → 改成具体异常类型（真实提升正确性：宽捕获当前会顺带吞掉非目标异常）。
2. **纯冗余** → 删除 `try/except`，让异常冒泡到**全局脱敏 handler**（仅在有 handler 的请求栈内适用）。
3. **承重降级** → **保留宽捕获 + 留在文件级基线**（后台任务 / SSE / 探针 / 可选通道降级，删了丢功能、且全局 handler 接不到）。

## 2. 关键勘察结论（决定本路适用范围）

- **全局脱敏 handler 覆盖面 = 1/6 应用**：仅 `knowledge-service` 注册 `add_exception_handler(Exception, unhandled_exception_handler)`（`api/errors.py`，`main.py:52`）。`agent_server` / `agent_federation` / `exhibition-agent` / `nl2sql-service` / `kefu-service` **均无**。
  - 推论：**「删纯冗余交全局 handler」只在 knowledge-service 请求栈内成立**。其它应用若删 `except`，异常退化为 Starlette 默认 500（**泄露内部细节、不脱敏**），属**不安全降量**——要覆盖须先给这 5 个应用补统一 handler（独立、更大的架构改动，见 §6）。
- **`agent-core` / `agent-runtime` 是库无 HTTP 边界**：其宽捕获多为「可选依赖 / 后端优雅降级」，承重，仅安全窄化部分适用（上一轮已做 6 处），**不进本轮删除桶**。
- **knowledge-service 62 处结构**（`--config 'lint.per-file-ignores={}'` 实测枚举）：绝大多数落在 LangGraph 节点 / `BackgroundTasks` / SSE 生成器 / 探针 / 可选通道（Neo4j/HyDE/rerank/embedding 回退）——**全局 handler 接不到**（后台孤儿任务、流式生成器）或**删了丢部分降级能力**，属承重桶。

## 3. 三桶处置规则与代表站点（knowledge-service）

### 桶 A：可窄化（改具体异常，零行为变更，最高优先）
识别：`try` 体内**只调用**了明确只抛特定异常的纯操作。

| 站点 | try 体实际 | 窄化为 | 行为影响 |
|------|-----------|--------|---------|
| `clients/milvus_utils.py:68` | `int(x)` | `(ValueError, TypeError)` | 零变更 |
| `node_pdf_to_md.py:134` | `upload_session.put` + 显式 `raise RuntimeError`（:130） | `(requests.RequestException, RuntimeError)` | **行为等价**（:130 的 RuntimeError 仍被捕获重包装），非“零变更”——因 try 体含控制流 raise；但排除 TypeError 等真 bug |
| `node_pdf_to_md.py:156` | `requests.get`（轮询） | `requests.RequestException` | 零变更 |
| `node_pdf_to_md.py:239` | `shutil.rmtree` | `OSError` | 零变更 |
| `node_pdf_to_md.py:339` | `open(md).read()` | `(OSError, UnicodeDecodeError)` | 零变更 |
| `benchmark/locustfile.py:46` | `open(golden).read()` + `json.loads` | `(OSError, ValueError)` | 零变更（JSONDecodeError/UnicodeDecodeError 均 ValueError 子类） |
| `tests/unit/test_tracing.py:33/39` | OTel SDK import 探测 | `ImportError` | 零变更 |
| `tests/unit/test_security_guards.py:47` | starlette/errors import 探测 | `ImportError` | 零变更 |

> （初稿误列的 `scripts/import_exhibition_corpus.py:217` 已核实为 **HTTP 上传+轮询批次降级**→改归桶 C，见下）。**执行纪律**：每处改后 `except` 类型集合必须**覆盖 try 体内所有正常抛出**，宁可少窄不可漏抛（漏抛=新崩溃路径，红线禁止）。

### 桶 B：纯冗余可删（删 try/except，冒泡到全局 handler）
识别：在**请求调用栈内**（非后台/SSE），`except Exception → logger.exception + raise HTTPException(500, 泛化文案)`，删除后由 `unhandled_exception_handler` 产出等价的脱敏 500。

| 站点 | 现状 | 处置 | 权衡 |
|------|------|------|------|
| `api/query_router.py:352`（get_history） | `except Exception → raise HTTPException(500,"获取会话历史失败")` | 删 `try/except`，直接冒泡 | 代价：错误文案从「获取会话历史失败」变泛化 `INTERNAL_ERROR`；detail 已 `logger.exception` 入日志 |

> **本桶实测仅 1 处**（其它 router 站点要么在后台任务、要么是部分降级不 re-raise）。**❌ 本轮不做**：核查发现删 `try/except` 后虽由 `unhandled_exception_handler` 兑同等脱敏 500，但该 handler 日志只记 method+path——**丢失原 `logger.exception("history error for session %s")` 的 session_id 上下文**，降低可观测性。1 处、收益边际、不划算——桶 B 整桶本轮跳过。

### 桶 C：承重降级（保留宽捕获，留文件级基线，不动源码）
后台任务顶层（`import_router.py:130` run_graph_task、`query_router.py:157` run_query_graph 标 FAILED+SSE）、SSE 生成器（`sse_utils.py:100`）、就绪探针（`query_router.py:114`）、客户端工厂降级（`milvus_utils.py:29/49`、`minio_utils.py:48`、`neo4j_utils.py:29/92`）、可选检索通道部分降级（`node_query_kg`/`node_rerank`/`node_rrf`/`node_search_embedding*`/`node_bge_embedding`）、嵌套 span 记录守卫（`query_router.py:161`）、**导入脚本批次降级（`scripts/import_exhibition_corpus.py:217`——try 体为 `upload_one`+`poll_status` 完整 HTTP 导入流程，单文件失败记 error 状态继续跑批，窄化会漏抛网络异常炸掉整个循环）**。**保持原状，基线豁免**。

## 4. 迁移策略

1. 逐文件处理桶 A + 桶 B（knowledge-service），**每文件**：改后从 `pyproject.toml` 的 `per-file-ignores` 删除该文件条目（若其所有站点都已处置）或保留（仍有桶 C 站点）。
2. 桶 C 站点所在文件的基线条目**保留不动**。
3. 全程不写任何 `# noqa: BLE001`（源码保持零逐点 noqa 的原则）。
4. `agent-core` / `agent-runtime` / 其它 4 应用：**本轮不动**（无 handler 或库语义）。

## 5. 验收标准（硬性）

- **正确性优先**：桶 A 每处窄化后 `pytest applications/knowledge-service`（含节点/检索/导入相关用例）全绿；窄化类型集合必须真覆盖 try 体抛出，禁止为「凑删基线」收窄到漏抛。
- **降量自证**：处理完对已完全脱离基线的文件，`ruff check applications/knowledge-service --config 'lint.per-file-ignores={}'` 报出的残留站点数 = 仍留在基线的桶 C 站点数（单调递减，可核对）。
- **门禁常驻**：`ruff check .` 全绿；源码 `grep 'noqa: BLE001'` = **0**（延续 M1-only 原则）。
- **文档防漂移**：`check_doc_sync.py` 0 警告；plan/审计/D7 反映本轮实际降量（桶 A 已处置、桶 B 跳过、桶 C 仍豁免）。
- **禁止**：删用例 / 放宽断言凑绿；为降量改变任何 happy-path 行为。

## 6. 已拍板决策（2026-09-24 用户核查后）

1. **本轮只执行桶 A**（knowledge-service 安全窄化 5 文件：milvus_utils / node_pdf_to_md / locustfile / test_tracing / test_security_guards）；**桶 B 跳过**（丢 session_id 日志上下文、收益边际）。
2. **为其余 5 应用补统一脱敏 handler** → 降为 **P2 独立方案**，本轮不并入。
3. **`agent-core`/`agent-runtime` 可选通道宽捕获** → 维持文件级基线豁免（承重，不降量）。

## 7. 规模与风险小结

| 桶 | 站点量级 | 行为风险 | 本轮 |
|----|---------|---------|------|
| A 窄化 | knowledge-service 5 文件 9 站点、agent 已做 6 处 | 低（严守覆盖校验） | **✅ 做** |
| B 删冗余 | 实测 1 处 | 中（丢 session_id 日志上下文） | ❌ **跳过** |
| C 承重 | 其余 ~53 处（含新归入的 import_exhibition:217） | 高（删即丢降级/崩后台） | **不动，留基线** |

**核心诚实结论**：受「全局 handler 仅 1/6 应用」+「多数盲捕获是承重降级」两条约束，本轮**真实降量以桶 A 窄化为主**，桶 B 删冗余仓库级收益有限；想要大范围降量必须先补各应用 handler（独立轮次）。

## 8. 执行结果与全量扇扣自证（2026-09-24）

**桶 A 已落地**（5 文件 9 站点）：node_pdf_to_md（134/156/239/339）、milvus_utils:68、locustfile:46、test_tracing（33/39）、test_security_guards:47。其中 **node_pdf_to_md / locustfile / test_tracing 3 文件清零脱基线**（ks 基线 24→21）。

**全量扇扣**（针对初稿标“非穷举”的剩余站点）：逐站读完整 try 体跨**每一类**（导入节点 / 查询节点 / client 工厂 / 路由 / SSE / 脚本 / 测试）。结论：剩余 **53 处均为承重降级**，无一为单原子操作可窄化点——try 体要么是多步编排（如 `node_item_name_recognition` 整步 LLM 链、`node_rerank` 打分降级），要么含**显式 `raise`**（`bge:120` raise ValueError、`import_milvus:326` raise、`pdf:134` 已处理），要么是错误处理器内 best-effort 读（`siliconflow:76`）。→ **无额外可安全窄化点，knowledge-service 真实降量到此完结**。

**降量自证**：`ruff check applications/knowledge-service --config 'lint.per-file-ignores={}'` 实测残留 = **53 处 / 21 文件**，与保留的 **21 条基线 1:1 对应**（无过宽豁免、无漏网）。全局 `ruff check .` 绿；0 stray noqa；`pytest test_tracing/test_security_guards` 41 passed/6 skipped（未把 skip 变 error）。

**待办（P2、不属本轮）**：给 agent_server / agent_federation / exhibition-agent / nl2sql-service / kefu-service 补统一脱敏 handler（才能仓库级启用桶 B）；需先逐应用研读现有 main/错误处理结构再定方案。
