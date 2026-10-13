"""langfuse_proof.py — 证明"模型调用层真被观测到了"（方案 §4 A3 的唯一算数判据）。

为什么需要它：`/health` 报 langfuse_enabled=true 只说明三个配置项非空，
`langfuse_ready=true` 只说明回调装配成功——**两者都不等于 trace 真的落进了 Langfuse**。
包没装、栈没起、凭据错、网络不通，页面上一片安静，观众以为平台没记录。

本脚本发一次带唯一 marker 的真实提问，然后回答唯一有意义的问题：
"那一次调用，Langfuse 里有没有，里面有没有本次的原文与用量"。

用法（在能同时访问平台与观测栈的机器上执行；凭据一律经 env 传入，**不走 argv**）：
    export API_KEY="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.API_KEY}' | base64 -d)"
    export LF_PK="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.LANGFUSE_PUBLIC_KEY}' | base64 -d)"
    export LF_SK="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.LANGFUSE_SECRET_KEY}' | base64 -d)"
    export LF_HOST="http://192.168.100.241:3000"
    /usr/bin/python3 -B langfuse_proof.py

成功判据（三条都要真）：
  P1 该次调用的 GENERATION 观测在 Langfuse 查得到（按 traceId 命中，marker 兜底）
  P2 其 input 里能看到 marker ⇒ 推给模型的原文可见
  P3 其 output 非空，且 usageDetails 的 input/output 两个数都非零
退出码：0 三条全过 / 1 P1 不成立（没接上）/ 2 P2 或 P3 不成立 / 3 缺 env
        4 **取证不成立但平台没错**：每个候选问题都命中了语义缓存 ⇒ 一次模型调用都没发生

语义缓存这个坑（2026-10-13 实踩，务必读懂再改）：
  `query_router.py:159-179` 命中 semantic_cache 就 **直接 return**，图根本不跑 ⇒ 没有模型调用
  ⇒ Langfuse 里当然什么都没有。此时若脚本按"查不到 = 没接上"报 FAIL，就是**拿探针的形状
  冒充平台的缺陷**。所以：问题必须**语义新颖**（marker 后缀不改变语义，查重按向量相似度，
  改几个字符没用），且 cache_hit 要单独成一个判定。取证问过的句子会留在 semantic_cache 里，
  重跑时若整池候选都命中缓存，那是证据链在提示"换语义"，不是"平台没接上"。

三条实测纪律（写代码的人别再猜，2026-10-13 在 241 的 v4.57.0 上量出来的）：
  · **v4 的 events_only 部署把 v1 读数 API 全撤了**：`/api/public/traces`、`/api/public/observations`、
    `/sessions`、`/metrics` 一律 404，body 明确写着 "not available ... in Langfuse v4 events_only mode"。
    读路径换成 **`GET /api/public/v2/observations`**，且 input/output 不在默认列里，
    必须显式带 `fields=io,usage`（`fields=input` / `full` / `*` 这些写法一律静默返回不含该键的行 ⇒
    "字段名猜错" 与 "真的没有内容" 在响应里长得一模一样，所以本脚本把"键在不在"打出来）。
  · agent_server **不**回写 traceparent 响应头（只有 exhibition_agent/server.py:214 写），
    所以本脚本自己造 trace id 并从请求头带进去，同时把"Langfuse trace id 是否等于 W3C trace id"
    作为**读数**打印出来，而不是当前提用。
  · 观测平台是异步批处理落库，查到前需要给它 flush 时间（下方 _ROUNDS × _SLEEP）。
  · 存进去的中文是**多层 JSON 编码后的 `\\uXXXX` 字面量**，`ensure_ascii=False` 只能解自己
    那一层 ⇒ 中文 needle 恒 miss（marker 是 ASCII 所以照常命中，最容易骗人）。用 `_flatten()`。
  · 本次实测一次 rag 问答落**两条 GENERATION**：路由决策（input 无 `[来源:` 属正常）与
    答案生成（input 必含检索原文）。条数随链路而异（blocked 只有路由那次），判定看内容别看条数。
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

TARGET = os.environ.get("TARGET", "http://127.0.0.1:18000")
LF_HOST = os.environ.get("LF_HOST", "")
LF_PK = os.environ.get("LF_PK", "")
LF_SK = os.environ.get("LF_SK", "")
API_KEY = os.environ.get("API_KEY", "")
_ROUNDS = 12  # 异步 flush：最多等 12×3s
_SLEEP = 3
# 候选取证问题：语义互相远离、且都能在已入库的会展语料里落到证据（见
# docs/operations/demo-questions.md）。逐个试，第一个没命中语义缓存的就用来取证。
POOL = [
    "按国家会议中心搭建手册，特装展台的搭建许可证怎么领取，谁签发？",
    "进博会搭建商手册里，撤展期间对垃圾清运和场地验收有什么要求？",
    "GB/T 33490 对展览工程现场用电安全箱体的设置提出了哪些要求？",
    "线上展览会服务指南里，对平台的数据备份与恢复能力有什么建议？",
    "国家会议中心手册中关于消防通道和灭火器配置的规定是什么？",
]
FORCE_Q = os.environ.get("PROBE_Q", "")


def make_question(base: str) -> tuple[str, str]:
    marker = f"LFPROOF-{uuid.uuid4().hex[:10]}"
    return f"{base}（取证标记 {marker}）", marker


def _get(url: str, headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        # 连不上/超时/DNS 都走这里：Langfuse 没起就是这个信号，不是"平台没记录"
        return 0, f"URLError:{e.reason}"


def _lf(path: str):
    auth = base64.b64encode(f"{LF_PK}:{LF_SK}".encode()).decode()
    return _get(f"{LF_HOST}{path}", headers={"Authorization": f"Basic {auth}"})


def ask(question: str) -> tuple[str, str, list[str], int]:
    """发一次 /query（自造 traceparent 进去），回 (w3c trace_id, 回答, 事件序列, evidence 条数)。"""
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    body = json.dumps({"query": question, "session_id": f"lfproof-{int(time.time())}"}).encode()
    req = urllib.request.Request(
        f"{TARGET}/query",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
            "traceparent": f"00-{trace_id}-{span_id}-01",
        },
    )
    answer, kinds, ev_count = "", [], 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp_tp = resp.headers.get("traceparent", "")  # 实测：期望为空
        print(f"  响应头 traceparent = {resp_tp or '(无)'}")
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:])
            except json.JSONDecodeError:
                continue
            # 事件帧是**平铺**的：_sse() 把 payload.type 提成事件名、其余字段直接落在顶层。
            # 读 d["payload"] 恒得 {} ⇒ evidence_count=0 / answer=''（曾据此误判"没接上"）。
            t = d.get("type") or "?"
            kinds.append(t)
            if t == "evidence":
                ev_count = int(d.get("count") or 0)
            elif t in ("answer", "cache_hit"):
                answer = str(d.get("text") or "")
    return trace_id, answer, kinds, ev_count


def _flatten(v, depth=4) -> str:
    """把观测载荷摊平成**真正可读的中文文本**。

    实测坑（2026-10-13）：input/output 落库时是**多层 JSON 编码**的字符串，内层的中文以
    `\\uXXXX` 字面量存在。所以 `ensure_ascii=False` 那一招在这里**不够**——它只影响
    我们自己 dumps 的那一层，解不开别人已经写死的转义。后果很阴：
    ASCII marker 照常命中，中文 needle（如 `[来源:`）恒 miss ⇒ 会把"证据没进 prompt"
    这个假结论读出来。摊平到解不动为止才是原文。
    """
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    for _ in range(depth):
        try:
            n = json.loads(s)
        except json.JSONDecodeError:
            return s
        if isinstance(n, str):
            if n == s:
                return s
            s = n
        else:
            return json.dumps(n, ensure_ascii=False)
    return s


def _rows(params: str) -> list[dict]:
    code, text = _lf(f"/api/public/v2/observations?limit=50&{params}")
    if code != 200:
        print(f"  v2/observations HTTP={code} body[:120]={text[:120]!r}")
        return []
    try:
        return json.loads(text).get("data") or []
    except json.JSONDecodeError:
        print("  v2/observations 返回非 JSON")
        return []


def find_observations(w3c_trace_id: str, since: str, marker: str) -> tuple[list[dict], str]:
    """先按 traceId 取；取不到再在时间窗里按 marker 定位。返回 (GENERATION 行, 命中方式)。"""
    fields = "fields=io,usage,modelParameters,metadata"
    for i in range(_ROUNDS):
        rows = _rows(f"fromStartTime={since}&traceId={w3c_trace_id}&{fields}")
        gens = [r for r in rows if (r.get("type") or "").upper() == "GENERATION"]
        if gens:
            return gens, "by-traceId"
        time.sleep(_SLEEP)
        if i == _ROUNDS // 2:
            # 中途换通道：不等 traceId，直接在窗口里找 marker（顺带回答"id 等不等于"）
            win = _rows(f"fromStartTime={since}&{fields}")
            for r in win:
                if marker in _flatten(r.get("input")) and (r.get("type") or "").upper() == "GENERATION":
                    return [x for x in win if x.get("traceId") == r.get("traceId")
                            and (x.get("type") or "").upper() == "GENERATION"], "by-marker"
    return [], "not-found"


def main() -> int:
    fixed_id, fixed_marker = os.environ.get("PROBE_TRACE_ID", ""), os.environ.get("PROBE_MARKER", "")
    # 只读复核不发消息 ⇒ 不需要平台 key（少一个凭据就等于少一次泄漏面）
    need_platform_key = not (fixed_id and fixed_marker)
    if not all([LF_PK, LF_SK, LF_HOST]) or (need_platform_key and not API_KEY):
        print("FAIL: 需要 env LF_PK / LF_SK / LF_HOST"
              + ("（发消息取证还要 API_KEY）" if need_platform_key else "（只读复核不需要 API_KEY）")
              + "，值一律不进 argv")
        return 3
    tried = []
    picked = None
    since = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 只读复核模式：上一次已经真跑过一次模型调用（trace_id 已知），只需把 P1/P2/P3 判完。
    # 为什么需要它——重复发同一个问题必然命中语义缓存，缓存里那次不算模型调用；
    # 而观测数据是已落库的，重发提问既拿不到新证据又白污染缓存。
    if fixed_id and fixed_marker:
        print(f"只读复核：不重发提问，直接按 trace_id={fixed_id} 判定（marker={fixed_marker}）")
        picked = (fixed_id, fixed_marker, since)
    for base in ([] if picked else ([FORCE_Q] if FORCE_Q else POOL)):
        question, marker = make_question(base)
        print(f"\nQ: {question}")
        trace_id, answer, kinds, ev_count = ask(question)
        print(f"  w3c trace_id={trace_id}  events={kinds}  evidence_count={ev_count}")
        print(f"  answer[:70]={answer[:70]!r}")
        if "cache_hit" in kinds:
            print("  ⇒ 命中语义缓存：图没跑、模型没调用 ⇒ 本次不产生任何 LLM 观测，"
                  "**不能**据此判观测面失败（换下一个候选问题）")
            tried.append(marker)
            continue
        picked = (trace_id, marker, since)
        break
    if picked is None:
        print(f"\n取证不成立：{len(tried)} 个候选问题全部命中语义缓存 ⇒ 全程没有模型调用。")
        print("     要么先清 semantic_cache 里对应行，要么用没问过的语义（PROBE_Q=...）。")
        return 4

    trace_id, marker, since = picked
    gens, how = find_observations(trace_id, since, marker)
    if not gens:
        print("P1 FAIL: Langfuse 查不到这次调用 ⇒ 观测面**没接上**（别拿 /health 的灯当接上）")
        print("     先分清三件事：栈没起 / 凭据不对 / 回调没发——上面的 HTTP 码能区分前两件")
        return 1
    ids = {g.get("traceId") for g in gens}
    # 投影互斥：`fields=io,usage` 会把 name/modelId 挤成 null，默认投影里有 name（"ChatOpenAI"）
    # 但没有 input/output ⇒ 要"原文 + 用量 + 名字"三样齐必须两次取、按 id 合并。
    # 注意 modelId 在**两种投影里都是 null**（模型名在库内的 model 列，UI 能看到），
    # 别把它读成"没记录模型"，也别据此声称"哪个模型"是 API 可读的列。
    names = {r.get("id"): r.get("name") for r in _rows(f"fromStartTime={since}&traceId={trace_id}")}
    for g in gens:
        g["name"] = g.get("name") or names.get(g.get("id"))
    print(f"P1 OK（{how}）: GENERATION 行数={len(gens)}  trace id={sorted(ids)}"
          f"  ==W3C id? {ids == {trace_id}}")
    for g in gens[:8]:
        u = g.get("usageDetails") or {}
        io_keys = [k for k in ("input", "output", "metadata", "usageDetails") if k in g]
        inp = _flatten(g.get("input"))
        print(f"     - {g.get('type')} | {g.get('name')} | model={g.get('modelId')}"
              f" | in={u.get('input')} out={u.get('output')} total={u.get('total')}"
              f" | latency={g.get('latency')} | 键={io_keys}"
              f" | marker={'HIT' if marker in inp else 'miss'}"
              f" | 含检索证据={'HIT' if '[来源:' in inp else 'miss'} | 摊平后字符数={len(inp)}")
    p2 = any(marker in _flatten(g.get("input")) for g in gens)
    p3 = any(g.get("output") for g in gens)
    usage_ok = any((g.get("usageDetails") or {}).get("input") and
                   (g.get("usageDetails") or {}).get("output") for g in gens)
    print(f"P2 {'OK' if p2 else 'FAIL'}: GENERATION 的 input 里含 marker（推给模型的原文可见）")
    print(f"P3 {'OK' if (p3 and usage_ok) else 'FAIL'}: output 非空={p3}，usageDetails 双值齐={usage_ok}")
    if not (p2 and p3 and usage_ok):
        print("     注：P2 为 FAIL 而键里有 input ⇒ fields 协商对了但原文没带 marker，是真的没记录")
        print("     注：键里没有 input/output ⇒ 是 fields 名不对（见模块 docstring），不是平台缺陷")
        return 2
    print("A3 PASS: 这次调用的原文与用量确实躺在 Langfuse 里（v4 v2/observations API 读到）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
