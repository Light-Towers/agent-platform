# data_analysis.query — 数据分析 Agent Skill

> 只读 skill。自然语言问数 → Metric Registry 校验 → HTTP 调 nl2sql-service → 返回结果。

## 链路

```
NL query
  → 提取 metric_id + nl_query
  → Metric Registry 校验（foundation/metric_registry.py get_metric_status）
      ├─ status == VERIFIED   → HTTP 调 nl2sql-service /api/query
      └─ status != VERIFIED   → 答"该指标待接入"，不触 L3、不生成 SQL（INV-10）
           ├─ BLOCKED          → error_code = METRIC_BLOCKED
           ├─ status is None   → error_code = DATA_NOT_CONNECTED
           └─ 其他非 VERIFIED   → error_code = METRIC_NOT_VERIFIED
  → 返回 SkillResult
```

## INV-10 约束

指标口径不可绕过：非 VERIFIED 不得执行。命中非 VERIFIED 时确定性答"该指标待接入"
（`PENDING_ANSWER`），不触 L3 text2sql、不生成任何 SQL。本 skill 不向 `sql_statements`
append，Supervisor 透传初始空列表，故全程零 SQL。

## nl2sql-service HTTP 调用

VERIFIED 分支经 `httpx.AsyncClient` POST `{NL2SQL_SERVICE_URL}/api/query`，
按 `SqlQueryResponse` 契约（answer / sql / error / latency_ms / fallback）组装 SkillResult。

- `NL2SQL_SERVICE_URL` 环境变量配置服务地址（默认 `http://localhost:8000`）
- 超时（30s）→ `UPSTREAM_TIMEOUT` + `NOT_CONNECTED`
- 异常/非 2xx → `UPSTREAM_ERROR` + `NOT_CONNECTED`
- 响应 `error` 非空 → `NL2SQL_ERROR` + `NOT_CONNECTED`
- 成功 → `READY` + `data.sql` / `data.latency_ms` / `data.fallback`

## 挂载方式

经 Supervisor `run_skill` 节点内 skill 路由分派执行（注册表 `_SKILLS["data_analysis.query"]`）。
不新增 LangGraph 节点，图节点集合保持 `select_skill → run_skill → emit_trace` 不变
（INV-10 结构守卫）。

路由触发条件（`select_skill`）：
1. `params.skill == "data_analysis.query"`（显式指定）
2. `params.nl_query` 存在（自然语言问数意图）
3. 否则默认 `venue.schedule.query`

## 依赖

- `foundation/metric_registry.py` — `get_metric_status()` 校验（只读，不改）
- `contract/error_codes.py` — `PENDING_ANSWER` + INV-10 错误码
- `contract/envelope.py` — `Readiness` / `DataClassification` / `Source`
- `skills/base_skill.py` — `BaseSkill` / `SkillContext` / `SkillResult`
