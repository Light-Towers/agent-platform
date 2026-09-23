"""skill 回归测试 · 层 1（端点契约，无需 LLM key）。

读取同目录 golden_cases.json 的 api_contract，逐条直连后端断言：
  - HTTP 状态码 == expect_status
  - 响应文本包含 must_contain 全部子串
沙箱 DNS 不可用：monkeypatch getaddrinfo 让数值 IP 走 inet_aton 绕过（真实环境无影响）。
后端地址由环境变量 EXHIBITION_API_BASE_URL 注入（默认 http://localhost:8000），严禁写死 IP。
退出码：全部通过 0，有失败 1（可作 CI / 部署后门禁）。

用法：
  set EXHIBITION_API_BASE_URL=http://<host>:8000
  python run_golden_api.py
"""
import json
import os
import socket
import sys
import urllib.error
import urllib.request

_real = socket.getaddrinfo


def patched(host, port, *a, **k):
    try:
        socket.inet_aton(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (host, int(port)))]
    except OSError:
        return _real(host, port, *a, **k)


socket.getaddrinfo = patched

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("EXHIBITION_API_BASE_URL", "http://localhost:8000").rstrip("/")


def call(method, path):
    url = BASE + path
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - 网络/连接错误
        return "ERR", repr(e)


def main():
    spec = json.load(open(os.path.join(HERE, "golden_cases.json"), encoding="utf-8"))
    cases = spec.get("api_contract", [])
    fails = 0
    total = 0
    print("层 1 端点契约回归 · base=%s · 用例数=%d\n" % (BASE, len(cases)))
    for c in cases:
        total += 1
        st, txt = call(c["method"], c["path"])
        ok = (st == c.get("expect_status", 200))
        missed = [m for m in c.get("must_contain", []) if m not in txt]
        if missed:
            ok = False
        if not ok:
            fails += 1
        print("[%s] %-20s %-4s %s -> %s%s" % (
            "PASS" if ok else "FAIL", c["skill"], c["method"], c["path"], st,
            "" if ok else "  missed=%s" % missed))
        if not ok:
            print("       snippet=%s" % txt[:140].replace("\n", " "))
    print("\n[summary] %d/%d passed, %d failed" % (total - fails, total, fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
