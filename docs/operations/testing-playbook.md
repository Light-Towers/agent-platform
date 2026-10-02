# 测试实跑最佳操作手册（testing playbook）

> 来源：2026-09-28 `feat/isolation-hardening` 分支深度盘点 + 本地/远程真实环境实跑的完整沉淀。
> 目标：**又快又准**——用最小成本闭合测试盲区，结论只基于实跑证据。
> 对应长期记忆条目：分层实跑流程（task_experience）、Linux 容器最小配方（project_build_configuration）、psycopg 审计脚本缺陷范式（common_pitfalls_experience）、Windows 远程 SSH 范式（tool_experience）。

## 1. 测试目标与红线

**目标**
- 能本地验证的本地验证；本地受限（OS 硬跳过 / 缺真实外部系统）的，用真实 Linux/Docker 环境实跑补齐，**不得因本机跳过就声称已验证**。
- 每次实跑分析卡点并优化流程，让下次更快。

**红线**（与 AGENTS.md 一致）
- 禁止删用例 / 收窄断言 / 放宽前置条件凑绿。
- 失败先复跑区分「环境 flake」与「真实缺陷」，真实缺陷修产品代码到契约要求。

## 2. 分层执行流程（按成本从低到高）

| 步骤 | 动作 | 耗时量级 |
|---|---|---|
| 1 | **缺口盘点先行**：列出"未实跑项"（仅 mock 覆盖、本机硬跳过、需真实 DB 的脚本），它们才是验证重点 | 分钟级 |
| 2 | **快速门禁**：`py_compile` + `ruff` + `lint_architecture.py` + `check_doc_sync.py` | 秒级，先行拦截 |
| 3 | **最窄子集**：`uv run pytest <改动目录>/tests -q`；迭代用 `--lf`/`--ff`，收窄用 `-k`/`-m` | 十秒~分钟 |
| 4 | **环境盲区补跑**：本机跑不了的（如 `tests/ha` 真实 PG，Windows 被 conftest 以 `sys.platform=="win32"` 硬跳过）在 Linux 容器/远程机实跑 | 视环境 |
| 5 | **CI 等价全量**：`make test` 9 session + eval + `uv lock --check` 收口 | 十分钟级 |
| 6 | **失败定性复跑**：单跑复验 1-2 次；不可复现的计时类失败记为环境 flake 并如实汇报，不改代码 | 分钟 |
| 7 | **报告**：按"门禁项 / 命令 / 结果"分层表格输出，明确区分 passed / skip / 未跑 | — |

**长任务执行方式**：后台化 + 输出落盘（bind-mount / `Tee-Object`）+ 轮询读取，抵御终端/SSH 通道断开；只看汇总行（`Select-Object -Last N`）。共享 shell 若卡在续行提示符 `>>`，命令会**静默不执行**——以"预期产物文件是否生成"作为核实手段。

## 3. 本仓特定配方

### 3.1 Linux 容器跑 tests/ha + identity（最小安装）

```bash
# 依赖：切勿 --all-packages（会拉全部 6 个 application；eval extra 含 flashrag
# git+https 构建，需 git 且极慢，是最大的耗时陷阱）
uv sync --extra dev                # 仅 pytest / pytest-asyncio / ruff

# tests/ha 需要 pgvector 真实 PG（规格同 docker-compose.ha.yml）：
#   pgvector/pgvector:pg16 → 127.0.0.1:5433，库/用户见 tests/ha/conftest.py 默认 DSN
#   测试容器用 --network host 复用同机 PG
uv run pytest tests/ha -q          # 预期 27 passed

# identity 套件（ADR-0007 RS256/HMAC 真实密码学）：PyJWT 在 agent-runtime
# 是 optional extra `identity`，不在默认依赖，须补装
uv pip install PyJWT cryptography
uv run pytest <identity 测试目录> -q   # 预期 40 passed
```

### 3.2 psycopg 只读审计/运维脚本三原则（真实库教训）

`scripts/audit_tenant_access.py` 连真实 PG 暴露的三个缺陷，mock 单测永远发现不了：

1. **显式 autocommit**：psycopg v3 默认 `autocommit=False`，单条 SQL 失败使事务进入 aborted 态，后续查询级联报 `current transaction is aborted`——"逐项 try/except 互不中断"成假象。只读扫描脚本建连后必须 `conn.autocommit = True; conn.read_only = True`。
2. **不硬编码 schema 列名**：按 `information_schema.columns` 做防御性列探测，缺列**降级**（如本表无命中计数列则仅按条目数统计并在报告注明）而非抛错。
3. **渲染层防御性取值**：报告渲染用 `sec.get('status', 'n/a')`，任何单项结构缺键不得导致整份报告不落盘。

> 结论性教训：凡连真实外部系统（DB 等）的脚本，**必须在真实环境至少跑一次**才算验证。

### 3.3 Windows → 远程 Linux 实跑通道（Posh-SSH 范式）

本机 OpenSSH 需交互输密、无 sshpass 时：
- `Install-Module Posh-SSH`（先 bootstrap NuGet provider），纯 PowerShell 非交互密码 SSH；
- 长任务不在 SSH 前台跑：`docker run -d` + bind-mount 日志文件，宿主 `tail` 轮询；
- PowerShell 引号陷阱：单引号内 `\"` 会被当串结束、`$?` 是本机自动变量而非远端回传、多行 here-string 易触发终端守卫——复杂命令拆单行或先落盘脚本再 `-File` 执行；
- 端口测绘用 `System.Net.Sockets.TcpClient.ConnectAsync(...).Wait(1500)`，勿用 `Test-NetConnection`（unreachable 端口约 21s/个）。

## 4. 已验证基线（2026-09-28 实跑快照）

| 范围 | 结果 |
|---|---|
| 远程真实 PG：`tests/ha` | 27 passed |
| 远程真实密码学：identity 套件 | 40 passed |
| 本地 CI 等价：根 session（`-m "not requires_pg"`） | 678 passed, 27 deselected |
| 本地：`tests/` 直跑 | 450 passed, 26 skipped |
| 本地：8 个子包 session | 全绿（agent-runtime 608×3 轮复跑稳定；首跑 8 failed 为冷启动环境 flake，不可复现） |
| 门禁：ruff / lint_architecture / check_doc_sync / eval / uv lock --check | 全过 |
