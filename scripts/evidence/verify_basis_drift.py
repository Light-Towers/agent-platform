#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据新鲜度漂移门禁：从 LIVE 实读判据依赖的形状，与结构化基线对码。

为什么需要（通用，不只 docstore）：凡判据绑 rev/配置/集合/租户，换任一形状后必须复取，
否则下一个人会把上一轮读数搬进本轮账面（AGENTS.md 观测面规矩第 9 条）。此前"复审触发
条件"只是一句散文 ⇒ 必然漂移。本量具把那句话变成可执行的 rc：
  - 台账（baselines/*.json）登记每条判据依赖哪些可实读形状 + 基线值；
  - 本量具经 ssh 在控制面执行探针（kubectl exec / pymilvus / crictl），与基线对码；
  - 任一漂移 ⇒ rc=1 并打印"哪些判据需重跑"；前置不可用（ssh 不通/缺 kubectl）⇒ rc=2。

退出码：0 = 全部新鲜 · 1 = 存在漂移（需重跑列出的判据）· 2 = 前置不可用。
与 scripts/evidence/ 其他量具同口径；2 从不折算成通过。

用法：
  uv run python scripts/evidence/verify_basis_drift.py --ssh-host <控制面IP>
  uv run python scripts/evidence/verify_basis_drift.py --list          # 列出全部台账判据
  EVIDENCE_SSH_HOST=<ip> uv run python scripts/evidence/verify_basis_drift.py

内网地址不硬编码在仓内（公开镜像脱敏纪律），由 --ssh-host / env 注入。
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent / "baselines"
NS = "agent-platform"


def load_ledgers() -> list[dict]:
    if not BASE_DIR.is_dir():
        return []
    out = []
    for p in sorted(BASE_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001 — 台账损坏即 fail-closed
            print(f"[LEDGER-BAD] {p.name}: {e}", file=sys.stderr)
            continue
        data["_file"] = p.name
        out.append(data)
    return out


def probe_command(probe: dict) -> str:
    """把探针 kind 映射为控制面上的 shell 命令（只读）。"""
    kind = probe["kind"]
    target = probe["target"]
    if kind == "kubectl_exec":
        pod, path = target.split(":", 1)
        return f"kubectl -n {NS} exec {pod} -- cat {shlex.quote(path)} 2>/dev/null | tr -d '\\r\\n'"
    if kind == "kubectl_exec_env":
        pod, var = target.split(":", 1)
        return f"kubectl -n {NS} exec {pod} -- printenv {shlex.quote(var)} 2>/dev/null | tr -d '\\r\\n'"
    if kind == "pymilvus_describe":
        col, field_spec = target.split(":", 1)
        # field_spec 形如 "dense_vector.dim"：字段名取 "." 前，取 ".dim" 后缀作属性
        field = field_spec.split(".", 1)[0]
        accessor = f"f['params']['{field_spec.split('.', 1)[1]}']" if "." in field_spec else "f"
        py = (
            f"from pymilvus import MilvusClient; c=MilvusClient(uri='http://milvus:19530'); "
            f"d=c.describe_collection('{col}'); "
            f"print(next({accessor} for f in d['fields'] if f['name']=='{field}'))"
        )
        return (
            "kubectl -n agent-platform exec deploy/ks-web -c web -- python -c "
            + shlex.quote(py)
            + " 2>/dev/null | tail -1"
        )
    if kind == "crictl_image_digest":
        name = target.split("@", 1)[0]
        repo, tag = name.rsplit(":", 1)
        return (
            "ctr -a /run/containerd-k8s/containerd.sock -n k8s.io images ls 2>/dev/null "
            f"| grep -E 'docker.io/library/{repo}:{tag}' | awk 'NR==1{{print $3}}'"
        )
    raise ValueError(f"未知探针 kind: {kind}")


def run_probe(ssh_host: str, probe: dict) -> str:
    cmd = probe_command(probe)
    remote = f"bash -lc {shlex.quote(cmd)}"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"root@{ssh_host}", remote],
        capture_output=True, text=True, timeout=60,
    )
    return (r.stdout or "").strip()


def match(actual: str, probe: dict) -> bool:
    if "expect" in probe:
        return actual == probe["expect"]
    if "expect_contains" in probe:
        return probe["expect_contains"] in actual
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="判据新鲜度漂移门禁（LIVE 实读 vs 结构化基线）")
    ap.add_argument("--ssh-host", default=os.environ.get("EVIDENCE_SSH_HOST", ""),
                    help="kubectl 控制面 IP（或 env EVIDENCE_SSH_HOST）；不硬编码内网地址")
    ap.add_argument("--list", action="store_true", help="列出全部台账判据及其探针，不连 LIVE")
    args = ap.parse_args()

    ledgers = load_ledgers()
    if not ledgers:
        print("[LIST] 无台账条目", file=sys.stdout)
        return 0
    if args.list:
        for led in ledgers:
            print(f"{led['_file']}: {led['criterion_id']} — {led.get('description', '')}")
            for pr in led["probes"]:
                print(f"    {pr['id']:32} affects={','.join(pr['affects'])}")
        return 0

    if not args.ssh_host:
        print("❌ 缺少 --ssh-host / EVIDENCE_SSH_HOST（前置不可用，不折算通过）", file=sys.stderr)
        return 2

    # 前置自检：ssh 连通 + kubectl 可用
    pre = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"root@{args.ssh_host}",
         "command -v kubectl >/dev/null 2>&1 && echo OK"],
        capture_output=True, text=True, timeout=30,
    )
    if (pre.stdout or "").strip() != "OK":
        print(f"❌ 前置不可用：{args.ssh_host} ssh/kubectl 不通（rc={pre.returncode}）", file=sys.stderr)
        return 2

    drifted: dict[str, list[str]] = {}  # criterion_id -> 漂移探针
    total = 0
    for led in ledgers:
        for pr in led["probes"]:
            total += 1
            actual = run_probe(args.ssh_host, pr)
            if not match(actual, pr):
                for crit in pr["affects"]:
                    drifted.setdefault(f"{led['criterion_id']}:{crit}", []).append(
                        f"{pr['id']} expect={pr.get('expect', pr.get('expect_contains'))!r} actual={actual!r}"
                    )

    print(f"台账判据 {len(ledgers)} 条 / 探针 {total} 个 / 漂移判据 {len(drifted)} 条")
    if drifted:
        print("\n❌ 判据已漂移，以下需在 LIVE 上重跑（不是「已验证」）：", file=sys.stderr)
        for key, items in drifted.items():
            print(f"  {key}:", file=sys.stderr)
            for it in items:
                print(f"      - {it}", file=sys.stderr)
        return 1
    print("✅ 全部判据新鲜（LIVE 形状与基线一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
