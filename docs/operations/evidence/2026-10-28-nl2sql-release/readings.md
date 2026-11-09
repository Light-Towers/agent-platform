# 批次 6 上线取证：问数（nl2sql）终态落地 · 2026-10-28

**代码 rev**：本轮构建/分发的源 = `896f966e052e95fa6fc0129b44217eed22022f19`（分支 tip，经 `git bundle` 送达构建机）。
**上线前线上 rev** = `6ac466af2ebf2d6d9f09b1fb181525a72268bdc3`。
**本文状态**：进行中快照。§1–§3 已实跑并取得读数；§4–§7 尚未执行，按 `docs/operations/evidence-format.md` §1 字段 4 记为**未跑**，不得当完成陈述引用。

> 本文件的主语是"现网此刻是什么"，不是"打算做什么"。每条读数都绑当轮命令与时刻；换 rev 或有人手工改过线上，
> 必须重跑对应命令再引数（`AGENTS.md` 观测硬规矩第 3 条）。

## 0. 一条必须先记的事实：两条历史无共同祖先

线上 rev `6ac466af` 与本轮 tip `896f966e` 的 `git merge-base` **为空**（根提交分别为 `9e95c922` 与 `b546aa56`），
`git diff` 跨 524 文件、+50059 / −5049。⇒ "线上跑的是本分支的旧提交"这个默认假设不成立，构建源是否安全**不能靠祖先关系判**，
只能靠内容级审计。本轮对 24 个"线上有而 HEAD 无"的文件逐条分类：

| 类别 | 数量 | 定性依据 |
|---|---|---|
| 刻意退役 / 搬家 | 大部分 | HEAD 侧有同名新路径或明确删除记录 |
| nl2sql `entities/*`（5）+ `*.prompt`（5） | 10 | 重构后 obsolete：这 5 个 prompt 文件在 HEAD 已删，删除由 `applications/nl2sql-service/tests/test_i0_cleanup.py` 钉住（`_DEAD_PROMPTS` L21-27 共五项 + `test_dead_prompt_files_removed` L33-34 断言现存 `prompts/*.prompt` **恰好**为 `answer/correct_sql/generate_sql` 三个），三名各自仍是活跃调用点（`answer.py:109` / `correct_sql.py:47` / `generate_sql.py:146` 的 `load_prompt(...)`），且新增了 `alias_matcher`/`tokenizer` 等确定性实现。<br>**订正（2026-10-29 复取，rev `896f966e`）**：本行原文的两条依据都不成立——① “HEAD 全仓零 `.prompt` 引用”**过宽**：`git grep -I -n -F -e ".prompt"` 命中 **97 行 / 34 文件**，`git ls-files -- "*.prompt"` 得 **9 个**（KS 6 + nl2sql 3），nl2sql-service 内 20 处命中；② “`_prompt.py` 白名单只剩三个”**误述**：`_prompt.py` 是加载器（`load_prompt` 在其 :38），文件内 `.prompt` 字面量命中 **0 行**，三名靠**调用点 + 测试断言**约束而非白名单。<br>本行未复核项：`entities/*`（5） |
| **真缺失（旧线独有）** | **2** | `docs/analysis/2026-09-21/05-exhibition-positioning-evaluation.md`、`docs/operations/evidence/2026-10-13-business-corpus/readings.md`。**两者在 HEAD 上都是断链而不是"没用的文件"**：同目录 `INDEX.md` + `02-debt-diagnosis.md` + `04-remaining-evaluation.md` 三处指名引前者，`minimal-release-runbook.md`（3 处）+ `plans/plan-router-keyword-gate-hides-corpus-2026-10-12.md`（1 处）引后者 ⇒ 已回捞（§7 条目 7） |

旁证（内容超集方向，答的是"旧线后期的修复在不在 HEAD 里"）：HEAD 的 `deploy/k8s/scripts/verify.sh` 已含"不能靠 `docker run` 读 `GIT_REV`"的修法，
`applications/agent_server/main.py` 已含装配顺序注释与两盏 Langfuse 灯。

搬家实例：旧线的 `applications/exhibition-agent/skills/mingyang-venue-ops/live.manifest.json` 在 HEAD 侧对应 `skills/venue-ops/live.manifest.json`（`git cat-file -e HEAD:…` rc=0），是改目录不是丢文件。
evidence 目录是双向对过的：旧线 4 份 `readings.md`、HEAD 5 份，差集只落在 `2026-10-13-business-corpus/` 一项 ⇒ "缺 2 份"是逐路径比出来的数，不是估的。

> `scripts/check_doc_sync.py` 抓不到这类断链：它的存在性校验只覆盖 `AGENTS.md`/`ARCHITECTURE.md`/`README.md` 三个文件里的路径引用，`docs/` 内部互引故意不在范围内。所以"清单能跑绿"不等于 `docs/` 没有悬空链接——跨历史搬家时尤其容易留这种洞。

**结论**：构建源取 HEAD 安全；两份旧线文档已回捞，回捞当场 index OID 与旧线 blob OID 逐字相同（`460da734` / `874e4cad`），见 §7 条目 7。

## 1. 凭据面（已完成，已验证）

| 项 | 读数 |
|---|---|
| 时刻 | 2026-10-28 17:4x（+0800），控制面 `<internal-host>(126)` |
| 写入方式 | `kubectl patch -n agent-platform <obj> --type merge --patch-file <file>`（**绝不 `apply`**：`apply` 对多键对象是整对象替换，`observability-keys` 里住着 `LLM_API_KEY`） |
| `agent-platform-secrets` 键集（写后） | `DATABASE_URL, DW_DB_DSN, META_DB_DSN, POSTGRES_PASSWORD, VALKEY_URL` |
| `observability-keys` 键集（写后） | `API_KEY, INTERNAL_HMAC_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LLM_API_KEY` |
| `agent-platform-config` 键数 | **18**（9 平台 + 9 `NL2SQL_*`），`NL2SQL_*` 命中 9 |
| 对账判据 | 写前/写后键集逐一比对：既有键一个不少 + 新键在位（脚本自带 `after_check`，`RESULT: OK`、`rc=0`） |
| 值不入日志 | 全程只打印键名与 `INTERNAL_HMAC_KEY` 的字节数（43）；patch 载荷文件用完 `shred` + `rm` |
| 口令生成 | `secrets.token_urlsafe(24)`，字符集 `A-Za-z0-9-_`（构造上避开 `% @ / ? #`）；生成后用 `nl2sql_dbsql.sql` 同款正则回读自检，5 项断言全 PASS |
| 本地留档 | `applications/nl2sql-service/.env`（`.gitignore:2`）+ `.dsh/ap-release-credentials-2026-10-28.json`（`.gitignore:61:.*/`），写入前 `git check-ignore -v` 实测命中，写入后 `git status` 不含二者 |
| 滚动前快照 | `/root/b6-pre-release-snapshot-2026-10-28.json`（126 本机，`chmod 600`，`sha256=34e33733cf624dd6…`）；含 Secret 明文，**不 scp、不入仓** |

**未覆盖**：`INTERNAL_HMAC_KEY` 的四条方案级短板（对称等权不可追责 / 头格式无 `kid` ⇒ 停-换式轮换 / 无 nonce ⇒ TTL 300s 内可重放 /
无密钥熵校验）本轮只登记不修复，见 `docs/operations/unconfirmed-items.md`（§7）。

> “无密钥熵校验”的可核对化（2026-10-29 复取，rev `896f966e`）：命令 `git grep -l -F -e INTERNAL_HMAC_KEY` 得作用域 **20 个文件**，
> 再在该 20 文件内 `git grep -I -n -E -e "entropy|熵|min_length|len\(key|token_hex|太短|强度"` 读数 **1 行**，
> 而那一行就是本条断言所在的文档行 ⇒ **代码侧 0 处校验**（唯一“命中”是自指）。断言成立，但作用域是“读该键的 20 个文件”，不是字面意义的整仓。

## 2. 清单 §1 六项落差的复跑定性（只读，18:03 实取）

| 落差 # | 本轮复跑结论 |
|---|---|
| 1（`30`/`35`/`36` 从未 apply） | **成立**：LIVE 只有 `Deployment agent-platform`、`Deployment postgres` + 两个 Service，Job 列表为空 |
| 2（线上 CM 比清单多 1 键） | **拆成两半定性（18:38 双向差集复取）**：“`NL2SQL_*` 零命中”成立→已由 17:4x 的 merge patch 闭合；**“多 1 个键”是错数**——现 LIVE 与声明**双向差集为空**（18 = 18），旧 rev `6ac466af` 的 `00-config.yaml` 也只声明 9 键（`NL2SQL_` 命中 0），而 merge patch 不删键 ⇒ 9+9=18，算术上不可能多 |
| 3（缺两个 DSN） | **成立→已闭合**（§1） |
| 4（缺 `INTERNAL_HMAC_KEY`） | **成立→已闭合**（§1） |
| 5（`20` 非 optional 引用 `VALKEY_URL`） | **成立→已闭合**（§1） |
| 6（`nl2sql-service:dev` 与 `valkey-bundle` 不在 `k8s.io`） | **成立**：18:03 三台 `k8s.io` 均只有 `docker.io/library/agent-platform:dev` 与 `docker.io/pgvector/pgvector:pg16`；`valkey/valkey-bundle:9.1.2` 只在构建机 **moby** 里（`f4e009e36dea`，283MB） |

同轮取到的环境事实（apply 前必知，全部只读）：

- 节点：`<internal-host>(241)` / `<internal-host>(125)` / `<internal-host>(126)`，`kubernetes.io/hostname` 标签与节点名同值；
  **只有 (126) 有 kubeconfig**（241 上 `kubectl` 报 `localhost:8080` connection refused）。
- `postgres` Pod 落 `<internal-host>(126)` ⇒ 数据面 Job 的 `nodeSelector` 取该主机名。
- 三台的 `/opt/ap-models/hf-cache/hub` 都有 `models--BAAI--bge-small-zh-v1.5` ⇒ 36/30 的 `hostPath type: Directory` 前置齐。
- 根盘余量：(241) 23G、(125) 40G、(126) 20G。

## 3. 镜像链路：一次 IO 熔断 + 一条被证伪的前提（已验证）

**命令**：`bash deploy/k8s/scripts/build_with_io_guard.sh 896f966e… <internal-ip>(125) <internal-ip>(126)`（构建机 (241)，首次尝试）。

| 项 | 读数 |
|---|---|
| 结果 | **熔断**：`18:02:18 avg10=73%` → 连续越线 3 次 → `TRIP: IO 熔断` → `pkill docker build`，`build rc=143 sampler rc=9`，脚本 `exit 3` |
| 触发位 | `Step 8/16 : RUN pip install --no-cache-dir torch …`（CPU torch 196MB 下载 + 铺层） |
| 守卫是否该怪 | 不该。脚本头注释自己写了「换到 (241) 构建只是换了受害者，**不等于风险消失**」——咬人是设计意图 |

**被证伪的前提**（要回写 `AGENTS.md` 内网环境第 7 条）：那条把 (241) 描述成"同机只有我们自己的东西（Pod）"，
暗示 IO 尖峰无外部受害者。18:05 实取：`docker ps` 在 (241) 上有 **`lf-langfuse` / `lf-langfuse-worker` / `lf-clickhouse` /
`lf-minio` / `lf-langfuse-db`(postgres:15) / `lf-valkey`** 整套观测后端 + `exhibition-dashboard`，全部与 `vda (ROTA=1)` 同盘。
⇒ **不能为了跑完构建而关掉守卫**：观测端被打坏，本批验收里"Langfuse 按 traceId 查得到本次原文"这条判据会同时失效。

**重试策略**（用守卫自带的 env 旋钮，不改脚本语义）：`IMAGES="agent-platform:dev" IO_LIMIT=80 IO_STRIKES=6`，
即①按 tag 分次构建（守卫的 `timeout 1800` 是两个 tag 共用，分次各得 30 分钟预算），②把触发口径从"10 秒级瞬时量连续 3 次"
放宽为"连续约 60 秒超 80%"（`avg10` 是 10s 衰减量，本仓已登记过它不能当排期依据）。
**同采样守护判据**：每次轮询回读四个受害容器的 `State.Status / RestartCount / Health`，基线为 10-13 起 `restarts=0 healthy=healthy`；
构建后只要有一个 restarts 变化 ⇒ 本批不得进入发布陈述。

### 3.1 30 分钟预算也不够：实测把"慢在哪"定到了 PyPI 国际链路（18:29–18:40）

| 取数 | 读数 |
|---|---|
| Step 9 的下载清单（从日志逐行抽 `Downloading *.whl (N MB)` 求和） | **171 项 / 290.9 MB（18:33 时点未完）**，在飞的是 `scipy 35.3 MB`；而预算只剩 302s ⇒ 必被 `timeout 1800` 杀 |
| 宿主直连同一 PyPI 文件（`curl` 取 `pyyaml` 真实 wheel URL） | **2.9 MB/s**（18:30 取，`code=200`） |
| 同一个镜像、同一个包、两种容器网络 | `--network=bridge` **14s** / `--network=host` **10s**（都 rc=0）⇒ **Docker 网络路径不是瓶颈**，不必拿 `--network=host` 当修法 |
| 定性 | 慢在 **构建内 pip 对 PyPI 的单流（45–60 kB/s）**，而宿主走同一文件能到 MB/s 级 ⇒ 不是出口带宽上限、不是容器网络、不是盘（PSI 全程 1–12%） |
| 层缓存的关键好处 | 重跑后 **20 秒就回到 `Step 9/16`** —— Step 1–8（含 196 MB 的 CPU torch 层）已作为层缓存落地。⇒ 被 `timeout` 杀掉的只是**当前这个未提交层**的下载，不是整条链 |

**本轮采用的处置（可核对、不改仓库）**：`cp` 守卫脚本到 `/tmp/b6_guard.sh`，`sed` 只把两处 `timeout 1800` 换成 `timeout 10800`，
并用 `diff` 自证差异行数 = 4（= 两行各 `<`/`>`），否则拒绝使用它；`SRC_DIR`/`REPO` 仍指向真 checkout ⇒ `build.sh`/`distribute.sh`
一字未改。**为什么不直接改构建机上的 checkout**：那就是在制造本仓已经欠着的那类债（`AGENTS.md` 内网第 4 条记的 `sed -i` + `docker cp` 第二通道）——
不能用一个新债去还旧债。该数字本身为何不够，已登记为待修项（`docs/operations/unconfirmed-items.md` D24，含"是否接内网 PyPI 镜像"这个供应链取舍）。

**18:40 启动后的基线（逐字读数，供构建后比对）**：`lf-langfuse` / `lf-langfuse-worker` running `restarts=0` `started=2026-10-13T07:14:23`；
`lf-minio` / `lf-clickhouse` / `lf-langfuse-db` / `lf-valkey` running `restarts=0` `healthy` `started=2026-10-13T07:14:12`；
`exhibition-dashboard` running `restarts=0` `started=2026-09-17T09:43:15`。根盘余量 21G（used 78%）、内存 avail 11G、`PSI avg10=7.53`，
日志内越线行 = 0。（订正一处自己的探针错误：`RestartCount` 在 `docker inspect` 的**顶层**，写成 `{{.State.RestartCount}}` 会报
`map has no entry for key` 并把该列取成空——"字段存在但取错路径"同样是静默丢判据。）

**未跑（本节内）**：A1 镜像内 import 复验与 `distribute.sh` 分发回读（构建仍在进行，见 §7）。

**19:0x 中途读数（attempt A 仍在 Step 9/16）**：

| 读数 | 数值 | 为什么这条值得记 |
|---|---|---|
| Step 1–8 | 全部 `---> Using cache`（Step 8 = `RUN pip install torch --index-url .../whl/cpu`，层 `7d10d2b9d30a`） | 本轮**没有重下 196 MB 的 CPU torch**，用的是上一轮被 `timeout` 杀掉之前落地的层缓存 ⇒ §3 前面"层缓存"那行成立且有 ID 可核 |
| Step 9 累计 | 160 项 / 102.9 MB，在飞 `transformers-5.21.0 (13.0 MB)`，单流 42–46 kB/s | 与上轮同量级；Step 9 从 18:36 起算已 30 分钟 |
| 受害者 | 7 个容器 `restarts=0` / `started` 与 18:40 基线逐字相同 / `healthy` 不变 | 不劣化判据仍成立；越线行 0、`PSI avg10` 1–4% |

**量具自身的一次错（已修）**：轮询脚本把 pip 的 `Downloading` 行数当进度，而 pip 进度条是 `\r` 刷行不刷行尾
⇒ 整块输出被 `grep -c` 算成一行，18:59 / 19:02 / 19:03 三次读数都是恒定的"154 项"，看着像卡死。
决定性读数是**日志字节数 + mtime**（20 秒内 36060→36595 B 就是在写）；修法是统计前先 `tr '\r' '\n'` 拍平。
⇒ 纪律：进度指标必须能自证在动，否则下次会把"量具测不出增量"当成"构建卡住"而误杀一轮。

**attempt B 的成本预测（据上面的层 ID 推）**：`Dockerfile.nl2sql-service` 的 torch 指令与根镜像逐字相同，
但 legacy builder 的缓存键 = 指令 + **父层**，两个 Dockerfile 的 COPY 链不同 ⇒ **层缓存不复用，B 必须真下 196 MB torch**。
按实测 42–46 kB/s 单流估 70–80 分钟，加 Step 9 同量级的依赖集 ⇒ B 总时长大概率超过 A 本轮（A 因命中缓存而快）。
`--no-cache-dir` 意味着中途被 `timeout` 杀掉的那个 `RUN` 会整步重下 ⇒ 开启前必须确认 10800s 预算够（D24 登记的数字口径按 tag 分次之后要按次算，不是按轮算）。
网络出口已实取：241 `curl -sSI` 对 `download.pytorch.org/whl/cpu/` 与 `pypi.org/simple/` 均 HTTP/2 200；`python:3.11-slim` 基座在位（`541096ae9b05`）；moby 里**无 `nl2sql-service` 镜像** ⇒ 与落差 6 一致。

**19:1x 起取证链路中断（本批第一次外部阻塞，构建态因此进入"未知"而不是"成功"）**：

| 时刻 | 读数 | 它能证明什么 / 不能证明什么 |
|---|---|---|
| 19:07:35 | 最后一轮完整轮询成功：Step 9/16、160 项 / 102.9 MB、7 容器 `restarts=0`、越线行 0 | 只证明**截至该时刻**在跑且未劣化；不证明后来 |
| 19:1x | `ssh root@126` → `Connection timed out`（两次）；随后 `ssh root@241` 也超时 | 两台**同时**不通 ⇒ 不是单台故障 |
| 同窗口 | 本机 ping `100.241 / 100.126 / 100.125` 均 100% loss；ping 网关 `102.1` **通**（<1ms）；`tracert 100.241` 第 1 跳后即 `*` | 我本机网卡与网关都正常，断点在**去 100 段的路由** |
| 同窗口 | `ipconfig`：活动网卡仅 `以太网 2 = <operator-lan-ip>`，两块 **OpenVPN 适配器均 `Media disconnected`** | 到 100 段的路由是隧道提供的 ⇒ 隧道断了就能解释全部现象 |

**定性（诚实版）**：从现网侧无法交叉验证（现网入口就是这条链路），所以**区分不了"整段 down"与"只有我的隧道 down"**。
能确定的只有一件事：构建是 `nohup` 起的脱离终端进程（`/tmp/b6_guard.sh` pid=1084795，服务端 `timeout 10800`），
**不因我这边断开而停**；若 241 自身存活且出口正常，它仍在跑；若整段 down，则 pip 下载会堆到 `timeout` 预算里失败（rc=124）。
⇒ 因此本批不得把"19:07 进度良好"写成"attempt A 完成"；**A 的终态行一个字都还没读到**。

**恢复后第一轮的动作已固定为脚本**：`.tmp-scratch/b6_recover_probe.sh`（只读）。次序是刻意的：
**先问进程在不在 → 再抓终态/失败行（`OK: built` / `A1 OK` / `OK: 构建 + A1 + 分发完成` / `TRIP` / `rc=124` / `FAIL:`）
→ 才看日志停在哪儿 → 再比受害者基线**。为什么这个次序：现场手拼最常见的错是先看进度后看进程，
把"日志停在半截"读成"还在跑"。本机无可用的 bash（WSL 无发行版、无 Git bash）⇒ `bash -n` 自检只能在链路恢复后在远端做。

**中断期间确实取不到的读数（不拿推断补位）**：A 的终态与 A1 import 回读、三台 `crictl` 分发回读、attempt B 全部、
valkey 三台导入与 `MODULE LIST`、以及 §5/§6 全部。这些在取到之前都维持"未跑"。

## 4. 数据面 35：建库/建角色/L1 只读（已验证）

**命令**（控制面 (126)）：占位符替换后 `kubectl apply -f 35-applied.yaml`，替换只动一行 ——
`kubernetes.io/hostname: <internal-host>` → 实测主机名；`diff` 输出确认**仅此一行**，残留占位符数 0。

| 判据 | 读数 |
|---|---|
| server-side dry-run | `job.batch/nl2sql-dbsql created (server dry run)`（`created` 而非 `configured` ⇒ 与落差 1 一致，这是新建对象） |
| Job 结果 | `succeeded=1`（50s 完成）；Pod `nl2sql-dbsql-*` 落 `<internal-host>(126)`，`Succeeded`，`restartCount=0` |
| **L1 行为负例** | 日志自报 `OK: 写路径被库侧拒绝（L1 成立）` —— 脚本用 `nl2sql_dw_reader` 真插 `_l1_probe`，写得动就 `exit 1`；**不是**读 `GRANT SELECT` 语句 |
| 权限读数 | `orders`/`users` 的 `can_select=t`，`can_insert/update/delete/truncate` **全 f** |
| 两库 | `nl2sql_dw`、`nl2sql_meta` 均在 `pg_database` |
| 三角色 | `nl2sql_dw_owner rolcanlogin=f`（NOLOGIN 组角色）、`nl2sql_dw_reader=t`、`nl2sql_meta=t` |
| fixture 基线对账 | `users=4 / orders=6 / paid_amount=388.50` ⇒ 与 `deploy/data/nl2sql_dw_fixture.sql` 头部登记的基线逐字一致 |
| 列类型 | `orders(id bigint, user_id bigint, status varchar, amount numeric, created_at timestamp)`、`users(id bigint, name/phone/city varchar)` |

**两份 ConfigMap 的分开判据**（别混：一份装 SQL 脚本正文，一份装平台非敏感默认值）：

| CM | 判据 | 读数 |
|---|---|---|
| `nl2sql-data`（新建，5 键 = `deploy/data/*` 正文） | **内容对账而不是只数键数**：逐键 `go-template` 取原文算 md5，与构建机落地副本比 | 5 键逐一 OK；取键内容必须走 `index`（jsonpath 会把 `nl2sql_dbsql.sql` 里的点当路径分隔符 ⇒ 返空串 ⇒ 假红） |
| `agent-platform-config`（只补键、未整对象替换） | 双向差集：`comm -23` 与 `comm -13` 都为空 | 18:38 实取：**两个差集皆空**（LIVE = 声明的 18 键）；`managedFields` = `kubectl-client-side-apply/Update`（2026-09-29 建时留的 `last-applied`，512 字节）+ `kubectl-patch/Update`（本轮）⇒ 无人今天整对象替换过它 |

**rev 绑定方式**（本轮新立的口径，因为 Windows 工作区不可信）：
`.gitattributes` 是 `* text=auto eol=lf`，但本机 `core.autocrlf=true` ⇒ **仓库 blob 是 LF、工作区文件是 CRLF，而 `git status` 报干净**
（实测 `deploy/data/nl2sql_dbsql.sql` 工作区 md5 `1840abdf…` ≠ blob `ed137f22…`）。
⇒ 上线文件一律从**构建机 checkout**（Linux、与镜像同 rev）取，并用 **blob OID** 三方对账：
`git rev-parse HEAD:<path>` == `git hash-object <构建机磁盘文件>` == `git hash-object <控制面落地文件>`。
本轮 10 个上线文件（5 个 `deploy/data` + `15/20/30/35/36` 五份清单）全部相等且 `CR=0`。
**为什么这条值得写下来**：这些文件要进 ConfigMap 再被 `psql -f` 执行，而 `nl2sql_dbsql.sql` 用 `\getenv`/`\gset` 从 DSN 解析口令——
行尾多一个 `\r` 就是"建出来的角色口令带 \r、服务 DSN 不带"，而 `/health` 可能仍然绿。

## 5. 数据面 36：元库 schema + 元知识（**未跑**）

前置依赖：`nl2sql-service:dev` 镜像进 `k8s.io`（§3 进行中）。判据口径已定：
① `--status` 打出 `nl2sql_schema_meta` 的 `vector_dim=512`、`schema_version` == 迁移最高版；
② 五张表（`nl2sql_column_info` / `nl2sql_metric_info` / `nl2sql_value_info` / `nl2sql_relation_info` / `nl2sql_alias_info`）行数均 > 0，
且**由独立取数 Job 直接查库**得到，不引 Job 自述；③ `embedding` 列的 `format_type` 真读数 == `vector(512)`。
本步的 CPU 编码 + 建索引是本批唯一从未实跑过的链路。

## 6. 服务面 30 / 平台面 20（**未跑**）

判据口径已定（详见 `docs/operations/nl2sql-release-checklist.md` §3 步 8/9）：
30 看 `/ready` 两池 ok + `/health` 的 `sql_backend` == dw 真方言 + 键文件字节数 > 0 + 伪造 `X-Internal-Tenant` → 401；
20 看 rollout 完成 + Pod 内 `GIT_REV == 896f966e…` + `/health` 四盏灯（`nl2sql=true`、`sql_backend=null`、`cache_backend=valkey`、`cache_ready=true`）。
**次序不可反**：`30` 未 Ready 就不动 `20`（反了就是"问数真空窗 + 探针全绿"）。

## 7. 未跑与待办（本批内）

1. §3 的 A1 复验 + 三台分发回读（构建进行中）。
2. `valkey-bundle` 补进三台 `k8s.io`：**前置读数已实取**（19:0x，等 attempt A 收尾后执行分发）——
   源在位：241 的 moby 有 `valkey/valkey-bundle:9.1.2`（id `f4e009e36dea`、283 MB；`lf-valkey` 就是它跑着的）；
   目标缺口：`crictl --runtime-endpoint unix:///run/containerd-k8s/containerd.sock images | grep -i valkey` 在
   **241 / 125 / 126 三台都空**（241 只有 moby 那份，k8s.io 没有）⇒ 三台都要导，且 241 不能因为“构建机上有”就算齐（双运行时互不可见）。
   不走 `distribute.sh` —— 它的 tarball 路径是 `/tmp/${IMAGE%:*}.tar.gz`，
   而 `valkey/valkey-bundle` 的 `${IMAGE%:*}` **含 `/`** ⇒ 重定向进不存在的目录，`set -e` 当场断。
   这是 `distribute.sh` 对多段镜像名的真实缺陷；修它要动仓库脚本，按“先方案后编码”另行登记，本轮用等效的一次性分发脚本。
3. §5（36）、§6（30 → 20）。
4. 清单回改（**已做**，本节末尾的自错更正见下）：`docs/operations/nl2sql-release-checklist.md` —— §1 落差 2 按两半定性、
   §2 补上"双向差集为空"的强判据取法、§3 步 2/3 写明 `timeout 1800` 不足与 `distribute.sh` 多段镜像名缺陷。
   ⚠ **两处自我更正（第二处推翻第一处；rev `896f966e` + 未提交工作区，当场实取）**：
   - 第一版把一条错命令记到了清单 §2 头上 ⇒ 其中“它在清单里”这半**为假**：`git grep -n -F -e '^[A-Z0-9_]+:' HEAD -- docs/operations/nl2sql-release-checklist.md` → **rc=1（HEAD 版不含）**。
   - 但第一版的更正文面顺手写了“那条命令**本身没毛病**” ⇒ 这半被本轮实测推翻：`Select-String -Path deploy/k8s/00-config.yaml -Pattern '^[A-Z0-9_]+:'` → **0 命中**，同文件的缩进口径 `^  [A-Z][A-Z0-9_]+:` → **21 命中** ⇒ 该命令确实有毛病（对目标文件恒不命中，因为键是 2 空格缩进）。清单 §2 现用的 `jsonpath='{.data}'` + python 排键名（`checklist.md:44-45`）与 `awk '/^  [A-Z][A-Z0-9_]+:/'`（`:51`）才是对的取法。
   - 该字符串的现行出现面（两口径都报）：`git grep -n -F --untracked -e '^[A-Z0-9_]+:'` → **2 行 / 2 文件** = `checklist.md:49`（本批新加的“常见错写法”警示注释，**位置在 §2 内**）+ 本文件上一版那句；不带 `--untracked` 的默认口径 → **1 行 / 1 文件**（只剩 checklist，因本件尚未入库）。
   ⇒ 纪律两条：① **“这条命令有没有毛病”不能靠 grep 命令字符串来回答**——那只能答“它出现在哪里”，行为必须实跑该命令本身（本轮就是靠直接跑 `Select-String` 才发现自己更正错了方向）；② **“仓库里只有 N 处、且就在本行”这类断言自带过期时间**，终点是自己的下一次编辑——本行初稿那句在当时为真，同一批次往清单加了 `:49` 之后就不再是了。
5. `AGENTS.md` 内网环境第 7 条订正（**已做**）：原文“同机只有我们自己的东西”已标为被证伪，补上“241 共置整套 `lf-*` 观测栈与 `ROTA=1` 同盘 ⇒ 守卫不得关”、
   熔断口径用 `IO_LIMIT/IO_STRIKES` 调旋钮、以及本节这两个实测坑（预算不足 / 多段镜像名）的出处指引。
6. HMAC 四条短板登记（**已做**）：`docs/operations/unconfirmed-items.md` §3 新增 D23；构建链路两缺陷与内网镜像的供应链取舍登记为 D24。
7. 两份仅存在于旧线的文档回捞（**已做**，18:5x，判据见 §0）：`git checkout 6ac466af -- <两个路径>` 后 `git ls-files -s` 的 index OID
   与旧线 blob OID 逐字相同 ⇒ 内容没被 CRLF 归一改动（上面的 `460da734`/`874e4cad` 就是这一对数）。回捞核对之后，两个文件顶部各加了一行
   **回捞注记**（按本仓“历史快照加注记”的惯例，包括“红线 4 已改叫红线 1”这种编号漂移），所以现在的 blob 与旧线差那一段注记——
   **正文未改**，要逐字对旧线就拿注记以外的局部读。
   **故意不与构建混提交**：构建源必须保持 `896f966e`，中途推进 tip 会让 §3 的镜像 rev 与分支对不上；这两份文档随批次 6 的 doc-only commit 一起收。
8. 端到端取证（清单 §4 的 7 条）：`/sql/train` 写路径、`/api/query` 三条真问对账、Langfuse 原文可读、缓存非零命中、租户隔离、L2/L3 权限。
