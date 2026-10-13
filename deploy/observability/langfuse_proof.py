"""langfuse_proof.py — 证明"模型调用层真被观测到了"（方案 §4 A3 的唯一算数判据）。

为什么需要它：`/health` 报 langfuse_enabled=true 只说明三个配置项非空，
`langfuse_ready=true` 只说明回调装配成功——**两者都不等于 trace 真的落进了 Langfuse**。
包没装、栈没起、凭据错、网络不通，页面上一片安静，观众以为平台没记录。

本脚本发一次带唯一 marker 的真实提问，然后回答唯一有意义的问题：
"那一次调用，Langfuse 里有没有，里面有没有本次的原文与用量"。

用法（在 126 上执行；凭据一律经 env 传入，**不走 argv**）：
    export API_KEY="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.API_KEY}' | base64 -d)"
    export LF_PK="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.LANGFUSE_PUBLIC_KEY}' | base64 -d)"
    export LF_SK="$(kubectl -n agent-platform get secret observability-keys \
        -o jsonpath='{.data.LANGFUSE_SECRET_KEY}' | base64 -d)"
    export LF_HOST="http://192.168.100.126:3000"
    /usr/bin/python3 -B langfuse_proof.py

成功判据（三条都要真）：
  P1 该次调用的 trace 在 Langfuse 查得到（按 id 或按 marker 命中，两者都试）
  P2 其 GENERATION observation 的 input 里能看到 marker
  P3 其 output 非空，且 usage 的 input/output 两个数都非零
退出码：0 三条全过 / 1 P1 不成立（没接上）/ 2 P2 或 P3 不成立 / 3 缺 env

两条实测纪律（写代码的人别再猜）：
  · agent_server **不**回写 traceparent 响应头（只有 exhibition_agent/server.py:214 写），
    所以本脚本自己造 trace id 并从请求头带进去，同时把"Langfuse trace id 是否等于
    W3C trace id"作为**读数**打印出来，而不是当前提用。
  · 观测平台是异步批处理落库，查到前需要给它 flush 时间（下方 retries）。
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

TARGET = os.environ.get("TARGET", "http://127.0.0.1:18000")
LF_HOST = os.environ.get("LF_HOST", "")
LF_PK = os.environ.get("LF_PK", "")
LF_SK = os.environ.get("LF_SK", "")
API_KEY = os.environ.get("API_KEY", "")
MARKER = f"LFPROOF-{uuid.uuid4().hex[:10]}"
QUESTION = f"根据知识库，特装展台报馆的纸质文件要打印几份？（取证标记 {MARKER}）"


def _get(url: str, headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, f"{type(e).__name__}"


def _lf(path: str):
    auth = base64.b64encode(f"{LF_PK}:{LF_SK}".encode()).decode()
    return _get(f"{LF_HOST}{path}", headers={"Authorization": f"Basic {auth}"})


def ask() -> tuple[str, str, list[str], int]:
    """发一次 /query（自造 traceparent 进去），回 (w3c trace_id, 回答, 事件序列, evidence 条数)。"""
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    body = json.dumps({"query": QUESTION, "session_id": f"lfproof-{int(time.time())}"}).encode()
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
        cur = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("event:"):
                cur = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    d = json.loads(line[5:])
                except Exception:
                    continue
                t = d.get("type") or cur or "?"
                kinds.append(t)
                p = d.get("payload") or {}
                if t == "evidence":
                    ev_count = int(p.get("count") or 0)
                elif t == "answer":
                    answer = str(p.get("text") or "")
    return trace_id, answer, kinds, ev_count


def find_trace(w3c_trace_id: str) -> tuple[dict | None, str]:
    """先按 id 查；查不到再在近期 trace 里按 marker 定位。返回 (trace, 命中方式)。"""
    for _ in range(12):
        code, text = _lf(f"/api/public/traces/{w3c_trace_id}")
        if code == 200:
            return json.loads(text), "by-id"
        time.sleep(3)
    # 按 marker 兜底：同时把 id 映射关系读出来
    code, text = _lf("/api/public/traces?limit=25&orderBy=timestamp&orderDir=desc")
    if code != 200:
        print(f"  列表查询 HTTP={code}（Basic 认证被拒？项目键不对？）")
        return None, "list-failed"
    data = (json.loads(text) or {}).get("data") or []
    for tr in data:
        blob = json.dumps(tr, ensure_ascii=False)
        if MARKER in blob:
            tid = tr.get("id") or ""
            full_code, full_text = _lf(f"/api/public/traces/{tid}")
            return (json.loads(full_text) if full_code == 200 else tr), "by-marker"
    print(f"  近期 {len(data)} 条 trace 里没有 {MARKER}")
    return None, "not-found"


def main() -> int:
    if not all([API_KEY, LF_PK, LF_SK, LF_HOST]):
        print("FAIL: 需要 env API_KEY / LF_PK / LF_SK / LF_HOST（值不进 argv）")
        return 3
    print(f"Q: {QUESTION}")
    trace_id, answer, kinds, ev_count = ask()
    print(f"  w3c trace_id={trace_id}  events={kinds}  evidence_count={ev_count}")
    print(f"  answer[:70]={answer[:70]!r}")

    tr, how = find_trace(trace_id)
    if tr is None:
        print("P1 FAIL: Langfuse 查不到这次调用 ⇒ 观测面**没接上**（别拿 /health 的灯当接上）")
        return 1
    obs = tr.get("observations") or []
    print(f"P1 OK（{how}）: trace id={tr.get('id')}  ==W3C id? {tr.get('id') == trace_id}"
          f"  observations={len(obs)}")
    for o in obs[:8]:
        u = o.get("usage") or {}
        print(f"     - {o.get('type')} | {o.get('name')} | in={u.get('input')} out={u.get('output')}"
              f" | latency={o.get('latency')}")
    gens = [o for o in obs if (o.get("type") or "").upper() == "GENERATION"]
    p2 = MARKER in json.dumps([g.get("input") for g in gens], ensure_ascii=False)
    p3 = any(g.get("output") for g in gens)
    usage_ok = any((g.get("usage") or {}).get("input") and (g.get("usage") or {}).get("output") for g in gens)
    print(f"P2 {'OK' if p2 else 'FAIL'}: GENERATION 的 input 里含 marker（推给模型的原文可见）")
    print(f"P3 {'OK' if (p3 and usage_ok) else 'FAIL'}: output 非空={p3}，usage 双值齐={usage_ok}")
    if not (p2 and p3 and usage_ok):
        print("     注：observations=0 而 trace 存在 ⇒ 只落了请求级 span，LLM 调用层没被观测")
        return 2
    print("A3 PASS: 这次调用的原文与用量确实躺在 Langfuse 里")
    return 0


if __name__ == "__main__":
    sys.exit(main())
