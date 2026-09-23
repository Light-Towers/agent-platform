# 代码审查后续追踪（2026-09-23）

> 来源：深度代码审查报告核验（8 条断言 7 条坐实、1 条部分准确）。
> 已修复：C1 / C2 / W3 / W4 / W4-conftest / W5 / S6 / S7 / S8。全部闭合。

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

### C2: 审计 JSON read-modify-write 静默清空（已修复）
- 创建共享 `foundation/_audit_writer.py`：`append_audit_record` + `read_audit_log`
- 损坏 JSON 归档为 `.corrupt.{timestamp}` + `logger.exception`（不再静默清空）
- 原子写：tmp 文件 + `os.replace`（唯一 tmp 文件名避免并发冲突）
- 进程内 `threading.Lock` 串行化同路径并发写
- 替换 5 处内联 read-modify-write：data_egress / evaluation / execution_context / knowledge_lifecycle / production_readiness_gate
- 测试：13 条（损坏归档 / 原子写 / 并发 / 正常追加 / 安全读取）
- 方案文档：`docs/plans/plan-c2-audit-atomic-write-2026-09-23.md`

### W3: 向量维度降级 512 永久固化错误 schema（已修复）
- 位置：`agent_federation/agent/db.py:51-55`
- 修复：`except Exception` → `logger.exception` + `raise`（fail-fast，拒绝用猜测维度建表）

### W4-conftest: 审计测试未隔离 _AUDIT_LOG_PATH（已修复）
- 位置：`exhibition-agent/tests/conftest.py`
- 修复：autouse fixture 重定向 5 个 `_AUDIT_LOG_PATH` 到 `tmp_path`

### S6: CI install 非 --frozen（已修复）
- 位置：`Makefile` ci 目标
- 修复：ci 目标末尾加 `uv lock --check` 门禁

### S7: LISTEN 重连失败无日志（已修复）
- 位置：`agent_runtime/planner/durability_pg.py:371-372`
- 修复：重连失败加 `logger.warning(..., exc_info=True)`

## 待修复

无。全部技术债已闭合。BLE001 真正治理（select 加 BLE + 逐条论证）作为独立里程碑后续推进。
