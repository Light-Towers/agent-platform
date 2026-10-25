# 记忆模块缺陷补救方案（2026-10-21）

| 项 | 内容 |
|----|------|
| 日期 | 2026-10-21 |
| 状态 | Proposed（待评审；**不授权编码**） |
| 范围 | `agent-core/memory` + `agent-runtime/memory_*` + `eval/` 记忆侧 + 门禁布线 |
| 上游 | `plan-memory-hardening-2026-09-27.md`（G1–G10 / T0–T8，T0/T1 已执行）+ ADR-0004 / ADR-0005 + 2026-10-19~21 三轮评审（测试分层盘点 / DSH 对照 / Codex 源码对照） |
| 结论 | **不重构**。12 项开放缺陷分四批补救，顺序为「先让质量可度量（批次 A/C），再补治理与性能（批次 B），最后收口（批次 D）」；Codex 对照出的 4 个增强项全部降级 P2 候选，本篇不授权 |

---

## 1. 结论摘要

1. **2026-09-27 加固计划的开放项全部核实为「仍未执行」**：T2（向量召回）、T3（去重）、T4（provenance）、T5（审计日志）、T6（sink 增量化）、T7（指标）、T8（契约收口）七项，本文逐一复核代码后确认零落地（证据见 §2）。T0/T1 已入主干，G8（评分双轨）已由 ADR-0005 §6 决策 2 关闭，本篇不重复立项。
2. **本轮评审新发现 4 项计划外缺陷**（D9–D12）：记忆质量回归不受任何门禁约束、无记忆侧 golden 集、PG 闭环无 e2e 覆盖、遗忘阈值无基线数据。其中「无 golden 集」是**批次 A 的前置阻塞**——没有基线就换召回路径等于盲改。
3. **Codex 源码对照（openai/codex `codex-rs/memories/`）产出 4 个增强候选**，全部登记为 P2、不授权：读取用量驱动巩固、brief/full 分层注入、记忆资产人可审计、行号级 citation。判断依据：前两个是真闭环值得借，后两个在企业多租户定位下收益/成本比存疑（§5）。
4. **总工作量估计 8–12 人/日**，四批可独立合流，每批独立验收（§6）。

---

## 2. 状态复核（2026-10-21 实测，防重复立项）

| 编号 | 内容 | 复核结论 | 证据 |
|------|------|---------|------|
| G1/T1 | episodic/procedural 租户维度 | ✅ 已关闭 | migration `010_episodic_tenant.up.sql` + `tests/ha/test_tenant_isolation_real_pg.py` |
| G8 | 评分双轨 | ✅ 已关闭（决策关闭，非实现关闭） | ADR-0005 §6 决策 2「不替换」；§6.1「评分下沉不再必要」 |
| 两链并行 | agent_server 同进程两套记忆 | ✅ 已关闭（设计定性） | ADR-0005 §2.3「不合并，协议下沉、实现留宿主」；T0 已落地 |
| D7 | `EXECUTION_MEMORY_KERNEL_CONTRACT` 开关漂移风险 | ✅ 已关闭 | 全仓 grep 该环境变量**零匹配**——开关已移除，契约改由 `runtime_checkable` 协议 + `test_execution_contract.py` 静态兜底 |
| G2/T2 | Episodic 向量召回 | ❌ 开放（D1） | migrations 至 `012` 无 episodic embedding 列；`embedding_recall.py` 只是补丁；`memory_pg.py` 主路径仍 ILIKE |
| G3/T3 | content_hash 去重 | ❌ 开放（D2） | 全仓 `content_hash` 零匹配 |
| G4/T4 | provenance 三列 | ❌ 开放（D3） | `injected_by` / `source_execution_id` 零匹配 |
| G5/T5 | memory_change_log + 真批删 | ❌ 开放（D4） | `memory_change_log` 零匹配；`memory_decay.py:53-66` 仍 `list_all(limit=1000000)` + 逐条循环删 |
| G6 | 衰减 O(n) 逐条删 | ❌ 开放（D5，同 T5 一并修） | 同上 |
| G7/T6 | ProceduralSink 全量扫描 | ❌ 开放（D6） | `memory_sink.py:91` `list_all(tenant_id=tenant)` 无水位 |
| G9/T7 | 生产指标 | ❌ 开放（部分并入口 D12） | `memory_metrics.py` 不存在；`eval/` 无记忆侧指标产物 |
| G10/T8 | UserSemanticStore 悬空 | ❌ 开放（D7） | `semantic_memory.py:66` 仍仅 ABC；非 mock 实现零个 |

---

## 3. 开放缺陷全量清单

| # | 级别 | 缺陷 | 后果 | 证据（文件:行） | 来源 |
|---|------|------|------|----------------|------|
| D1 | **P0** | Episodic 召回主路径 = `ILIKE` 关键词 + `ORDER BY importance DESC`，向量能力只在补丁里；语义改写即召回失败 | 执行经验「存了却找不到」，程序性记忆沉淀管道的出口是瞎的 | `memory_pg.py` recall；`embedding_recall.py`；migrations 无列 | 计划 G2/T2 |
| D2 | P1 | 无 `content_hash`，相同执行反复沉淀 | Episode 表单调膨胀，召回信噪比下降 | 零匹配 | G3/T3 |
| D3 | P1 | 无 provenance（`source_execution_id` / `injected_by` / `confidence`） | 投毒记忆无法溯源、无法按注入方降权（OWASP ASI06） | 零匹配 | G4/T4 |
| D4 | P1 | 无 `memory_change_log`，`DELETE` 直接生效 | GDPR「可证明删除」不成立，误删无回滚 | 零匹配；`typed.py` forget 直删 | G5/T5 |
| D5 | P1 | 衰减 `list_all(limit=1e6)` + 逐条 delete | 内存 O(n) + 往返 O(n)，万级即劣化 | `memory_decay.py:53-66` | G6 |
| D6 | P1 | `ProceduralSink` 每 10 次执行 `list_all()` 全量扫描 | 挖掘成本随记忆量线性涨 | `memory_sink.py:91` | G7/T6 |
| D7 | P1 | `UserSemanticStore` 无生产实现（ABC + 2 个 mock） | 「用户事实」随时可能被另写一份存储 → 真双份真相源 | `semantic_memory.py:66-80` | G10/T8 |
| D8 | P1 | `MemoryType.episodic`（情节型**事实**）与 `MemoryCategory.EPISODIC`（一次**执行轨迹**）同名不同义 | 跨包阅读即误判，已两次险些踩中（ADR-0005 §1.3 登记） | ADR-0005 §1.3 | 本轮评审 |
| D9 | **P0** | 记忆质量评测（`eval/memory_reuse_llm.py`）只在手动工作流 `eval-llm.yml`，**任何 CI 门禁都不跑** | 召回/抽取改坏 → 质量退化静默进主干 | `.github/workflows/eval-llm.yml:1,65` | 本轮评审 |
| D10 | **P0** | 无记忆侧 recall@k golden 集（RAG 侧有 `golden_queries` + `compare_runs --fail-on-regression` + 冻结基线，记忆侧一个对标物都没有） | 换召回路径（D1）**没有基线可对比**，是批次 A 的阻塞前置 | `eval/` 目录盘点 | 本轮评审 |
| D11 | P1 | e2e 闭环（5 次执行→沉淀→挖掘→升级→召回）全走 `InMemoryEpisodicStore` | PG 上的写真/读/挖掘质量零覆盖，SQL 谓词错误 mock 抓不到 | `test_memory_e2e.py:15,23,48,97` | 本轮评审 |
| D12 | P2 | 遗忘阈值 `0.1` / `30 天` 仍是无基线常量（已可 env 配置，但取值无依据） | 治理动作要么误杀要么永不触发，不可解释 | `typed.py:383-404` | 本轮评审 |

---

## 4. 分缺陷方案（含权衡选项）

### D1（P0）Episodic 召回升级为向量——三个选项，推荐选项 1 + D10 前置

| 选项 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **1（推荐）** | 加 `summary_embedding vector({{vector_dim}})` 列 + HNSW 索引；宿主层注入 embedding（守 ADR-0004「内核不下沉 embedder」）；列为 NULL 时降级 ILIKE + `three_factor_score` | 与 `typed.py` 同代能力；指标与语义路一致 | 破坏性迁移；维度须与宿主 embedder 对齐 |
| 2 | 把 `embedding_recall.py` 补丁扶正为主路径，ILIKE 兜底 | 不动表结构 | 双路径并存，复杂度长期化 |
| 3 | 只建 golden 量化现状，不换 | 零风险 | 质量问题继续挂着 |

**拍板要求**：选项 1，但**批次顺序上 D10 golden 先行**——golden 冻结基线 → 换路径 → 同 golden 复跑必须零退化才合流。维度用 migrations 既有 `{{vector_dim}}` 模板占位（`001_baseline.up.sql:13` 同款），不硬编码 1536。

### D2（P1）零成本去重

- `content_hash = md5(task_summary + "\|" + sorted(key_steps))`；UNIQUE 索引 `(tenant_id, content_hash) WHERE content_hash IS NOT NULL`。
- `save` 改 `ON CONFLICT DO UPDATE SET importance = GREATEST(...), updated_at = ...`。
- 对齐 Mem0 md5 模式，零 LLM 成本；与 D1 同库迁移，合入同一 migration。

### D3（P1）provenance 三列

- `episodic_memories` + `memories` 同步加 `source_execution_id` / `injected_by DEFAULT 'system'`（user\|model\|tool\|system）/ `confidence DEFAULT 1.0`。
- `typed.remember_typed` 加可选形参（默认值不破坏现有调用）。
- 排序对 `injected_by='tool'` 降权——最小投毒防护，**不**做完整的 MINJA 对抗（超出范围）。

### D4（P1）审计日志 + D5（P1）衰减批量化——同批同迁移

- 新建 `memory_change_log`（对齐 Mem0 history 十列 + 补 `tenant_id`）：所有写/删路径记一条；GDPR 删除写**一条 bulk 审计**而非逐条。
- D5：`DELETE FROM episodic_memories WHERE tenant_id=%s AND created_at < %s` 批删；容量淘汰改 `ORDER BY importance ASC LIMIT %s` SQL 删除，删掉 `memory_decay.py:53-66` 的内存循环。

### D6（P1）ProceduralSink 增量化

- 新增 `list_since(tenant_id, since_ts)` store 方法（SQL `WHERE tenant_id=%s AND created_at > %s`）。
- 水位 `last_extract_at` **存 `metadata` 表**（`001_baseline.up.sql` 已建该表，实测存在）；不选「内存 + 启动重建」——重启即丢水位会导致重复挖掘候选 Skill。

### D7（P1）UserSemanticStore 契约收口

- **选项 1（推荐）**：`CoreTypedUserSemanticStore(UserSemanticStore)` 薄适配器，内部调 `agent_core.memory.typed` 的 `recall_typed` / `remember_typed`，不自建表不自建评分；驱动遵守 ADR-0004 决策 4（接收宿主 psycopg 池，不新建池）。
- 选项 2：禁止性注释封死（「暂无生产实现，禁止自行实现后端」）。
- ADR-0005 §6 项 3 已拍板「单独立项（归 T8）」，**按选项 1 执行，不重开决策**。

### D8（P1）同名不同义收敛

| 选项 | 做法 | 影响面 |
|------|------|--------|
| **1（推荐）** | runtime 侧 `MemoryCategory.EPISODIC` → `MemoryCategory.TRAJECTORY`（语义最准：一次执行的完整轨迹） | **11 处引用**，全在 runtime + agent_server 宿主侧，不动内核契约 |
| 2 | 内核侧 `MemoryType.episodic` → 改名 | 6 处引用，但改的是 `agent-core` 公开 API，federation/agent_server 连带 |
| 3 | 维持现状 + docstring/测试锁定（当前状态） | 0 |

**前置动作**：改名前全仓数两处引用数复核（现值 11 / 6，2026-10-21 实测）；若 runtime 侧超 20 处则退选项 3 并加跨包误用 lint 规则。内核侧无论选哪项都补一句 docstring 互斥声明。

### D9（P0）质量评测入门禁 + D10（P0）golden 集 + D11（P1）PG 闭环——同批「质量可度量」

**D10 先行（阻塞项）**：
- 新建 `eval/memory_golden.jsonl`：10–20 条「query → 应召回的 episode_id 列表」；3 条租户隔离对（tenantA 的记忆 tenantB 不得召回）。
- 参照 RAG 侧 `compare_runs.py --fail-on-regression` 写记忆侧对标脚本：改前跑一遍冻结基线 → 改后复跑 → recall@k 下降即 `rc=1`。**先量化 ILIKE 现状再谈换向量**，基线读数本身也是 D12 的输入。

**D9**：新建 scheduled workflow（每日一次）跑 `make eval-llm-memory` + D10 的 golden 对比，失败贴通知。**不**并入 PR 级 `eval-llm-required`——LLM 评测慢且花钱，nightly 是正确节奏；PR 级只跑 D10 的确定性 golden（无 LLM、秒级）。

**D11**：`test_memory_e2e.py` 参数化 store backend（InMemory + PgMemoryStore，无 PG 自动 skip）；PG 分支覆盖「5 次执行 → 5 episode 落库 → 挖掘 draft Skill → 5 次使用升级 stable → 召回命中」全闭环。注意 Windows 上 PG 测试默认 skip，PR 模板加勾选项提醒手动补跑（与 `tests/ha/` 既有约定一致）。

### D12（P2）遗忘阈值基线化

- **依赖批次 C 的指标产出**：先采集「importance 分布 + 记忆年龄分布 + 实际召回命中」，再定 `MEMORY_FORGET_THRESHOLD` / `MEMORY_FORGET_AGE_DAYS` 取值，把「拍脑袋常量」变成「有读数依据的配置」。
- 采集不到数据前**保持现值不动**——宁可不治理，不可误杀。

---

## 5. P2 增强候选（Codex 对照，本篇不授权，仅登记）

| # | 候选 | Codex 做法（源码实证） | 借/不借判断 |
|---|------|----------------------|------------|
| E1 | 读取用量驱动巩固 | `usage_count`/`last_usage` 列 + Phase 2 按用量选输入（migration `0016_memory_usage.sql`） | **借（P2）**：「被用」是记忆价值最硬的信号，本仓 consolidate 只看 importance+age。实现 = D3 的 provenance 同批加两列 + 巩固排序加权 |
| E2 | brief/full 分层注入 | brief 一行结论常驻上下文，full 带证据按需加载 | **借（P2）**：typed 记忆每次全量走 embedding+向量召回才进上下文；平移成「摘要常驻 + 全文按需」省一次召回 |
| E3 | 记忆资产人可审计 | `.meta-memory/*.md` 文件，人可直接读可改 | **不借（本体位不同）**：本仓记忆沉 PG 是多租户隔离的必然代价；折中替代 = D4 审计日志 + 管理端只读查询，不走文件化 |
| E4 | 行号级 citation | `MemoryCitation {path, line_start, line_end, note}` | **暂不借**：当前 memory 无文件路径概念（存 PG）；等价物 = D3 provenance 的 `source_execution_id`，先把它做实再说 |

---

## 6. 批次划分与验收

| 批次 | 内容 | 项数 | 复杂度 | 依赖 | 验收判据 |
|------|------|------|--------|------|---------|
| **A** | D10 golden 集 + 基线脚本 → D1 向量召回 → D2 去重 | 3 | 高 | 无（最优先） | golden 基线冻结；换路径后同 golden recall@k **不下降**；无 embedding 行走降级不报错；相同 task_summary+key_steps 连续 save 两次只有一行 |
| **B** | D3 provenance → D4 审计日志 → D5 衰减批删 → D6 sink 增量化 | 4 | 中 | 无（可与 A 并行） | `injected_by='tool'` 记忆排序得分低于同等 `'user'`；删 1000 条 → 1 条 bulk 审计、耗时降一个数量级；10k 记忆量下 ProceduralSink 单次扫描行数 ≤ 增量窗口 |
| **C** | D9 门禁布线 + D11 PG e2e 闭环 | 2 | 中 | D10 的 golden 脚本 | nightly 工作流实跑一次可见结果；PG 分支闭环全绿（无 PG 环境 skip 并有 PR 勾选提醒） |
| **D** | D7 T8 适配器 → D8 命名收敛 → D12 阈值基线 | 3 | 中 | B 的指标产物（仅 D12） | `UserSemanticStore` 有非 mock 实现且两侧读到同一条；`TRAJECTORY` 改名后全仓引用通过、契约测试 5 passed 不回退；阈值调整有读数依据 |

每批独立 commit、独立合流；批内「写→验→报」逐项过（语法/lint/相关测试/冒烟）。

---

## 7. 明确不做

- ❌ 不重构四类分类、`ContextSelector`、`SkillUsageTracker`——计划 §4 已定论保留。
- ❌ 不合并 `agent-core/memory` 与 `agent-runtime/memory_*` 两条链路（ADR-0005 定性：语义不同，合并毁掉程序性记忆管道）。
- ❌ 不替换三因子评分/加权融合（ADR-0005 决策 2）。
- ❌ 不引 Mem0/Zep/Letta 外部方案替代。
- ❌ 不借 Codex 的「无向量检索 / 无租户 / 文件式存储」本体位——企业多租户定位下是退步。
- ❌ 本篇不授权任何编码；评审通过后按批次逐个授权。

---

## 8. 风险与依赖

1. **D1 是破坏性迁移**：存量 `episodic_memories` 加列走 `ADD COLUMN IF NOT EXISTS` + 可空，不阻塞上线；但需确认线上存量数据量级（`docs/operations/unconfirmed-items.md` 已登记「真 PG 加列往返」为待环境项）。
2. **D1 维度对齐**：用 `{{vector_dim}}` 模板与宿主 embedder 同源，实施时以 `memories` 表现有维度为准复核。
3. **D9 nightly 需要 LLM 密钥**：密钥缺失时退出码 2 显式 SKIP（不假装通过，现行设计正确）；无密钥时至少 D10 确定性 golden 仍在 PR 级兜底。
4. **D11 的 PG 闭环**在 Windows 开发机默认 skip——存在「绿灯但没真跑」的风险，靠 PR 勾选 + CI Linux 侧真 PG 双重兜底。
5. **上游状态行同步**：本篇授权执行后，`plan-memory-hardening-2026-09-27.md` 的「状态」行与 ADR-0005 §6.1 未完项清单需同步刷新（两处文档改动随第一批合流一起做，避免又出现计划与实态漂移）。
6. **D8 改名是 breaking**：虽影响面仅宿主侧 11 处，仍需按仓库惯例评估是否有外部调用方（agent_federation 是否引用 `MemoryCategory` 未核实，列为改名前第一步）。
