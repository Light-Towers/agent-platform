# 观测面接线与现网取证 · 坑档（2026-10-13）

> 用途：把一次 Langfuse 接线 + 现网取证里踩到的**全部**卡点落成可复算的记录，供后续会话/模型直接查，
> 不靠"下次我记得"。每条都写「现象 / 真因 / 解法 / 下次怎么提前避开」。
> 相关：修法与方案见 `docs/plans/plan-langfuse-wiring-2026-10-13.md` §7；现场读数见
> `docs/operations/evidence/2026-10-13-langfuse-stack/readings.md`；线上状态见 `docs/operations/env-126-inventory.md` §4.11。

## 0. 一览表（按本轮耗时代价排序）

| # | 现象（第一眼像什么） | 真因归类 | 一句话解法 |
|---|---|---|---|
| 1 | `/health` 报 `otel_status=ACTIVE`，但 Jaeger 里一条 span 都没有 | **产品缺陷**：两个后端抢同一个 OTel 全局 provider，装配顺序决定谁活着 | `init_tracing` 上移到模型构造之前；复用分支"探不到出口就补挂"；三条钉用例 |
| 2 | "Jaeger 已验证 ✅"写在手册里，现网却是空的 | **文档失效**：读数量的是旧 Pod，换 rev 后没复跑 | 现网读数必须绑定当时的 Pod `GIT_REV` 一起记 |
| 3 | `verify.sh` 报"镜像 rev 不符" | **读错运行时库**：`docker run` 读的是 moby 库残留，Pod 跑的是 containerd-k8s | 改 `kubectl exec` 读跑着的 Pod 内 `GIT_REV` |
| 4 | 三节点镜像回读 241 是旧 id | **分发盲区**：`distribute.sh` 只覆盖*其余*节点，构建机自身要补一次本地导入 | 构建机也要 `docker save \| ctr -a …containerd-k8s… images import -` |
| 5 | 探针读数 `evidence_count=0 / answer=''` | **探针读法错**：SSE 事件帧是平铺的 | `d.get("type")` + 顶层取字段，别取 `d["payload"]` |
| 6 | 取证"查不到 trace" | **平台版本差异**：v4 `events_only` 撤了 `/api/public/traces` | 改 `GET /api/public/v2/observations?fields=io,usage` |
| 7 | 中文 needle 恒 miss，但 ASCII marker 命中 | **编码层级**：载荷是多层 JSON 编码的 `\uXXXX` 字面量 | 匹配前 `_flatten()` 摊平到解不动为止 |
| 8 | 后端"查不到本次调用"，其实平台没错 | **被短路了**：命中语义缓存 ⇒ 图不跑、模型不调用 | 取证问题要**语义新颖**；`cache_hit` 单独成一个判定 |
| 9 | 判定只看到 1 条 GENERATION，"含检索原文"永远不成立 | **先命中≠全到**：路由那条先落库 | 命中后再等一个 settle 窗口复取 |
| 10 | `e2e_traceparent.sh` 只 `exit 1`，一行原因都没有 | **脚本形状**：`set -e pipefail` 下 `X=$(curl -sf … \| grep -c …)` 在 404 处直接终止 | 先落盘再判，把"404/连不通/服务名不符"分开报 |
| 11 | `crictl images` 回读"缺失" | **假 flag**：`--no-trims` 不存在（是 `--no-trunc`） | 读数为空先判探针是否真跑到 |
| 12 | 一次长命令输出整个丢失 | **工具超时**：默认 2 分钟，命令被移入后台且本轮结束 | 长命令显式设 tool timeout 或 run_in_background 并轮询读数 |
| 13 | 三个 `pkill -f` 把自己 ssh 会话杀了（本轮之前两次） | **自匹配**：模式匹配到自己的命令行 | 用括号技巧 `pkill -f "[d]ocker build"`，杀完必须回读真实进程状态 |
| 14 | `git add -A docs` 把一份没审过的未跟踪文档扫进提交 | **暂存范围过宽** | 按文件名 `git add <path>`；提交前 `git status` 复核 included 内容 |

## 1. 两个观测面互相顶掉（本轮最贵，D-LF-1）

**现象**：rev `c01e9cf`，Langfuse 的 A3 判据刚通过，同窗口一次 `GET /health` + 一次 `POST /query`
在 Jaeger 里 `rowcount=0`，注入的 traceparent id 直查 404；而 `/health` 报 `otel_status=ACTIVE`。

**排查里被排除的三个假嫌疑人**（先证伪再动刀，省下乱改）：
- Jaeger 挂了？→ 容器 `Up 13 days`、`/api/services` 200、`4318` 从 Pod 内可达（GET 得 405 = OTLP 端点正常拒绝 GET）。
- 时钟漂移把查询窗口挪空了？→ 三台机器 `date -u +%s` 差 ≤1s。
- 只有 `/query` 断？→ 同窗口 `/health` 也 0 条 ⇒ 是**全局导出断了**，不是某条路由。

**真因**（在 Pod 内用**假凭据**复现，不是推断）：`get_langfuse_callbacks()` 构造 Langfuse 客户端时把全局
TracerProvider 换成自己那份，processors 只有 `['LangfuseSpanProcessor']`（不导 OTLP）。随后 kernel
`init_tracing()` 走"复用已存在 provider"分支——该分支的前提是"宿主自带 exporter，不必白挂"——
于是**什么都不挂**，本平台的 OTLP 出口从未存在。附带还有第二半：注入 exporter 的分支把 processor
挂在随后被丢弃的自建 provider 上（孤儿）。

**反序实验**（决定修法的那一次测量）：先 `init_tracing()` 再构造 Langfuse ⇒ 全局 provider 是我们的
（带本服务 resource 与 sampler），Langfuse **复用并追加** `LangfuseSpanProcessor` ⇒
`['BatchSpanProcessor', 'LangfuseSpanProcessor']`，callback 不受影响。这就是 OTel 的标准扇出形态。

**解法（三层，缺一层就还是靠自觉）**：装配顺序上移（`applications/agent_server/main.py`）+ 复用分支
"探测不到 OTLP 出口就补挂，探测失败一律当作没有"（`packages/agent-core/agent_core/tracing.py`）+
`tests/observability/test_provider_reuse_otlp.py` 三条钉不变量。

**下次怎么提前避开**：
- 跨组件共用一个**进程级全局单例**（OTel provider / 事件循环 / 连接池 / embedder 缓存）时，
  **调用顺序就是正确性的一部分**。写"如果 A 已经设过我就复用"这类分支时，必须回答
  "复用的那个对象**真的做了我该做的事吗**"——这次的答案是"没有"，而且是**静默没有**。
- 状态灯（`otel_status`）只当"意愿"读，**判据必须是"后端里查得到本次原文"**。
- 顺序注释要写死原因（本次已写"【顺序是硬约束，别挪到下面去】"），否则下一个人会当垃圾整理回去。
- 这条缺陷本来可以在**本地** `--extra otel` 环境里提前一小时发现：同一失败在本地用例第一次跑就复现。
  ⇒ 凡是"进程内可复现"的问题（初始化顺序、provider 归属、依赖注入），**先本地复现再上现网**。

## 2. 现网读数绑定 rev，否则文档带着过期结论活着

我在 §6.2 写下的"Jaeger ✅ `e2e_traceparent.sh` 实跑通过"是在**接 Langfuse 之前**那个 Pod 上量的。
换 rev 滚动后没复跑 ⇒ 这句话在现网为假而文档为真。修法不是改措辞，是改纪律：
**每条现网读数旁边记上它属于哪个 `GIT_REV` / 哪个 Pod 名 / 什么时刻**（见 `env-126-inventory.md` §4.11 的表头）。

## 3. `verify.sh` 用 `docker run` 读镜像内容 = 读错了库

126 上 moby 与 k8s 专用 containerd-k8s 是两套互不可见的镜像库（AGENTS.md 126 §3）。
`docker run --rm agent-platform:dev cat GIT_REV` 读到的是 2 小时前**中止构建**留在 moby 的 `3cd5580`，
同期 Pod 内是 `c01e9cf` ⇒ 假 FAIL。而"同步了≠上线了 ⇒ 读回 Pod 内 `GIT_REV`"这条我早写在手册里，
**却没写进执行它的脚本**——工具和文档会各自漂移，门禁脚本也要跟着纪律改。

## 4. 构建换机后的两条硬规则

1. `distribute.sh` 的目标列表**只覆盖其余节点**；构建机自己的 containerd-k8s 要补一次本地导入
   （`docker save agent-platform:dev | ctr -a /run/containerd-k8s/containerd.sock -n k8s.io images import -`）。
   本轮新 Pod 恰好调度到 241，而 241 的 k8s 库还是旧镜像 ⇒ 可变 tag + `IfNotPresent` 下**不是报错，
   是静默跑旧代码**，比 `ErrImagePull` 更坏。
2. 判"三节点镜像内容一致"要在 **CRI 视角**比（`crictl images` 的 image id），不是 `ctr images ls`
   的 digest 列（那是 manifest/config 之别，会和 Pod 的 `imageID` 对不上而误判）。

## 5. 读"另一个系统"的数据，先读它的形状而不是它的文档

四条同源（都表现为"读数说没有，其实是我读不出"）：

- **SSE 事件帧平铺**：`_sse()` 把 `payload.type` 提成事件名，其余字段落在**顶层**。按 `d["payload"]` 读
  恒得 `{}`。确认形状的最短路径是 dump 原始响应行，而不是读客户端代码猜。
- **v4 `events_only` 撤了 v1 读数 API**：`/api/public/traces|observations|sessions|metrics` 一律 404
  且 body 明写原因；可用的是 `GET /api/public/v2/observations`。**猜错的 `fields=` 名不报错**，
  它静默返回"不含该键"的行 ⇒ "字段名错"与"真的没内容"同形。真名是 `fields=io`（还有 `usage`、
  `modelParameters,metadata`）。
- **投影互斥**：带 `fields=` 时 `name/modelId` 被挤成 null，默认投影里没有 `input/output` ⇒ 要
  "原文+用量+名字"必须两次取按 id 合并。`modelId` **在两种投影里都是 null**（模型名在库内 `model` 列、
  UI 可见）⇒ 不得声称"哪个模型"是 API 可读列。
- **多层 JSON 编码**：落库的中文是 `\uXXXX` 字面量，`ensure_ascii=False` 只能解自己那一层。
  ASCII marker 照常命中、中文 needle 恒 miss——**半对半错比全错更难发现**。解法：`_flatten()` 循环
  `json.loads` 到解不动为止。ClickHouse 侧同坑（中文按字面搜不中）。
- **先命中≠全到**：异步批处理后端里"路由那条"先落库，立刻判定就永远少读"答案那条"
  （而"input 含检索原文"只在答案那条成立）⇒ 命中后再等一个 settle 窗口复取。

## 6. 语义缓存会把取证短路成"查不到"

`query_router.py:159-179` 命中 `semantic_cache` 就直接 return，图不跑 ⇒ 没有任何模型调用 ⇒ 观测后端
本来就该是空的。此时按"查不到=没接上"报 FAIL 是**拿探针的形状冒充平台的缺陷**。
三条纪律：
1. 取证问题必须**语义新颖**——加 marker 后缀不改变语义（查重按向量相似度），改几个字没用；
   本项目做法：候选问题池轮转 + `PROBE_Q` 覆盖 + 退出码 **4 = 取证不成立但平台没错**。
2. 只读复核用 `PROBE_TRACE_ID` + `PROBE_MARKER`：观测数据已落库，重发提问既拿不到新证据又白污染缓存
   （而且这条路径不再需要平台 API_KEY，少一个凭据就少一次泄漏面）。
3. 消融/对照实验同理：第一次读数必须先证明被测链路真的走到了（`route=rag` + `evidence count>0`），
   并把**四个回放源**清零（`semantic_cache` / `memories` / `episodic+procedural_memories` /
   LangGraph `checkpoints|checkpoint_blobs|checkpoint_writes`，第四个最容易漏）。

## 7. 取证脚本自身的两个哑点

- `set -euo pipefail` + `SPANS=$(curl -sf … | grep -o … | wc -l)`：Jaeger 返回 404 时赋值处直接终止，
  **解释原因的 FAIL 行永远打印不出来**，只剩一行 "OK: /query 200" 和 exit 1。改成先落盘取 http code 再判。
- 任何"读数为空"的轮次，先判**探针是否真的跑到了**（本轮就有一次：`crictl images --no-trims` 是假 flag，
  grep 无输出被读成"节点缺镜像"）。判据形状：脚本自己先打一行标题/哨兵，多分支都打计数。

## 8. 我这台机器上的会话形状问题（与平台无关，但同样吃时间）

- **ssh 里内联 python/awk 必炸**（本轮两次：嵌套 f-string 引号、三层 awk 引号）。可靠形状始终是
  `写本地文件 → scp → ssh 'bash -s' < 文件` 或 `… python - < 文件`；凭据经 env 传入，**不进 argv**。
- **本机 Git Bash 无 `python3`**，Windows 版 `python` 看不见 bash 写的 `/tmp`。
- **长命令要显式给工具 timeout 或走后台**：默认 2 分钟，超时后输出整块丢失（本轮 `make` 类三连就是这样丢的）。
- `git commit -m "$(cat <<'EOF' …)"` 在长中文+全角引号下会让**整条命令解析失败**（一个命令都没执行）
  ⇒ 长消息一律 `git commit -F <文件>`。
- 暂存按文件名，不用 `git add -A <目录>`（本轮把一份未审的未跟踪文档扫进了 `f45b8a5`）。
