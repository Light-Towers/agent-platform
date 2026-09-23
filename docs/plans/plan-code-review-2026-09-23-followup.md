# 代码审查后续追踪（2026-09-23）

> 来源：深度代码审查报告核验（8 条断言 7 条坐实、1 条部分准确）。
> 已修复：C1 / W4 / W5 / S8。待修复：C2 / W3 / S6 / S7 / W4-conftest。

## 已修复

### C1: 358 处 `# noqa: BLE001` 死代码清理（方案 B）
- BLE001 从未启用（select 不含 BLE，ignore 显式含 BLE001），noqa 对门禁零收益
- 精确删除 358 处 `# noqa: BLE001`（保留其他规则 noqa + 恢复 22 处 pragma: no cover）
- ruff check . 通过，RUF100 从 420 降到 64（剩余为既有非 BLE001 noqa）
- BLE001 真正治理（select 加 BLE + 逐条论证）作为独立里程碑后续推进

### W4: 测试产物 knowledge_lifecycle_audit.json 从版本库移除
- git rm --cached + .gitignore

### W5: 22 处 `# noqa: BLE001 - pragma: no cover` → `# pragma: no cover`
- 恢复 coverage.py 豁免语义

### S8: architecture-boundary-agent-core-vs-dialogue-framework.md 加 SUPERSEDED 标注

## 待修复

### C2: 审计 JSON read-modify-write 静默清空（高优先级）
- 位置：`exhibition_agent/foundation/data_egress.py:233-247` 及同模式 4 处（evaluation.py / execution_context.py / knowledge_lifecycle.py / production_readiness_gate.py）
- 问题：json.load 失败 → `audit_log = []`（无日志）→ append 1 条 → 全量覆盖写 → 历史审计销毁；无文件锁、非原子写
- 修复：`logger.exception` + 归档损坏文件 `os.replace` 为 `.corrupt.{ts}` + tmp+`os.replace` 原子写；长期改 append-only JSONL
- 验证：坏 JSON 跑 transition_status 断言旧记录仍在 + 两进程并发写 20 条断言 40 条

### W3: 向量维度降级 512 永久固化错误 schema
- 位置：`agent_federation/agent/db.py:51-55`
- 问题：`get_embedder().dim` 异常 → `dim=512`（无日志）→ `CREATE TABLE IF NOT EXISTS` 固化错误 schema → 后续 vector dim mismatch，不自愈
- 修复：fail-fast（`logger.exception` + `raise`）或校验既有表列维度与 `get_embedder().dim` 一致
- 验证：monkeypatch get_embedder 抛 ConnectionError，断言 _ensure_memories_schema 抛错且不建表

### W4-conftest: 审计测试未隔离 _AUDIT_LOG_PATH
- 位置：`exhibition-agent/tests/conftest.py`
- 修复：加 autouse fixture 重定向 `_AUDIT_LOG_PATH` 到 `tmp_path` + 补 `assert get_audit_log()[-1]["to_status"] == "REVIEWING"` 断言

### S6: CI install 非 --frozen，uv.lock 漂移不可拦截
- 位置：`Makefile:7` `uv sync --all-packages --extra dev`（无 `--frozen`）
- 修复：CI 改 `uv sync --frozen` + 加 `uv lock --check` 门禁

### S7: LISTEN 重连失败无日志 + 复用失败 conn
- 位置：`agent_runtime/planner/durability_pg.py:371-372`
- 注：首次异常有 `logger.warning`（line 367），但重连失败（line 371-372）无日志 + 复用同一 conn
- 修复：重连失败打日志 + 指标计数 + 连续 N 次失败从池中换新连接
