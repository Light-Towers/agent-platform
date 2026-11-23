# 构建期包下载加速——治本方案（反复踩坑的根因修复）

> 状态：Proposed（待拍板）｜依据：2026-11-23 实取测速（路径/命令见 §2）｜触发：用户「将包下载加速彻底解决，遇到好几次了」
> 关联：`docs/operations/unconfirmed-items.md` D24（此坑的历次登记，本方案收口它）｜`docs/operations/deploy-e2e-time-sinks.md`

## 0. 问题陈述

构建镜像时 pip 下载包反复慢到 50–160 kB/s（一次 KS 构建 70 分钟还没下完 55MB 的 pyarrow），已多次遇到。D24 之前只记了现象（"慢在 PyPI 国际链路"）和绕过（`/tmp` 副本改 timeout），没有根治。

## 1. 根因（实取，不是猜）

| 事实 | 证据（2026-11-23 实取） | 结论 |
|---|---|---|
| 容器网络不慢 | `--network=host` 容器内 curl 阿里云 **19 MB/s**、宿主 17 MB/s | 瓶颈不是带宽/容器网络 |
| 构建实际走清华源 | 3 个 Dockerfile `ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`；`build.sh:83` 硬编码同值；`pip config set` 全局生效 | 慢源是配置写死的，不是网络 |
| 构建日志印证 | KS 构建 `pandas 12.4MB @118kB/s`、`numpy 16.9MB`、`pyarrow 55MB` 慢 | 与清华源慢一致 |
| 清华源首页 301 | `curl pypi.tuna.tsinghua.edu.cn/simple/` 返回 301 | 跳转 + 回源是慢因之一 |
| torch 单独走 pytorch.org | 3 个 Dockerfile `--index-url https://download.pytorch.org/whl/cpu`；容器实测该首页仅 734 kB/s | torch 是另一条慢链路（但 wheel 走 CDN 尚可） |
| 阿里云无 torch +cpu | 阿里云索引只有官方 CUDA 版（x86_64 ~800MB+），无 `+cpu` 后缀 | torch **不能**简单换阿里云，否则拉 CUDA 版撑爆镜像/磁盘 |
| 靠人传参 | 换源只能 `--build-arg PIP_INDEX_URL=...`，每次构建靠人记得 | 违反 P2（配置与代码分离）+ P3（机制保证，不靠自觉）|

**一句话根因**：慢源（清华 + pytorch.org）被硬编码进 Dockerfile 默认值和 build.sh，而且靠命令行参数临时覆盖——既没选对源，又没机制化。

## 2. 治本方案（三层，P2/P3 齐全）

### 2.1 单一真相源：3 个 Dockerfile 的默认值（它们在版本控制里）

⚠ 实取订正：`deploy/k8s/` 整个被 `.gitignore:145` 排除，**不在版本控制里**——所以曾试图新增的 `build-env.sh` 放那里是错的（gitignored 的本机副本不是真相源，新克隆不存在）。真相源必须是入库文件：**3 个 Dockerfile 的 `ARG PIP_INDEX_URL` 默认值**（它们被 CI 和 doc-sync 保护）。

- 3 个 Dockerfile 的默认 `ARG PIP_INDEX_URL` 统一改成阿里云；`PIP_TRUSTED_HOST` 用 ARG 参数化（不再硬编码）。
- nl2sql Dockerfile 原本**完全没配 pip 源**（裸 pip 走官方 PyPI，也是慢点），补上统一配置。
- 构建机上的 `build.sh:83` 硬编码改成 `"${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"`（运行时读 env，构建机副本不在本方案交付范围，仅记录改法）。

### 2.2 torch 不动（已有层缓存，不是瓶颈）

实取订正：torch 的 `download.pytorch.org` 虽首页 734 kB/s，但 209MB CPU wheel 走 CDN 30 秒下完（构建日志实测 7 MB/s）；且 Dockerfile:88-92 已刻意把 torch 放在业务代码 COPY 之前、`--no-cache-dir` 配合 Docker 层缓存——改它会破坏这套成熟设计。阿里云又无 `+cpu` 版（只有 800MB+ CUDA 版）。⇒ **torch 保持原样**，不在本次治本射程内。慢的只是清华源的其余包。

### 2.3 门禁（防复发）

- `lint_architecture.py` 加不变量：**Dockerfile 和 build.sh 里不得出现 `pypi.tuna.tsinghua.edu.cn` 或裸 `download.pytorch.org --no-cache-dir`**（白名单：torch 的 --index-url 行可保留），违反即 CI 红。
- 治理用例：种植违规源能咬、真面（当前 Dockerfile）参与判决。

## 3. 影响面

| 文件 | 改动 |
|---|---|
| `Dockerfile` / `Dockerfile.nl2sql-service` / `applications/knowledge-service/Dockerfile` | 默认源改阿里云；PIP_TRUSTED_HOST 参数化；nl2sql 补源配置；torch 不动 |
| `scripts/lint_architecture.py` + 治理用例 | 防复发门禁（Dockerfile 不得再出现 tuna.tsinghua 源） |
| （构建机副本 `build.sh`，gitignored 不在交付） | 记录改法：`PIP_INDEX_URL` 从 env 读 |

## 4. 验收

1. 改完后**重新构建 KS 镜像**（当前这次已停），计时对比：应从 70 分钟降到分钟级。
2. 门禁反证：种植清华源 URL 能报红，真面绿。
3. 三镜像（agent-platform / KS / nl2sql）构建日志无非预期慢源。

## 5. 待拍板

- **方案范围**：(a) 全量治本（改 3 Dockerfile + build.sh + build-env.sh + 门禁，本方案推荐）——一劳永逸；(b) 只改这次构建的 `--build-arg` 用阿里云（最小改动，但下次还会踩）。
- **torch 缓存策略**：(a) 去 --no-cache-dir 复用 pip 缓存（改动小）；(b) 宿主持久缓存挂卷（改动大但最彻底）。

## 6. D24 收口

本方案落地后，`docs/operations/unconfirmed-items.md` D24 的"要不要接内网镜像"应更新为：不接内网私有镜像（信任面变更不值当），改用**公共阿里云镜像 + 机制固化**——19MB/s 已够快，且无新增信任面。
