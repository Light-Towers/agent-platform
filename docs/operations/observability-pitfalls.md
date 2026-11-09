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
| 13 | 三个 `pkill -f` 把自己 ssh 会话杀了（本轮之前两次） | **自匹配**：模式匹配到自己的命令行 | 用括号技巧 `pkill -f "[d]ocker build"`，杀完必须回读真实进程状态（**只读版同族错法见 24**——`pgrep` 不杀进程，但会给你一条**假在场**证据） |
| 14 | `git add -A docs` 把一份没审过的未跟踪文档扫进提交 | **暂存范围过宽** | 按文件名 `git add <path>`；提交前 `git status` 复核 included 内容 |
| 15 | 「Jaeger 里没有 `POST /query`」 | **探针淹没**：`GET /health` 每 5s 一条把 `limit=40` 窗口刷满（`deploy/k8s/VERIFICATION.md` §C 第 4 条早已写明这条，我当天仍重犯） | 查询必须带 `operation=` 精查，不用大 `limit` 捞全量 |
| 16 | 清库时漏删一行残留 | **肉眼列 id 而不是让谓词挑**（我的谓词命中 67，手写的集合是 68–73） | `WHERE id = ANY(谓词查出来的集合)` + `DELETE … RETURNING` 回读被删内容 |
| 17 | 删 checkpoint 的脚本连撞两次，两次都在**删之前**失败 | **API/形状**：asyncpg 没有 `Connection.copy()`（那是 psycopg 的）；送进 `ssh 'bash -c'` 的 python 里 `"\x"` 被折叠成单反斜杠 ⇒ SyntaxError | 形状固定为 `本地文件 → ssh 'kubectl exec -i … python -' < 文件`；bytea 用 `chr(92)+"x"+hex` 拼；失败无损失正因为断言闸门在 DELETE 之前 |
| 18 | Jaeger 按 `/api/search` 查"0 条 trace" | **端点形状错**：现网这个 all-in-one build 对 `/api/search` 返回的是 **SPA 首页 HTML**（不是 JSON），`json.loads` 之前不判形状就会被读成"没有数据"；同一次提问在 UI 上还是**两棵 trace**（不带 `traceparent` ⇒ 两路埋点各自起根），只点 1-span 那棵会误判"链路是空的" | 查询一律用 `/api/traces?service=&operation=&limit=`；先判响应是不是 JSON 再数条数；按 `otel.scope.name=agent-platform` 筛"有内容的那棵" |
| 19 | 我写下"Jaeger 属性里刻意没有 prompt 与输出文本" | **单样本过度概括**（同族第 9 次）：我只数了一条 3-span 的 `/query`（`POST /query` + `fastapi.dependencies/endpoint`，那条里**没有 `ChatOpenAI` span**），就把"我们 kernel 只写脱敏属性"推广成"Jaeger 里没有原文" | 结论要覆盖**每一条 scope 的 span**：`agent-platform` 那条确实只有脱敏位，但 `otel.scope.name=langfuse-sdk` 的 `ChatOpenAI` span 带 `langfuse.observation.input/output/model.name/usage_details` ⇒ **原文与模型名都在**（需求方一张截图逼出来的）。下这类"某面没有 X"的断言前，先把该 trace 全部 span 的 tag 键列一遍 |
| 20 | 我写下"官方页抓取不可达，属性名待固定版本复核" | **把 404 读成不可达**：官网 `opentelemetry.io/docs/specs/semconv/gen-ai/` 早已是 **Moved 存根**（正文迁到 `open-telemetry/semantic-conventions-genai`），而我按印象猜路径（目录是 `gen-ai` 不是 `genai`）拿到 404，两层错叠在一起就写成了"不可达"。同族还有一个变体：推理 span 的正文在 `client-inference.md`，`gen-ai-spans.md` 里只做跳转 ⇒ 只读一个文件会误报"某属性没定义" | **404 与不可达是两种读数，必须分开报**。标准原文一律直取仓库：`gh api "repos/<org>/<repo>/contents/<path>" --jq .content \| base64 -d`（本机 `gh` 已登录即可，不依赖浏览器与官网）；结论落文档时同时记**锚定版本**（本次 v1.44.0）与复核命令。命令里反引号要落在单引号表达式内（双引号会被 shell 当命令替换） |
| 21 | 「四类回放源已清零 ⇒ 屏上不会有取证残留」 | **把"清过库"当成"屏上干净"**：10-13 清空之后新发生的合法问答照样写进记忆面，其中一条元问题（"我之前问了哪些问题？"）的答案文本自带 `LFPROOF-*` / `e2e-*` 标记，10-14 浏览器实拍时**被当普通业务内容回放**到屏上 | 判据要换成"**当天会问什么**"而不是"清过没有"：演示当天避开元问题、开场先跑一遍业务问答把面板换掉（台账 ㉔）。清库对这一类无效 |
| 22 | 我写下「KS 容器 `docker diff` 里**没有** .py 热改」 | **探针形状错**（同族第 4 次，与 18/20 一路）：过滤式写成 `grep -E "^C? M? A? .*\.py$"`，而 `docker diff` 的行形状是 `C /app/...`——第二个字面空格在 "C " 之后并不存在，整个式子恒不匹配 ⇒ 输出空，被我读成"没有热改" | 判"没有 X"之前先跑**不加过滤**的原始输出看形状（本次重跑：`docker diff` 共 68 项、`.py` 9 个）。`docker diff` 的行首只有一位字母（`A`/`C`/`D`），不要按"CMAS 可组合"去写正则 |
| 23 | 我差点写下"三节点镜像 digest 与 Pod `imageID` 不一致 ⇒ 漂移" | **两种 digest 天然不相等**（2026-10-14 三机复测）：`ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images ls` 给的是 **manifest** digest（本轮三台同为 `sha256:adf6a2bc3193…`，type=`application/vnd.oci.image.manifest.v1+json`），而 k8s `status.imageID` 与 `docker images` 给的是 **config/镜像 ID**（`c18dc76a93f8…`）。同一条命令里还把**列序读错**（实际 REF/TYPE/DIGEST/SIZE，我按 `$3=SIZE` 取），第一次输出的 size 栏是 digest 前缀 | 写"三节点一致"必须**指明是哪一个 digest**；跨工具比镜像只比"同一层语义"的字段。任何 awk 取列先原样 `head -1` 看一次列序（与 22 同一教训：**先读形状**） |
| 24 | `pgrep -af 'port.forward agent-platform'` 经 ssh 执行**匹配到自己** | 只读版自匹配（13 那条的姊妹）：远端 `bash -c` 的 argv 里就含该模式，于是打印出我自己的 ssh/timeout/bash 三行，看着像"port-forward 进程还在" | 判"转发在不在"唯一算数的读数是 `ss -ltnp \| grep :18000`（本轮：`0.0.0.0:18000 users:(("kubectl",pid=3496802))`）。模式一律用括号技巧 `[p]ort-forward`，且**回读要用另一条命令** |
| 25 | 语义缓存 L2「看着是对的」：`VectorField` 平铺传参、`Query.add_param`、`RETURN 2 value_json distance` 三处都先按印象写过 | **未证实的第三方形状**。前两条已被打回，第三条是本轮查上游才发现：`distance` 是 KNN 结果别名而不是文档字段，而 valkey-search 的 RETURN 解析器（`src/commands/ft_search_parser.cc`）对查不到的名字**原样保留、不报错**，"带了 RETURN 还取不取得到距离"未证实。根子上是这套代码**从未在真 Valkey 上跑过**（工作区未提交 ⇒ CI 契约作业没执行），所以"印象"没有对手 | 断言只写在两样东西上：上游原文（`gh api repos/valkey-io/valkey-search/contents/docs/commands/ft.search.md`（**main**）—— dialect 只支持 2（pin 那版源码实际接受 2..4，见第 26 行）；官方向量示例不带 RETURN，回复里距离与哈希字段同时在场）与**库自己的组装器**（测试用 `_ArgvCapture` 调 `SearchCommands._mk_query_args` 生成真 argv，不抄它的输出形状）。未证实的形状一律不用。同一份文档还给了 `@tag:{x*}` 是**前缀匹配** ⇒ 租户名以 `*` 结尾且漏转义就是跨租户读，与 AGENTS.md「先读形状」同一课，只是对象换成了客户端库和模块 |
| 26 | 查完"上游支不支持 CASESENSITIVE / dialect 2 / FT.INFO 的 `state`"，得出的结论是**部署 pin 的那个版本不支持**，准备换镜像 | **读了另一个版本的文档**：核对用的是 `main` 分支的 docs，而 pin（**当时**是 valkey-bundle 9.0.1，该坐标后来按真机读数改回 9.1.2，见第 27 行）内含的是 valkey-search **1.0.2**；1.0 分支的 `ft.create.md` 里 CASESENSITIVE **出现 0 次**、`ft.search.md` 缺 dialect 那句 ⇒ 文档沉默被当成了特性缺失。真去 grep 1.0.2 的源码，特性全在（`ft_create_parser.cc:77/:231`、`ft_search_parser.cc:218` 接受 2..4、`index_schema.cc:744` + `:667-672`）。**同批还有第二种版本错位**：ADR 与生产清单里写的 `notify.c:125`/`attribute_data_type.h:67-69`/`index_schema.h:63` 这些行号只有 main 对得上，pin 上是 `:124`/`:76-77`/`schema_manager.cc:121`——行号是随 ref 漂移的量，不标 ref 就是给后人埋死锚（我这轮自己就被自己的注记挡了一次） | 两条纪律：① **特性存在性查源码 tarball，不查分支文档**；② 引用上游代码位置一律写成「数字 + 所属 ref」，换 pin 必须重取。唯一真按版本变的是**报错措辞**（1.0.2 是 `Index with name 'X' not found`，main 多个 ` in database N` 后缀），所以自愈谓词的两组形状各自都有参数化用例，正反双向都在（§4 反证见 ADR-0013 §11 第 19 行） |
| 27 | 我写下"valkey-io/valkey-bundle 的 release 列表只到 9.0.1 ⇒ bundle **没发过** 9.1.x ⇒ 现网照 9.1.2 上线即 `ErrImagePull`"，并据此把**六处执行件**的镜像坐标改掉 | **拿错证据源**：git 的 tag/release 列表与 Docker Hub 的镜像 tag 是**两个命名空间**——镜像可以不对应任何 git 标签发布。本机与测试机都取不到 Docker Hub（curl 空返回），我却在"取不到"的情况下把推断写成了事实。真机读数（241）：`valkey/valkey-bundle:9.1.2` 实体存在、`lf-valkey` 用它健康跑了 **12 天**、实例 `valkey_version:9.1.1`、`MODULE LIST` 的 `search ver=66049` 按 `(major<<16)\|(minor<<8)\|patch` 解出 **1.2.1**；另一台同 tag 有 `RepoDigests`（`sha256:1c39295c…`）⇒ registry 确实发布过。**反向的坑**：241 那份 `RepoDigests` 是空数组，因为它是 `docker load` 进去的——空数组不等于没发布，别拿它当反证 | 判"某镜像坐标存不存在"只有两种取证：`docker pull`/`docker images`（现场）或 registry API；**仓库 git 标签不是证据**。取不到证据时的正确动作是把判据标为"未证实"并**保留原值**，不是反过来改执行件。坐标一致性由 `lint_architecture` P14 ⑤ 强制，且注记必须写"读数来源"而不是只写版本号（否则下一个人又会拿列表来推） |
| 28 | 一条断言"`*` 已被转义 ⇒ 星号租户不会前缀匹配到别人"的用例长期绿，我以为隔离面堵住了 | **测具不解释语义**：wire 用例用的是 fake client，它只记录"发出去的 argv 里有没有反斜杠"，**不解释查询串**——所以这类"我们发了转义"的断言在 fake 上恒真，永远挡不住转义本身无效。真机（9.1.2/search 1.2.1）判别集 `{acme, acmeX, "acme*"}`：`@tenant:{acme*}` 命中 3 条（前缀匹配成立，隐患为真），`@tenant:{acme\*}` **同样命中 3 条** ⇒ 反斜杠被引擎忽略、星号仍是通配符，`_escape_tag()` 对 `*` 无效。对照组证明这不是测具问题：TAG 分隔符那根竖线**加反斜杠**时转义有效（命中 1 条=字面那个值），**不加反斜杠**时被当 OR 解析（命中 0 条） | 转义不掉就**拒绝**：隔离维度以 `*` 结尾一律 fail-closed（`_tag_reject_reason` 单一判据点，读写两路共用），并单独计 `skipped_unsafe_tag`（"配置里有非法隔离值" ≠ "没带租户"）。用例改成**断言引擎行为本身**：同一份数据发两种查询串比命中数（转义若真生效必须不同），实现被拒的断言写在"根本没发出查询 + 计数"上。通用一条：**fake 测具上的"形状断言"不能替代真机语义断言**，凡判据依赖被调用方的解释规则，就要有一条打到真引擎的用例（本机 skip / CI 必跑的那个边界要显式声明） |
| 29 | 语义缓存契约用例首跑四条红，报错是 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 in position 2`，第一眼像"中文/编码问题" | **线格式，不是编码**：客户端建在 `decode_responses=True`，而 L2 哈希里存着原始 float32 的 `query_vec`；实现此前刻意**不发 RETURN**（理由是"KNN 别名能不能进 RETURN 未证实"）⇒ 引擎把向量一起回传，valkey-py 逐字段解码即崩，再被 fail-open 吞成永久 miss。`distance` 别名实测**能**进 RETURN，所以那个"少依赖一个未证实前提"的决定本身就站不住 | 读路径显式 `.return_fields("value_json","distance")`，只回真正要用的文本字段；wire 用例钉"必发 RETURN 且向量不许在里面"。通用一条：**声明式客户端 + decode_responses=True 遇上任何二进制字段就是地雷**，凡是"回全部字段"的读法都要先问一句里面有没有 bytes。（第 25 行那条"未证实的形状一律不用"在这里反过来咬了一口：删依赖的代价是把崩溃换成静默） |
| 30 | 我差点把"变异后十条红"记成"隔离用例有牙" | **红得多 ≠ 红得对**：我改查询串做反证（换成通配、换成负向谓词、整段删子句），改出来的串真机根本不接受 ⇒ 谁都命中不了，连不相关的用例都红；另一轮的红其实是专用实例 **maxmemory 打满**（`volatile-lru` 不淘汰索引/HNSW 结构，多轮各建索引把 256mb 吃光，SET 直接被拒） | 反证只认"恰好红目标那几条 + 断言原文就是那个性质"（本轮达标的一刀：整段删租户子句、其余保持有效语法、`py_compile` 核对 ⇒ 恰好 3 条红且原文是 `assert CacheHit(layer='l2') is None`）；跨轮复用同一台实例时**每轮先 FLUSHALL**，并先读 `E` 行原文再数条数。同族教训：`docs/operations/evidence-format.md` §4 的空转反证 |
| 31 | 契约里"运维摘掉索引后自愈"那条一上来就红在**清理动作**上：`wrong number of arguments for 'FT.DROPINDEX' command` | **客户端缺陷**：valkey-py 6.2.0 的 `ft().dropindex()` 在 `delete_documents=False` 分支把空串当第三个参数发出（`FT.DROPINDEX <idx> ""`）；只有带 `DD` 的那条路径走得通。`bench_cache.py` 的清理同样静默失败，只留一句 warning | 运维与用例一律发裸命令 `execute_command("FT.DROPINDEX", idx)`；判"某个便捷方法可用"要按分支判（同一函数两条分支一边能用一边不能用是常见的）。另记：真机取证时的依赖闭包要**从包顶层 `__init__` 起走**，只扫实现文件的 import 会漏掉 `agent_runtime/__init__` → `schemas` → pydantic/shared_schemas 这条链 |
| 32 | 我把六条隔离用例"改强了"（读侧统一换措辞，强制走 L2），然后 m09 变异——**把租户从 L1 精确键里摘掉**——在本地和真机都不红（真机 19 passed） | **改一条断言的路径 ≠ 整体覆盖不变**：那六条用例原来还兼着一条我没意识到的路径——"同一句话换个租户也必须读不到"（L1 面）。我把读侧措辞全换成"另一种说法"以后，L1 的跨租户那格再没人守，而 L2 的 TAG 过滤、CASESENSITIVE、索引分区都还在，缺陷只在最快、最容易被当成已覆盖的那一层暴露 | ① 换判据路径时当场问"**这条断言原来还兼着哪条路径**"，被让出的路径要显式补一条；② 判缺口用**变异**而不是直觉或覆盖率——本轮就是把 17 个变异逐个下刀才发现的（仪表：`make mutation-cache`，`scripts/mutation_cache_branches.py`）；③ 假客户端层与真机层的杀死集合要**分开声明**（`ENGINE_OWNED`），声明比"杀得越多越好"更可核对：集合漂移只有"用例退化"或"用例依赖了假层没有的解释能力"两种解释，都得人定性 |
| 33 | 全量战役跑到某个变异体后 10 分钟不动，最后一行仍是 `bool:Or→And L701 KILLED`，我第一反应是**引擎死了** | **不是死，是挂**：那一刀让套件卡在真实等待上，而 `_run()` 当时**没有超时** ⇒ 引擎在等子进程，被检目录 meanwhile 一直停在 `ast.unparse` 出来的无注释版本上——共享工作区里这正是"下一条提交把我的半成品带走"的入口 | 四条一起补：单刀 `--timeout`（默认 180s，超时**计为被杀但另标 `timed_out`**，因为"跑挂"不等于"暴露缺陷"）；不再走 shell（`shell=True` 下 kill 只落在 cmd.exe，pytest 变孤儿继续占着文件）；`atexit` + SIGINT/SIGTERM/SIGBREAK 都按字节还原；开跑前把原始字节快照到 `.tmp-scratch/mutation-snap/`。**判"卡住 vs 在跑"用进程表 + 被检文件 sha256 漂移，不用日志** |
| 34 | 后台起的战役"一条输出都没有"，日志文件 0 字节，我按"没启动成功"去查进程 | **重定向后 stdout 是块缓冲**（≈8KB 才刷一次盘），进程活得好好的；反向也成立：**日志在动不代表在推进**（同一行被反复读会误判成卡住，本轮就是这么误判了一次） | 要边跑边看就 `python -u` 启动（或 `PYTHONUNBUFFERED=1`）；否则按上一条的判活手段来，别拿日志当心跳 |
| 35 | 一把只读量具 rc=1、零输出，看上去像"账面被抓了" | **native 命令的 stderr 会杀死整把 PowerShell 工具**（刀㊶ 实踩）：git 的 CRLF advice（`warning: in the working copy … CRLF will be replaced by LF`）走的是 stderr，而 `$ErrorActionPreference='Stop'` + 重定向下它被包成 NativeCommandError 并**终止脚本** ⇒ 工具死在第一个文件上，一条真判据都没跑 | stderr 文本 ≠ 失败：**git 调用收敛到一个出口**，调用期间临时降 EAP、**只以 rc 为判据并把 rc 计数**（git 真失败绝不允许静默返回空数组——空数组与"这个文件没有新增行"同形 = 静默旁路）；门件侧另加一枚 `TOOL-DIED-NO-VERDICT` 把"量具瞎"与"账面被抓"分开。⚠ 调用点必须以数组传参（`-gargs @('diff','-U0',…,'--',$f)`），因为 PS 会把以 `-` 开头的 token 当**参数名**解析 |
| 36 | 一条种进去的假时间戳，第二轮变成"可证"了 | **「判决自己的日志」变成证据源**：反证的 stdout 必落盘成件，若那些件又被 corpus 读进来 ⇒ "假戳曾在某份日志里出现过"把可证性格磨成恒真（本轮没出假绿纯属侥幸：那次正好读失败） | 按**内容**排除判决日志（行首 `<<< `，或 `TS_RC=` / `GATE_RC=` / `TYPO_RC=` 这类判决锚），而不是靠无穷无尽的临时件名；排除只加在无人评审的本机 scratch 面，入库面照旧当证据。⚠ 方向要说清：排除 corpus 只会让本格**更容易报红**，造不出假绿；而"排除有没有失效"靠自测双向自证，不靠自觉 |
| 37 | 加了"本轮启动后被写的件不入 corpus"这条过滤，读数里 `inflight-skipped=0` 而 `read-failures=2` | **mtime 排除规则实测从不生效**：写句柄在 flush 前不更新 mtime ⇒ 那是一条"看着在过滤、实际一次也没跑"的规则 | 要排除 in-flight 文件就用**内容指纹**或共享读（`FileShare.ReadWrite`）消除读失败本身；单件读不到不能整把工具死、也不能静默跳过 ⇒ 逐件 try/catch + **计数** + fail-closed 报红。任何"装了过滤但计数为 0"都要当成量具缺陷查，而不是当成"本轮没有这种件" |
| 38 | 一条单行命令执行后终端挂在 `>>`，第一眼像"命令在跑" | **PowerShell 的双引号串不能以反引号收尾**（刀㊶ 实踩）：递一个以 Markdown 反引号结尾的字符串会把闭引号吃掉 ⇒ 命令未闭合、**一个字都没执行**，而它要改的文件（往台账追加）看起来"可能已经写了" | 先证明"没发生"再决定怎么改：比 SHA（与备份同串）+ 行数 + mtime，三条都对才敢说文件未动；然后把"种入 / 还原"拆成**两件独立脚本**、串里不放反引号（纯 ASCII 哨兵行）。顺带落那条在册纪律：破坏性自证的还原不写在种入件末尾 |
| 39 | 同一型单字错字写到第五次，而且这次是在一次"只是重排文案"的编辑里出现的 | **齿只看得见形状，看不见意图**：那个单字在入库面还要留给"点名登记这个错字"的合法自指，所以不能抬成硬 0；而一次意图 no-op 的编辑同样能替换单个汉字 ⇒ "这次不算改动"这个判断本身不可信 | 按**两字形状**加码点齿（脚本里按码点构造，不在文件里落字面），并当场用按码点构造的样件跑真工具做正控制（同时验正字未被吞 = 假阳性那一侧也要测）；纪律侧：逐字读 diff 回显**不按编辑意图分级**。⚠ 陈述方别把"我看出来了"写成"齿拦下来了"——本轮两次都是人眼先看见 |
| 40 | 门件终跑判红，红的不是账面而是新装那枚齿的自测格（`forbidden=0`，期望 2） | **合成样件的构造式静默改变了被测形状**（刀㊶ 实踩）：PowerShell 里 `$arr -join '' + ' / '` 因 `+` 优先级高于 `-join` 而解析成 `$arr -join ('' + ' / ')` ⇒ 分隔符成了 `' / '`，两个汉字被隔开 ⇒ 二字形状不连续 ⇒ 那格恒读 0，而 0 正是"齿是装饰"的读数 | 修构造式而不是降期望值（外层括号先把 `-join ''` 固定住）；**合成样件必须逐字符核形状连续**，判据是码点 dump 不是"代码看着对"。本轮对照实取（件 k46-join-probe.txt）：buggy 样件码点 `62C4 0020 002F 0020 9519` ⇒ `forbidden=0`・HIT-CP 0 条；fixed 样件 `62C4 9519 0020 002F 0020 6247 63CF` ⇒ `forbidden=2`・HIT-CP 2 条，两次 `rc=0`（量具活着，判决可信）。⚠ 这格能红本身就是收益：自测不成立时门件红给你看，装饰齿上不了线 |

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
**每条现网读数旁边记上它属于哪个 `GIT_REV` / 哪个 Pod 名 / 什么时刻**（见 `docs/operations/env-126-inventory.md` §4.11 的表头）。

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

`applications/agent_server/api/query_router.py:167-201`（缓存查询块 `:167-186`、命中分支 `if cached:` 在 `:187`、旁路 SSE `:197-199`；原记 `query_router.py:159-179` 已漂移，该窗口现在是 coordinator 占位与缓存查询）命中 `semantic_cache` 就直接 return，图不跑 ⇒ 没有任何模型调用 ⇒ 观测后端
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

## 8. 演示前的数据卫生（观众会当场念出来的那一类）

平台的自观测表是**真数据**，所以取证残留会当成"历史"念给观众：

- **`semantic_cache`**：现场问"我之前问了哪些问题？"会走 **sql 能力**，模型自己写
  `SELECT id, question, answer … FROM semantic_cache ORDER BY created_at` 把清单念出来。
  2026-10-13 实测该表 16 行里 **7 行是我的取证句**（`LFPROOF-…`／`SHAPECHECK-1`／`同窗对照-…`／
  `e2e取证-…`／`e2e复验-…`），已按谓词清理，剩 9 行真实内容。**这些 id 会变，别引用行数，复跑谓词查询。**
- **LangGraph checkpoints（`/history` 面板）**：同一批探针句在会话状态里**还有 8 条**。2026-10-13 **10:27 UTC**
  已拍板 **整桶清空并执行完毕**（备份后删；宿主 +0800 显示 18:27），删后读数：`checkpoints`/`checkpoint_blobs`/
  `checkpoint_writes` 三表 `tenant-default` 桶与全表同为 **0**，`/history?session_id=tenant-default` →
  **HTTP 200 `count=0`**，`/health` 仍 200。⇒ 控制台历史面板现在是空的，演示时**第一轮真实问答就是面板的第一条内容**，
  别把"面板空白"讲成缺陷，要讲成"从这一句开始记账"。
- **为什么只能整桶、不能挑着删**（动手前查出来的，别再走一遍弯路）：checkpointer 只保留**最新一条**
  checkpoint 行（1 行装下整段会话），消息不是独立的表行，而是序列化在 `checkpoint_blobs` 的 channel
  value 里；`identity_mode=single` 又把前端传的任意 `session_id` 折叠成 `tenant-default` ⇒
  **既没有"某一句"的删除锚点，也没有更早的快照可回退**（`/session/revert` 是时间旅行，需要前序快照）。
  备份只能整桶还原原状（含探针句），所以取舍只有"全清 / 全不清"两档。
- **备份与恢复的诚实边界**：备份在 `126:/tmp/ckpt-backup-host/*.csv`（0600，
  `checkpoints.csv` 472B md5 `4e05aca7…`、`checkpoint_blobs.csv` 289052B md5 `22c10dd2…`、
  `checkpoint_writes.csv` 79B md5 `fb97a3bb…`）。它在宿主 `/tmp`，**主机重启即失**；且
  **恢复路径（`COPY … FROM csv` 回灌）我没有实跑验证过**——把它当"能恢复"用之前先测一次。
- 清理纪律：**用谓词挑集合**（`WHERE question ~ 'LFPROOF|SHAPECHECK|同窗对照|e2e取证|e2e复验|取证标记'`），
  且 `DELETE … RETURNING id, left(question,56)` 打印被删内容 + 删后回读残留计数 = 0。
  我第一遍是肉眼列的 id 集合，结果**漏删一行、多包含一条不在谓词里的**（坑档表第 16 行）。
- 删前的硬闸门：**先备份、断言备份非空，再 DELETE**（`assert size > 0`），删除按 FK 顺序
  `checkpoint_writes → checkpoint_blobs → checkpoints`，删后逐表回读"该桶 + 全表"两个数。
  这段脚本连撞两次工具形状（都在**删之前**失败，数据无恙）：asyncpg **没有** `Connection.copy()`
  （那是 psycopg 的 API），以及把 python 送进 `ssh 'bash -c'` 时 `"\x"` 被折叠成单反斜杠 ⇒ SyntaxError；
  可靠形状是 `写本地文件 → ssh 'kubectl exec -i … -- python -' < 文件`，bytea 用 `chr(92) + "x" + hex` 拼。
- 残留行还有第二重代价：它们躺在**语义缓存**里，会以高相似度抢走后续提问的命中（取证问题因此必须
  **语义新颖**，见 §6）。

### R19 的归因方法（读 `otel.scope.name`，别猜标签）

同一个请求的两条 `POST /query` SERVER span，一条来自 **FastAPI 自带 native telemetry**
（`otel.scope.name=fastapi`，新 semconv：`http.request.method`/`url.path`/`server.address`），
一条来自**我们的 kernel 中间件**（`otel.scope.name=agent-platform`，旧 semconv：`http.method`/`http.target`）。

- **别用 `http.route` vs `http.target` 当归属判据**——那只是 semconv 代际差异的副产物，版本一换就骗人。
- **可见形状取决于客户端带不带 `traceparent`**：带 ⇒ 两条 span 在同一 trace 里互为兄弟；
  不带（浏览器真实点击）⇒ 两路各自起根，屏幕上变成**两棵独立 trace**（成对的 1-span + 5|6-span）。
  ⇒ 演示前若不改，口径必须按"两条独立 trace"讲；这一条决定现场怎么解释，也决定改动值不值。
- **状态灯/附录不是台账**：R19 早在 `deploy/k8s/VERIFICATION.md` §C 定性并转了 issue #23，但因为写在附录里，
  演示前没人会翻 ⇒ 已提升到 `docs/operations/minimal-release-runbook.md` §9 作为第 **⑲** 条待拍板项。**凡是"当场会被观众
  看到"的既存缺陷，都要进那张带责任人与时点的台账，而不是留在技术附录。**

## 9. 我这台机器上的会话形状问题（与平台无关，但同样吃时间）

- **本机 TCP connect 探针一律假阳性**（2026-10-13 实测）python socket 与 `/dev/tcp` 对 126 的
  22/16686/18000/**以及我随手编的 2222 和 80** 全部报"TCP已连"，而同一时刻应用层 curl 对 126 的三个口
  都是 `HTTP 000`、对 241:3000 是 `HTTP 200` ⇒ **这台机器到内网的 connect 层被中间层接管，读数无意义**。
  判"某个 UI 能不能打开"**只能用应用层**（HTTP 状态码 + `size_download` + `time_total`），并且**必须带对照组**
  （编一个不存在的端口；它也"通"就说明探针废了）。我差点拿这组废读数去解释 Jaeger 为什么打不开。
  **成因已查到顶**：PowerShell `Test-NetConnection` 同样对**编造的 2222 端口**报 `TCP=True`、对全部目标报
  `Ping=False`，公网 `api.github.com` 返回 **403 拦截页**，显式走 `127.0.0.1:7897` 返回 **502**，且网卡里有
  `Meta Tunnel 198.18.0.1/30`（fake-ip 段）+ OpenVPN TAP/ODC ⇒ **这台机器上有个代理客户端在 TUN 模式接管全部流量**。
  后果：**本机任何"连得上吗"的读数都没有意义**，`<internal-ip>` 通不通由那个客户端的放行规则决定，与应用层
  代理设置 `ProxyOverride` 无关（TUN 不看这个）。⇒ 现网取证要么在该客户端里把内网网段设为 DIRECT，
  要么换一台不装它的机器/跳板。**在这种机器上"我的 curl 打不开"绝不能写成"服务不可用"。**
- **到 `<internal-ip>/24` 的整段路由会无预兆消失，而且症状会伪装成"某个服务挂了"**（2026-10-13 10:33 UTC 起实测）：
  126 的 18000/16686 与 241 的 3000 五个 URL **全部 `000/5.0s`**（含需求方声称能打开的那一个）；**强行走系统代理
  `127.0.0.1:7897` 得到 502** ⇒ 代理自己也够不着；连 102 网段的 `<internal-ip>:22` 都超时；但公网活着
  （`https://1.1.1.1/` → 301）。本机**没有任何接口在 100 网段**（`以太网 2` = <internal-ip>/24，另有 Meta Tunnel
  198.18.0.1/30 的 fake-ip 段 + OpenVPN TAP/ODC 两张虚拟卡），`ProxyEnable=1` 且 `ProxyOverride` 含 `<internal-ip>`
  ⇒ 内网本应绕过代理直连。**结论：这台机器的内网可达性由那个代理/VPN 客户端的路由接管决定，它一抖，控制台 +
  Langfuse + Jaeger 三个入口同时不可达，且成因是同一个。** 判别顺序（下次别再从"服务挂了"开始猜）：
  ① 先用一个**已知可达**的内网 URL 做对照；② 对照组也 `000/5s` ⇒ 是**这台机器的路**，不是被测服务；
  ③ 再分直连与走代理各打一次，代理回 502 而直连超时 ⇒ 客户端没路由，去查代理/TUN，不要去查平台；
  ④ **别拿"我 curl 得到 000"去写任何关于服务状态的结论**（本轮我差点把 Jaeger 写成"绑定限制"，实际两口都在 `0.0.0.0`，
  见 `jaeger.sh:25` 与 `docker-compose.langfuse.yml:97`）。
- **ssh 连续快速连接会把两台主机都关在 kex 之外**（`kex_exchange_identification: Connection closed by remote host`，
  126 与 241 同症状，几分钟前还能通）⇒ 像是 sshd MaxStartups 限流。取证据时**一次连接里把要读的东西全读完**，
  不要一个事实一次 ssh。

- **ssh 里内联 python/awk 必炸**（本轮两次：嵌套 f-string 引号、三层 awk 引号）。可靠形状始终是
  `写本地文件 → scp → ssh 'bash -s' < 文件` 或 `… python - < 文件`；凭据经 env 传入，**不进 argv**。
- **本机 Git Bash 无 `python3`**，Windows 版 `python` 看不见 bash 写的 `/tmp`。
- **长命令要显式给工具 timeout 或走后台**：默认 2 分钟，超时后输出整块丢失（本轮 `make` 类三连就是这样丢的）。
- `git commit -m "$(cat <<'EOF' …)"` 在长中文+全角引号下会让**整条命令解析失败**（一个命令都没执行）
  ⇒ 长消息一律 `git commit -F <文件>`。
- 暂存按文件名，不用 `git add -A <目录>`（本轮把一份未审的未跟踪文档扫进了 `f45b8a5`）。
- **`git checkout HEAD -- <文件>` 不是"撤销我刚才那一处编辑"**（2026-10-25 我自己踩）：
  现象——想回退我在联邦 `agent/cache/semantic_cache.py` 里新加的一处门禁，跑完这条命令后文件变回 HEAD 的
  **双轨旧版**，还 import 本工作流早已删掉的 `agent/cache/layers.py`。
  假因——我把它当成定向回退（"只退我这几行"）。
  真因——该文件是**已跟踪**文件，HEAD 里根本没有 ADR-0013 C Stage 2 的那次重写；`checkout HEAD --` 恢复到最近
  一次提交，等于把本工作流里**不是我写的未提交改动**一起抹掉。我按行编辑时只看自己那几行，看不见同一文件里
  别人的未提交工作，于是"看起来只退了我一处"。
  修法——**撤回自己的编辑一律用反向 Edit（old/new 互换），不对已跟踪文件用 git 定向回退**；确实要用 git 时，
  先 `git diff -- <文件>` 看清相对 HEAD 这份文件里还混着谁的改动，并先把整份文件 `cp` 进 `.tmp-scratch/` 再动。
  本次恢复靠会话里此前完整 Read 到的原文重写，重写后 `uv run pytest applications/agent_federation/tests -q`
  = **192 passed, 1 skipped**（rev 口径：`62ef617` + 本工作流未提交改动，同 §1 字段 1）才算完。
  代价——一个往返；更贵的是"旧版被 import 已删模块"这种**看起来只是多几行红**、实际会把整条 Stage 2 结论
  改写成假象的回归。判据：**`git status` 里的 `M` 只代表"与 HEAD 不同"，不代表"只有我的改动"。**
