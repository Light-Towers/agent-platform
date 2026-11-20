"""通用 skill 实时端点校验 harness（manifest 驱动，单份复用）。

用法：
  # 直接运行
  python tests/skill_live_check/harness.py skills/company-venue-ops/live.manifest.json
  # 或 pytest（每个 skill 一个薄壳 test_*.py）
  python -m pytest tests/skill_live_check/

manifest 里只放"声明"（端点、期望），执行逻辑全在本文件，故各 skill 不重复代码。
凭据：优先环境变量 <jwt_env>，否则从 manifest 所在目录向上查找 <jwt_search> 中的文件。
传输层默认 GET；仅 manifest 显式声明的 `post_data`/`post_struct` 会发 **POST 只读查询**
（对应前端 page/list 类，params 走 query string，与 axios `params` 一致），不触达任何写端点；
任意写调用触发 SystemExit（E.写护栏 断言其未被调用）。
"""
import hashlib
import json
import os
import re
import sys

import requests

# ---- 本地内网配置（不入库，运行时加载）----
# 仓库根 .env 已被 .gitignore 忽略：放真实内网地址与令牌，绝不入库。
# replay 气隙模式不依赖这些值（键归一化后一致）；live/record 才用真实地址发请求。
def _load_local_env():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_file = os.path.join(root, ".env")
    if not os.path.exists(env_file):
        return
    for line in open(env_file, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def resolve_base(manifest_base):
    """live/record 用本地 .env 的 SKILL_BASE_URL 覆盖 manifest 占位符；未配置则回落。"""
    real = os.environ.get("SKILL_BASE_URL", "").strip()
    return real or manifest_base


_load_local_env()

WRITE_CALLED = {"n": 0}


def write(method, path, **kw):
    WRITE_CALLED["n"] += 1
    raise SystemExit(f"[护栏触发] harness 禁止写操作: {method} {path}")


def _resolve_up(manifest_path, rel):
    d = os.path.dirname(os.path.abspath(manifest_path))
    while True:
        cand = os.path.join(d, rel)
        if os.path.exists(cand):
            return open(cand, encoding="utf-8").read().strip()
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_tokens(manifest_path):
    """加载多套令牌：default（<jwt_env> 或 <jwt_search> 首个存在文件）+ manifest.jwt_files 里按 key 声明的其余令牌。
    断言可用 "jwt": "<key>" 指定用哪套（缺省 default）。"""
    cfg = json.load(open(manifest_path, encoding="utf-8"))
    tokens = {}
    env = cfg.get("jwt_env")
    tok = os.environ.get(env, "").strip() if env else ""
    if not tok:
        for rel in cfg.get("jwt_search", []):
            tok = _resolve_up(manifest_path, rel)
            if tok:
                break
    tokens["default"] = tok
    for key, rel in (cfg.get("jwt_files") or {}).items():
        tokens[key] = _resolve_up(manifest_path, rel)
    return tokens


def pick_token(tokens, a):
    key = a.get("jwt", "default")
    tok = tokens.get(key)
    if not tok:
        if MODE == "replay":
            # 气隙回放不发真实请求，无需真令牌（cassette 不含 header 校验）。
            return "<replay-no-auth>"
        raise SystemExit(f"未找到令牌 '{key}'：请在 manifest 的 jwt_files/jwt_search 配置，或设置环境变量 {key}")
    return tok


def find_jwt(manifest_path):
    tok = load_tokens(manifest_path).get("default")
    if not tok:
        raise SystemExit("未找到默认 JWT：请设置环境变量 MINGYANG_JWT，或按 jwt_search 放置令牌文件")
    return tok


def headers(jwt, base):
    return {
        "Referer": base + "/",
        "Authorization": "Bearer " + jwt,
        "jwt-token": jwt,
        "Origin": base,
        "Cookie": "SET_TOKEN_HOME=" + jwt,
    }


# ---- L3 hermetic 传输层（cassette 录制/回放）----
# 模式：live(默认,真实请求) / record(真实请求并落盘) / replay(仅读 cassette, 缺则报错=断网)
# 可用环境变量 SKILL_HTTP_MODE 设定（便于 pytest / CI 气隙运行），CLI flag 优先。
MODE = os.environ.get("SKILL_HTTP_MODE", "live").lower()
CASSETTE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cassettes")
HTTP_SERVED = {"replay": 0, "record": 0}


def _cassette_key(method, url, params):
    # URL 的 host 段归一化：真实内网 IP 与 <internal-ip> 占位符算出同一键，
    # 使 live/record（真实 IP）与 replay（占位符）共用同一批 cassette。
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    normalized = f"{parts.scheme}://<internal-ip>{parts.path}"
    raw = f"{method} {normalized} {json.dumps(params, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _http(method, base, path, params=None, jwt=None, timeout=25):
    url = base + path
    if MODE == "replay":
        p = os.path.join(CASSETTE_DIR, _cassette_key(method, url, params) + ".json")
        if not os.path.exists(p):
            raise RuntimeError(f"[hermetic] 缺失 cassette，禁止实时调用: {method} {path}")
        c = json.load(open(p, encoding="utf-8"))
        HTTP_SERVED["replay"] += 1
        return c["status"], c["json"]
    r = requests.request(method, url, headers=headers(jwt, base), params=params, timeout=timeout)
    status = r.status_code
    try:
        j = r.json()
    except Exception:
        j = {}
    if MODE == "record":
        os.makedirs(CASSETTE_DIR, exist_ok=True)
        json.dump(
            {"request": {"method": method, "path": path, "params": params}, "status": status, "json": j},
            open(os.path.join(CASSETTE_DIR, _cassette_key(method, url, params) + ".json"), "w", encoding="utf-8"),
            ensure_ascii=False, indent=2,
        )
        HTTP_SERVED["record"] += 1
    return status, j


def call_get(base, jwt, path, params=None, timeout=25):
    status, j = _http("GET", base, path, params, jwt, timeout)
    return {"http": status, "code": j.get("code"), "data": j.get("data")}


def call_post(base, jwt, path, params=None, timeout=25):
    """POST 只读查询（page/list 类），params 走 query string（同前端 axios params）。"""
    status, j = _http("POST", base, path, params, jwt, timeout)
    return {"http": status, "code": j.get("code"), "data": j.get("data")}


def nonempty(d):
    if isinstance(d, list):
        return len(d) > 0
    if isinstance(d, dict):
        return any(bool(v) for v in d.values())
    return d is not None


def datacount(d):
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        return sum(1 for v in d.values() if bool(v))
    return 0


# ---- L2 黄金主（结构指纹 + 归一化）----
# 归一化目标：免疫"数据漂"（行数/具体值/列表顺序变化），仅捕获"schema 漂移"
# （字段改名、类型变化、嵌套结构变化）。基于 Golden Master / 表征测试最佳实践：
# 易变字段先归一化再比，绝不静默更新基线。
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ID_RE = re.compile(r"^\d{11,}$")  # 长数字 id（展会/展位/订单等）


def normalize(v):
    """把响应归一成"结构指纹"。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return "<bool>"
    if isinstance(v, int):
        return "<int>"
    if isinstance(v, float):
        return "<num>"
    if isinstance(v, str):
        if TS_RE.match(v):
            return "<TS>"
        if UUID_RE.match(v):
            return "<UUID>"
        if ID_RE.match(v):
            return "<ID>"
        return "<str>"
    if isinstance(v, list):
        return [normalize(v[0])] if v else []  # 列表只留首元素结构，丢弃顺序/长度
    if isinstance(v, dict):
        return {k: normalize(val) for k, val in sorted(v.items())}
    return "<?>"


def call_raw(base, jwt, path, params=None, timeout=25):
    return _http("GET", base, path, params, jwt, timeout)


def _safe(s):
    return re.sub(r"[^\w.-]+", "_", s)


def _golden_path(golden_dir, group, label):
    return os.path.join(golden_dir, f"{_safe(group)}__{_safe(label)}.golden.json")


def _diff_paths(a, b, prefix=""):
    """返回前若干处结构差异路径，便于定位 schema 漂移。"""
    out = []
    if type(a) != type(b):
        out.append(f"{prefix}: 类型 {type(a).__name__}->{type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{prefix}.{k}: 新增")
            elif k not in b:
                out.append(f"{prefix}.{k}: 缺失")
            else:
                out += _diff_paths(a[k], b[k], f"{prefix}.{k}")
    elif isinstance(a, list):
        if a != b:
            out.append(f"{prefix}[]: {a} != {b}")
    else:
        if a != b:
            out.append(f"{prefix}: {a} != {b}")
    return out[:6]


def resolve_ctx_params(manifest, base, jwt, a):
    """为上下文端点选稳定 exhibitionId：优先 manifest.golden_exhibition_id，
    否则在展会列表中找该端点有数据的首个，仍无则取首个。结果写入 golden meta 复用。"""
    pinned = manifest.get("golden_exhibition_id")
    if pinned:
        return {"exhibitionId": pinned, "page": 1, "pageSize": 10}
    exh = call_get(base, jwt, manifest["exhibition_list_path"])["data"] or []
    for e in exh:
        res = call_get(base, jwt, a["path"], params={"exhibitionId": e["id"], "page": 1, "pageSize": 10})
        if res["http"] == 200 and res["code"] == 200 and nonempty(res["data"]):
            return {"exhibitionId": e["id"], "page": 1, "pageSize": 10}
    if exh:
        return {"exhibitionId": exh[0]["id"], "page": 1, "pageSize": 10}
    return {"exhibitionId": None, "page": 1, "pageSize": 10}


def run_golden(manifest_path, golden_dir, regen=False):
    """L2 黄金主：对 GET 类端点录制/比对结构指纹。返回 (results, failed)。
    golden 未初始化（目录不存在或无文件）时跳过，不报错。"""
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    base = resolve_base(manifest["base_url"])
    tokens = load_tokens(manifest_path)
    results = []
    if regen:
        os.makedirs(golden_dir, exist_ok=True)
    elif not os.path.isdir(golden_dir) or not any(f.endswith(".golden.json") for f in os.listdir(golden_dir)):
        print(f"[SKIP] L2 黄金主: 目录 {golden_dir} 未初始化，跳过（先 --regen 生成）")
        return results, []
    eligible = [a for a in manifest["assertions"]
                if a["type"] in ("get_data", "get_struct", "get_ctx", "post_data", "post_struct")]
    for a in eligible:
        g, lbl = a["group"], a["label"]
        jwt = pick_token(tokens, a)
        gp = _golden_path(golden_dir, g, lbl)
        if regen or not os.path.exists(gp):
            if a["type"] == "get_ctx":
                params = resolve_ctx_params(manifest, base, jwt, a)
            else:
                params = a.get("params")
        else:
            params = json.load(open(gp, encoding="utf-8"))["_meta"]["params"]  # 复用录制时输入，保证稳定
        method = "POST" if a["type"].startswith("post_") else "GET"
        _, body = _http(method, base, a["path"], params=params, jwt=jwt)
        fp = normalize(body)
        if regen or not os.path.exists(gp):
            json.dump({"_meta": {"path": a["path"], "params": params}, "fingerprint": fp},
                      open(gp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            results.append((g, lbl, True, "regen 已写"))
            print(f"[PASS] {g:>10} | {lbl}  (regen 已写 {os.path.basename(gp)})")
            continue
        prev = json.load(open(gp, encoding="utf-8"))["fingerprint"]
        if fp == prev:
            results.append((g, lbl, True, "指纹一致"))
            print(f"[PASS] {g:>10} | {lbl}  (指纹一致)")
        else:
            diffs = _diff_paths(prev, fp)
            results.append((g, lbl, False, "指纹变更: " + " | ".join(diffs)))
            print(f"[FAIL] {g:>10} | {lbl}  (指纹变更: " + " | ".join(diffs) + ")")
    failed = [r for r in results if not r[2]]
    return results, failed


def run_manifest(manifest_path):
    """返回 (results, failed)。results 为 (group,label,ok,info) 列表；不调用 sys.exit。"""
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    base = resolve_base(manifest["base_url"])
    tokens = load_tokens(manifest_path)
    exh_path = manifest.get("exhibition_list_path")
    results = []

    def rec(group, label, ok, info=""):
        results.append((group, label, ok, info))
        print(f"[{'PASS' if ok else 'FAIL'}] {group:>10} | {label}" + (f"  ({info})" if info else ""))

    for a in manifest["assertions"]:
        t = a["type"]
        g = a["group"]
        lbl = a["label"]
        jwt = pick_token(tokens, a)
        if t == "auth":
            ok = len(jwt) > 50
            rec(g, lbl, ok, f"len={len(jwt)}")
        elif t == "const":
            ok = bool(a.get("value"))
            rec(g, lbl, ok)
        elif t == "get_data":
            res = call_get(base, jwt, a["path"], params=a.get("params"))
            ok = res["http"] == 200 and res["code"] == 200 and nonempty(res["data"])
            rec(g, lbl, ok, f"http={res['http']} code={res['code']} rows={datacount(res['data'])}")
        elif t == "get_struct":
            res = call_get(base, jwt, a["path"], params=a.get("params"))
            ok = res["http"] == 200 and res["code"] == 200 and isinstance(res["data"], (list, dict))
            rec(g, lbl, ok, f"http={res['http']} code={res['code']} rows={datacount(res['data'])} (默认展会数据，可能为空)")
        elif t == "get_http":
            res = call_get(base, jwt, a["path"], params=a.get("params"))
            ok = res["http"] == a["expect_http"]
            rec(g, lbl, ok, f"http={res['http']} (期望 {a['expect_http']})")
        elif t == "get_ctx":
            exh = call_get(base, jwt, exh_path)["data"] or [] if exh_path else []
            reachable = False
            data_exh = 0
            for e in exh:
                res = call_get(base, jwt, a["path"], params={"exhibitionId": e["id"], "page": 1, "pageSize": 10})
                if res["http"] == 200 and res["code"] == 200 and isinstance(res["data"], (list, dict)):
                    reachable = True
                    if nonempty(res["data"]):
                        data_exh += 1
                if reachable and data_exh >= 1:
                    break
            ok = reachable
            rec(g, lbl, ok, f"有数据展会 {data_exh}/{len(exh)}（能力可达={reachable}）")
        elif t in ("post_data", "post_struct"):
            res = call_post(base, jwt, a["path"], params=a.get("params"))
            if t == "post_data":
                ok = res["http"] == 200 and res["code"] == 200 and nonempty(res["data"])
            else:
                ok = res["http"] == 200 and res["code"] == 200 and isinstance(res["data"], (list, dict))
            rec(g, lbl, ok, f"POST http={res['http']} code={res['code']} rows={datacount(res['data'])}")
        elif t == "write_guard":
            ok = WRITE_CALLED["n"] == 0
            rec(g, lbl, ok, f"write_calls={WRITE_CALLED['n']}")
        else:
            rec(g, lbl, False, f"未知断言类型: {t}")

    failed = [r for r in results if not r[2]]
    return results, failed


def main():
    if len(sys.argv) < 2:
        print("用法: python harness.py <skill>/live.manifest.json [--regen] [--golden-dir DIR]")
        sys.exit(2)
    manifest_path = sys.argv[1]
    global MODE, CASSETTE_DIR
    regen = "--regen" in sys.argv
    record = "--record" in sys.argv
    replay = "--replay" in sys.argv
    if record and replay:
        print("错误: --record 与 --replay 互斥")
        sys.exit(2)
    if "--golden-dir" in sys.argv:
        golden_dir = os.path.abspath(sys.argv[sys.argv.index("--golden-dir") + 1])
    else:
        # 默认：仓库 tests/skill_live_check/golden（manifest 位于 skills/<name>/live.manifest.json）
        golden_dir = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(manifest_path)), "..", "..", "tests", "skill_live_check", "golden"))
    if "--cassette-dir" in sys.argv:
        CASSETTE_DIR = os.path.abspath(sys.argv[sys.argv.index("--cassette-dir") + 1])
    # 否则保留模块级默认（harness 同级的 cassettes/），兼容 pytest+SKILL_HTTP_MODE
    if record:
        MODE = "record"
    elif replay:
        MODE = "replay"
    # 否则保留模块级 MODE（来自 SKILL_HTTP_MODE 环境变量或默认 live）

    r_l1, f_l1 = run_manifest(manifest_path)
    r_l2, f_l2 = run_golden(manifest_path, golden_dir, regen=regen)

    print("\n" + "=" * 72)
    print(f"传输模式: {MODE}" + ("  (cassette 目录: " + CASSETTE_DIR + ")" if MODE != "live" else ""))
    print(f"L1 结构断言: 总 {len(r_l1)} 项, 失败 {len(f_l1)} 项")
    print(f"L2 黄金主  : 总 {len(r_l2)} 项, 失败 {len(f_l2)} 项" + ("  (已 regen)" if regen else ""))
    if MODE == "replay":
        print(f"L3 hermetic: 本次 {HTTP_SERVED['replay']} 次调用全部来自 cassette，0 次实时网络（误发写请求在物理上不可能）")
    elif MODE == "record":
        print(f"L3 hermetic: 录制 {HTTP_SERVED['record']} 个 cassette 至 {CASSETTE_DIR}")
    for r in f_l1 + f_l2:
        print(f"   FAIL -> {r[0]} | {r[1]} ({r[3]})")
    if f_l1 or f_l2:
        print("RESULT: FAIL  (退出码 1)")
        sys.exit(1)
    print("RESULT: PASS  (退出码 0)")
    sys.exit(0)


if __name__ == "__main__":
    main()
