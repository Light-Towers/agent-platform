# Dockerfile 依赖层拆分——让"改一行代码"不再重跑 10 分钟 pip

> 状态：Proposed（待拍板）｜依据：2026-11-24 实取构建日志（`/tmp/build-*.log`）+ Dockerfile:70-115｜触发：用户复盘"为什么一早上反复重建、每次 10 分钟"
> 关联：`plan-build-pypi-acceleration-2026-11-23.md`（治的是"下载慢"，本方案治的是"重复安装"——两件事）

## 0. 问题（实取）

根 `Dockerfile` 的分层顺序（:102-115）：

```
COPY applications/agent_server ./applications/agent_server   # :102 业务代码
RUN pip install ... ".[otel]"                                 # :110 全量依赖（100+ 包）
RUN pip install pymilvus==3.0.3                               # :115
```

**`:110` 在 `:102` 之后** ⇒ 只要 `agent_server/` 下改一行 .py，:102 缓存失效 → :110 的 pip install 整条重跑（实测每次 ~10 分钟，即便下载已换阿里云加速到 122MB/s，仍要重新解析/安装 100+ 包）。

今天上午因 5 个 bug 重建 5 次，每次都付这笔 10 分钟——这是结构性浪费，不是偶发。

## 1. 关键约束（实取）

- `pyproject.toml:68` `[tool.hatch.build.targets.wheel] packages = ["applications/agent_server"]`
  ⇒ `pip install .` **必须** `applications/agent_server` 目录存在才能构建 wheel。
- 不能简单把 :110 提到 :102 之前——那样目录不存在，构建失败。
- extras（`[langfuse]` 在 agent-runtime、`[memory-embed-local]` 在 agent-core、`[otel]` 在根包）必须挂在声明它的包上（Dockerfile:103-109 的既有雷），拆分时不能丢。
- torch 层（:99-100）已在业务代码前、且传递依赖预装，不受本次影响。

## 2. 方案

**核心**：把"装依赖"和"装业务代码"解耦，让依赖层的缓存键只绑依赖声明、不绑业务源码。

### 改动（根 Dockerfile :102-115）

分三步：

```dockerfile
# 步骤 A：依赖层——只依赖 pyproject + packages + 一个最小 agent_server 骨架
# 骨架只需 pyproject 声明的包目录存在（hatch 能构建即可），内容随后会被覆盖
COPY applications/agent_server/__init__.py ./applications/agent_server/__init__.py
RUN pip install --no-cache-dir \
      "./packages/agent-core[memory-embed-local]" ./packages/shared-schemas \
      "./packages/agent-runtime[langfuse,identity,auth]" \
      ".[otel]" pymilvus==3.0.3
# ↑ 这层缓存键 = pyproject(73) + packages(74-76) + 骨架 + 本行命令
#   改 applications/agent_server 的业务 .py 不动这些输入 ⇒ 整层命中，不重跑

# 步骤 B：业务代码层——覆盖骨架，重装元数据（--no-deps 秒级）
COPY applications/agent_server ./applications/agent_server
RUN pip install --no-cache-dir --no-deps --force-reinstall .
# ↑ 只重装根包元数据（此时依赖已满足），不重新解析/下载任何第三方包
```

### 为什么可行

- 步骤 A 的骨架 `__init__.py`：hatch 的 wheel target 只要求包目录存在即可解析依赖、构建元数据；此时装的是"空壳"根包，但**第三方依赖全装好**（这是耗时部分，且被缓存）。
- 步骤 B 的 `--no-deps --force-reinstall .`：把真实业务代码覆盖进去后，仅重装根包本体（含 `agent_server/` 的真实文件），依赖不动——秒级。
- extras 保留：步骤 A 的 `.[otel]` + 各包 extras 一字不改，不触发 :103-109 的雷。
- pymilvus 并入步骤 A（:115 单独一行也重跑，一并解决）。

### 风险与对策

| 风险 | 对策 |
|---|---|
| 骨架 `__init__.py` 不足让 hatch 构建 wheel | 若失败，退路：步骤 A 用 `pip install <显式依赖列表>`（从 pyproject dependencies 生成，需维护）；或在步骤 A 先 COPY 整个 agent_server 但把 pip install 放在一个**只依赖文件哈希的层**——实施时先小规模验证 |
| `--force-reinstall --no-deps .` 是否真秒级 | 构建时实测计时；若不达预期，改用 `pip install -e . --no-deps`（editable 直接指向源码，无需重装） |
| 改了依赖声明（pyproject/lock）后的缓存 | :73 的 `COPY pyproject.toml` 会触发步骤 A 失效——正确行为（依赖变了就该重装） |

## 3. 验收

1. 构建计时：改一行业务 .py 后重建，步骤 A（pip 层）显示 `CACHED`，总时长从 ~10min 降到 <3min。
2. 镜像内 import 探针全过（现有 A1：langfuse import）。
3. extras 在位：`langfuse` / `argon2-cffi`(identity/auth) / `sentence_transformers`(memory-embed-local) / `opentelemetry`(otel) / `pymilvus` 全部 import 成功——防"构建绿但镜像缺包"的静默雷。
4. 三台分发 + rollout + /health 正常（现有流程）。
5. 门禁：可加一条断言"步骤 A 在 COPY 业务代码之前"，防回退。

## 4. 影响面与刀次

- 只改根 `Dockerfile`（KS Dockerfile 的 pip 层结构不同，本次不动；nl2sql 同构可后续套用）。
- 实施：改 Dockerfile → 本地 `docker build` 无法跑（本机无 docker）→ 直接在 241 构建验证（一次构建窗口 ~20min）→ 三台分发 + rollout。
- 因涉及构建产物，属 D2（需用户拍板）。

## 5. 与既有工作的关系

- `plan-build-pypi-acceleration` 治"下载慢"（阿里云源 + torch 依赖预装），本方案治"重复安装"——两者叠加后：下载快 + 不重复装。
- `scripts/evidence/chat_images_real_pg_probe.py`（今天新增的真 PG 探针）保证本次 Dockerfile 改动不涉及业务逻辑回归；镜像内 import 探针（A1）保证依赖齐全。

## 6. 实施结果（2026-11-24 实取，诚实读数）

**核心目的达成**：改一行业务代码（`config.py` 加注释）后重建，`Step 19（torch）` 与 `Step 21（依赖层 9.5min）` 均 `Using cache`，只有 `Step 22（COPY 业务代码）` + `Step 23（pip --no-deps --force-reinstall）` 重跑。依赖层不再因业务代码改动而重装——B 的目标证实。

**但总耗时未降到 <3min（实测 692s ≈ 11.5min）**：因为**前端 pnpm 层（Step 6 `pnpm install` / Step 8 `pnpm build`）没命中缓存、每次重跑**。这是 Dockerfile :28-35 早已记录的**另一个**分层坑（`COPY web/` 在 `pnpm install` 之前，任何前端源码变化都让安装层失效）——与本次依赖层拆分无关，但让"整体构建快"的目标只实现了一半。

⇒ 待办（独立）：按 :28-32 的既有思路拆前端层（清单先 COPY → pnpm install → 源码 COPY → pnpm build），才能把总构建时长真正降到分钟级。

线上：rev `05d9910b` 三台分发 + rollout 成功，A1 全依赖 import（langfuse/pymilvus/minio/sentence_transformers/jwt/argon2/opentelemetry/fastapi）全过——分层没漏包。
