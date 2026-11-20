# 黄金主测试（L2）

本目录的回归测试分两层，互补：

- **L1 结构断言**（`live.manifest.json` + `harness.run_manifest`）：断言端点"鉴权可达 / 200 / 有真实数据或正确 HTTP 码 / 写护栏"。基于 `manifest` 声明驱动，与数据是否存在无关。
- **L2 黄金主**（`harness.run_golden` + `golden/*.golden.json`）：断言"**响应结构指纹不变**"，专门捕获 API 的 **schema 漂移**（字段改名、类型变化、嵌套结构变化）。

## 为什么需要 L2
API 数据本身会漂（默认展会一换，`page/backlog` 从 15 行变 0 行；展会列表顺序不稳定）。若把"期望返回 N 行 / 某顺序"写死，测试会天天假红。L2 用**归一化结构指纹**替代具体值，对数据漂免疫，只对结构变化敏感——这正是 Golden Master / 表征测试对易变系统的标准做法。

## 归一化规则（`harness.normalize`）
| 内容 | 归一化为 | 目的 |
|---|---|---|
| 时间戳 `2026-09-18T...` | `<TS>` | 免疫时间 |
| UUID | `<UUID>` | 免疫随机串 |
| 长数字 id（≥11位，展会/展位/订单） | `<ID>` | 免疫动态主键 |
| bool / int / float / str | `<bool>` / `<int>` / `<num>` / `<str>` | 仅保留类型，丢弃具体值 |
| list | 只保留**首元素**结构（丢弃顺序与长度） | 免疫行数与排序 |
| dict | 按键排序后逐字段归一化 | 免疫键顺序 |

→ golden 文件**不含任何密钥 / PII**（令牌在 `headers` 里，从不入文件；响应体已归一化）。

## golden 文件
`golden/<group>__<label>.golden.json`，结构：
```json
{ "_meta": { "path": "...", "params": { "exhibitionId": "..." } },
  "fingerprint": { "code": "<int>", "data": [ { ... } ], ... } }
```
- 上下文端点（`get_ctx`）用钉死展会 `golden_exhibition_id=1963526156780019713` 录制，`params` 写入 `_meta`，**比对时复用同一输入**以保证稳定（不受展会列表顺序漂移影响）。
- golden 文件纳入版本控制（VCS）。

## 运行
```bash
# 比对模式（CI / 日常回归）：L1+L2 全跑，退出码非 0 即失败
python tests/skill_live_check/harness.py skills/company-venue-ops/live.manifest.json
python -m pytest tests/skill_live_check/ -q

# 重新生成基线（仅当 skill 或 API 契约确有变更时；diff 必须人工 review）
python tests/skill_live_check/harness.py skills/company-venue-ops/live.manifest.json --regen

# 指定其他 golden 目录
python tests/skill_live_check/harness.py <skill>/live.manifest.json --regen --golden-dir /path/to/golden
```

## 红线
- **绝不静默更新基线**：golden 变化=潜在回归，必须像审 PR 一样看 diff 再决定是否 `--regen`。
- L2 仅在 `golden/` 已初始化（存在 `.golden.json`）时运行；未初始化则跳过（先 `--regen`）。
- 默认仅 GET；仅 manifest 显式声明的 `post_data`/`post_struct` 会发 **POST 只读查询**（`page`/`list` 类，params 走 query string），任何真正的写调用触发 `harness.write` 的 `SystemExit`（E.写护栏）。
- **多令牌**：默认令牌取自 `jwt_env`/`jwt_search`；manifest 可另用 `jwt_files`（key→相对路径，向上查找）声明其他令牌，断言以 `"jwt": "<key>"` 选用（如 mingyang-company `/site` 门户用独立站点令牌 `SET_TOKEN`）。

---

# L3 hermetic 气隙模式（cassette 录制/回放）

在 L1/L2 之上提供**可离线、断网**的运行模式，用于 CI 门禁：即使被测 API 宕机/限流/鉴权过期，套件仍能跑；且**任何实时写请求在物理上不可能**（replay 下缺失 cassette 即报错，绝不回退到网络）。无需引入 vcrpy 等外部依赖，传输层统一走 `harness._http`。

## 三种模式
| 模式 | 触发 | 行为 |
|---|---|---|
| `live`（默认） | 无 flag / `SKILL_HTTP_MODE=live` | 真实请求；保留 L2 实时 schema 漂移检测 |
| `record` | `--record` | 真实请求并落盘 cassette 至 `cassettes/` |
| `replay` | `--replay` 或 `SKILL_HTTP_MODE=replay` | 仅读 cassette；缺失即 `RuntimeError`（断网） |

cassette 按 `sha256(method+url+params)[:16]` 命名，存于 `tests/skill_live_check/cassettes/`（含 `request`/`status`/`json`，无密钥——令牌只在请求头，从不入体）。

## 运行
```bash
# 录制（本地，API 确有变更时；会落盘 cassette，需 review 后提交）
python tests/skill_live_check/harness.py skills/company-venue-ops/live.manifest.json --record

# 气隙回放（CI 门禁：全来自 cassette，0 实时网络）
python tests/skill_live_check/harness.py skills/company-venue-ops/live.manifest.json --replay

# pytest 气隙（CI 用环境变量，无需 flag）
SKILL_HTTP_MODE=replay python -m pytest tests/skill_live_check/ -q
```

## 红线
- `replay` 下若出现未录制过的调用路径，立即 `RuntimeError` 失败——**绝不允许静默回退实时网络**（这是气隙保证的核心）。
- cassette 文件进 VCS（即 HTTP 层 golden）；API 变更须重录并 review diff。
- `live` 模式仍是"实时漂移检测"的权威入口，建议本地/定时跑；`replay` 是 PR 快门禁（稳定性优先）。

---

# 任务级黄金集（complex tasks）

在端点级 L1/L2 之上，再固定一层"**用户提示词 → 多端点编排**"的用例：`tasks.golden.json`（声明）+ `test_complex_tasks.py`（执行）。

- 每条 task = `{id, prompt, jwt, steps[], mode}`；`steps` 是编排出的逐次调用（method/path/params + 期望 http/code + schema 断言 `expect_list|expect_dict|expect_keys`）。
- 断言**只锁"可达性 + 响应结构"**，不锁具体值（免疫数据漂移），与 L2 哲学一致。
- 令牌：复用 `live.manifest.json` 的 `jwt_files`；每条 task/step 可用 `jwt` 选令牌（如 `/site` 门户用 `site`）。
- **写操作任务写 `"mode":"hitl"`→ 测试自动 `skip`**，保证"写操作永不自跑"（只登记 `planned_request`）。
- 三模式同 harness：`pytest`(live) / `SKILL_HTTP_MODE=record pytest` / `SKILL_HTTP_MODE=replay pytest`。

当前任务：`A.venue-health`(展会体检,9 端点)、`B.exhibition-ops`(带 exhibitionId 的上下文端点)、`D.my-exhibitor-todo`(/site: company+operation 跨服务)、`E.batch-audit-contractor`(HITL, skip)。

