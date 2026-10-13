# R1 上线留证 — 2026-10-13（agent-platform @ 0425257，126 k8s）

> 事后证据，判据全部来自回读，不来自命令退出码。全文不含密钥值（只出现键名）。
> 本轮改动 = 修"LLM 结构化路由 100% 静默回退"（方案⑦ R1）。方案与根因见
> `docs/plans/plan-router-keyword-gate-hides-corpus-2026-10-12.md` §8–§13。

## 1. 改了什么（两处，缺一不可）

| 文件 | 改动 | 为什么不能只改一处 |
|---|---|---|
| `applications/agent_server/agent/router.py:91` | `with_structured_output(RouteDecision, method="function_calling")` | langchain-openai 1.7.0 默认 `method='json_schema'`，现网 DeepSeek 对该类型稳定 400 |
| `packages/agent-core/agent_core/llm/fallback.py:227` | `with_structured_output(self, schema, **kwargs)` 并透传给 primary | `agent/llm.py:39` 交给 router 的是 `FallbackChatModel`，旧签名**不收 method** ⇒ 只改调用点会被这层静默丢掉 |

`tool_choice` 保持默认 `auto`，**没有**传 `required`——实测现网 DeepSeek 支持 required，但同端点 Qwen 会 400，
留 auto 才是跨模型都成立的那一档。

## 2. 上线通道六步（每步带回读）

| 步 | 读数 |
|---|---|
| 0 bundle 同步 | 126 `git fetch /tmp/ap-r1.bundle main` + checkout ⇒ `git rev-parse HEAD = 0425257033621b031a1e2c33ff0c101ad17d7b95`，**与本地期望逐字相等**；checkout 前 `git status --porcelain` 脏 0；改动前的 Deployment/ConfigMap 存 `/root/ap-release-backup-20261013/` |
| 1 build | `build.sh 04252570…` ⇒ `OK: built agent-platform:dev @ 04252570… (dirty=no)`（rev 门禁通过） |
| 2 distribute | 三节点 `crictl images` 全部 `agent-platform dev **2439eb0ab6bcd** 1.67GB`（126/125/241 一致） |
| 3 rollout | `rollout restart` ⇒ 旧 Pod `…bgqk5` **Terminating 与新 Pod `…hp9p8` Running 并存 21s**（`maxUnavailable=0` ⇒ 先起新再停旧，**无中断**），落 <internal-host> |
| 4 verify | `verify.sh 04252570…` ⇒ `OK: verify 全部通过`，其中 `image rev: 0425257033621b031a1e2c33ff0c101ad17d7b95`。⚠️ 第一次跑是 **FAIL**：`L2 /health 不可达`——原因是 port-forward 还指着旧 Pod。**这是通道缺陷不是应用缺陷**：`portforward.sh` 没有 `restart` 子命令，滚动后必须 `stop` + `start` 重指，否则取证面自己先瞎 |
| 5 观测/端到端 | `e2e_traceparent.sh` ⇒ `/query 200`、`trace_id=0000000000000000025db1cb85d09e6a`、**trace 落 Jaeger，span 数=8** |

## 3. 验收四条的结果

| # | 验收项（方案 §9 定的） | 结果 |
|---|---|---|
| 1 | 上线后问答**不再**产生 `This response_format type is unavailable` | ✅ 新 Pod 全程该告警 **0 条**；跑完 5+3+1 次问答后增量仍为 0（`回退启发式=0 json_schema 拒绝=0 限流=0`） |
| 2 | `route.reason` 变成模型写的话（不再是词表固定话术） | ✅ 例如："特装展台报馆的纸质文件份数属于公司/展会规定类知识，需查本地知识库中的报馆流程文档。" 之前只会是 `命中知识库特征词` / `无明确能力特征` |
| 3 | `make eval` 15 条 golden 不掉基线 | ✅ 本地 `15/15 = 100.00%`（`decide_route` 的 system 文案与字段描述未改，测试里专门断言了 `"rag=本地知识库" in system`） |
| 4 | 用例钉住"`FallbackChatModel` 把 `method` 透传给 primary" | ✅ `tests/llm/test_llm_fallback.py::test_with_structured_output_forwards_kwargs_to_primary`；同时把替身签名改成与真实 `ChatOpenAI` 同构（`with_structured_output(self, schema, **kwargs)`）——旧替身只实现旧签名，正是会把"参数被吞"盖成绿灯的那种形状 |

**关键词闸门的现场效果**（这是 R1 真正要解决的东西）：`特装展台报馆的纸质文件要打印几份？`（不含任何特征词）
今天 09:35 是 `route=direct` + `evidence count=0`；现在 **`route=rag` + `count=4`**。

## 4. 我在这轮里犯的、以及当场被自己数据推翻的两件事

1. **单样本过度概括**：第一轮验收里那道无特征词的因果题返回 `direct`，我当下写成"有一题没达验收"。
   复测时同一题 `0.17s` 返回、事件数 2 —— 那是**语义缓存命中**，我的"复测"根本没重新走路由。
   清掉四类回放源（`semantic_cache`/`memories`/`episodic+procedural`/LangGraph `checkpoint*`）再连打 3 次：
   **3/3 `capability=rag`、`count=4`，墙钟 18.12 / 26.75 / 14.76s。** ⇒ 结论更正为通过；
   一次读数不配当结论，这条又落回我记忆里那个同族（已第 8 次）。
2. **"search 是死路"说过头了**：换措辞的对照题确实被判成 `search`，但 SSE 是
   `evidence node=search count=1` ×2 → **`evidence node=rag count=4`** ⇒ replan 自己把链路改回来了，
   最终仍带着本地知识库依据（代价是墙钟 27.76s）。今天早些时候那次"无法回答"也真，区别就在 replan 有没有改道成功。

## 5. R1 之后**新暴露**的一条（待拍板，不属本轮改动）

路由器的能力清单**始终**写着 `search=联网搜索`，可 `/health` 报 `search: false`（未配 `SEARCH_API_KEY`）
⇒ **我们告诉模型有一条它走不通的链路**，它就会在"这像法规/公开资料问题"时选它，然后靠 replan 兜。
候选（含建议）：① 清单只广告**已启用**的能力（一行拼接条件，与 `mcp` 的处理方式一致——`mcp` 已经是这么做的）；
② 真去配 `SEARCH_API_KEY`；③ 不动，接受 replan 的那 2 跳开销。
建议 **①**：`router.py:84-86` 对 `mcp` 已经是"未启用就不进清单"，`search` 却没有同样的闸门，属同一形状的不一致。

## 6. 收束状态

| 项 | 值 |
|---|---|
| Pod | `agent-platform-7d7944fdfc-hp9p8`，1/1 Running，restart=0，node=<internal-host> |
| Pod 内 `GIT_REV` | `0425257033621b031a1e2c33ff0c101ad17d7b95`（回读，非 apply 退出码） |
| `/health` | `storage=postgres`、`sql_backend=postgres`、`embedding_backend=LocalEmbedder`、`embedding_real=true`、`otel_status=ACTIVE`、`auth_enabled=true`、**`search=false`（见 §5）** |
| 本地门禁（`make test` 十个 session 全跑，另加 agent-core） | root 1028 / shared-schemas 28 / agent-runtime 594 / agent_server app 85 / federation 176 / kefu 43 / exhibition 348 / knowledge-service 410（+7 skip）/ nl2sql 18 / tests-observability 15（真 OTel SDK）= **2745 passed**；再加 `packages/agent-core/tests` 349（改的就是这个包，Makefile 的 test 目标里没有独立 session）⇒ **3094 passed，0 失败**；eval `15/15 = 100%` |
| 语料 | `chunks=303`（业务 210 + ADR 93），dim 512 单一 |
| 回放源 | 演示前需再清一次（本轮最后几问又写入了缓存与记忆）；命令：`kubectl exec -i $POD -- python - wipe_all < /tmp/r30db.py` |
| 126 脚本 | `/tmp/r33.sh` `/tmp/r33.log`（验收编排与读数）、`/tmp/r30db.py` `/tmp/r30q.py`（复用件）、`/tmp/ap-r1.bundle`（源同步包，可删） |
| 回滚位 | `/root/ap-release-backup-20261013/`（改动前 Deployment + ConfigMap 原文）。⚠️ 代码回滚不能靠 `rollout undo`（可变 tag + `IfNotPresent`），要重走构建通道回旧 rev |
