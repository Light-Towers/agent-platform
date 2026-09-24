# C2: 审计 JSON read-modify-write 静默清空修复方案

> 日期：2026-09-23
> 优先级：高（审计数据丢失风险）
> 来源：深度代码审查报告 C2 条目

## 1. 问题

5 个审计文件使用相同的 read-modify-write 模式，存在三个缺陷：

1. **静默清空**：`json.load` 失败 → `audit_log = []`（无日志）→ append 1 条 → 全量覆盖写 → 历史审计销毁
2. **非原子写**：`open("w")` + `json.dump` 两步，进程崩溃在中间产生空/截断文件
3. **无文件锁**：两进程并发 read-modify-write 丢失记录（后写覆盖先写）

### 受影响文件

| 文件 | 函数 | 行号 |
|------|------|------|
| `foundation/data_egress.py` | `_log_audit` | 233-247 |
| `foundation/evaluation.py` | `_write_audit` | 227-241 |
| `foundation/execution_context.py` | `record_cross_tenant_attempt` | 225-239 |
| `foundation/knowledge_lifecycle.py` | `_write_audit_record` | 200-214 |
| `foundation/production_readiness_gate.py` | `_judge_data_ready` | 292-302 |

## 2. 修复方案

### 2.1 共享工具模块 `foundation/_audit_writer.py`

创建单一函数 `append_audit_record(path, record)`，封装：

- **损坏处理**：`json.load` 失败 → `logger.exception` + `os.replace` 归档为 `{path}.corrupt.{timestamp}` + 从空列表继续
- **原子写**：写到 `{path}.tmp` → `os.replace(tmp, path)`（POSIX/Windows 均原子）
- **目录确保**：`os.makedirs(dirname, exist_ok=True)`

同时提供 `read_audit_log(path)` 用于安全读取（损坏时返回空列表 + 打日志）。

### 2.2 替换 5 处内联模式

将每处的 15 行 read-modify-write 替换为 `append_audit_record(_AUDIT_LOG_PATH, record)` 一行调用。
`get_audit_log()` 函数替换为 `read_audit_log(_AUDIT_LOG_PATH)`。

### 2.3 不做的事

- **不改为 JSONL**：JSONL 是长期方向（追踪文档已记录），本次不改文件格式，保持 JSON array 兼容
- **不加文件锁**：原子 `os.replace` 已将竞态窗口从 "open+dump" 缩到 "read+write" 的 TOCTOU；审计场景并发量极低（会展 Agent 单租户），加锁收益不抵复杂度
- **不改 `_AUDIT_LOG_PATH` 路径****

## 3. 影响面

- 仅 `exhibition-agent` 应用内部，不跨包
- 5 个 foundation 模块 + 1 个新 `_audit_writer.py`
- 现有测试使用 `monkeypatch` 重定向 `_AUDIT_LOG_PATH`，不受影响

## 4. 验收标准

1. `ruff check .` 通过
2. `pytest applications/exhibition-agent/tests -q` 全通过
3. 新增测试：损坏 JSON 文件被归档为 `.corrupt.{ts}`，旧记录不丢失（从空继续）
4. 新增测试：原子写——写过程中文件不出现截断状态
5. 新增测试：并发写 20 条（2 线程 × 10），断言 ≥ 20 条记录（允许少量丢失因无锁，但不应清空）
