#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主干复验（判据 6 形态）：在给定 merge sha 上实取，门禁预期集按 changed paths **派生**。

由本机取证探针 `.codeartsdoer/temp/verify_main_tip.py` 移植入库（方案：
`docs/plans/plan-evidence-scripts-intake-2026-10-04.md`）。入库理由：仓内多处账面把
「任何一次合入后必须在新 tip 上重跑本脚本」写成指针对象，而指针原本住在全目录被
`.gitignore` 忽略的 `.codeartsdoer/` 里 ⇒ 新克隆上脚本不存在，判据只在本机成立。

七项均 **fail-closed**（查不到即判未达成，绝不「查不到当通过」）：

  [A] 主干最新 CodeQL analysis 确已**按 sha 绑定**跑在该 tip（只看时间晚于合入不够）
  [B] open = 0
  [C] `dismissed_at` 非空 = 0（只认自动 fixed，不认人工 dismiss）
  [D] 全仓最大告警号不增（`--baseline-max-number`）
  [E] 合入时刻之后新建告警 = 0
  [F] 门禁 checks 全 success，且预期集由 `on.push.paths` × changed paths 派生
      —— 硬编码集合两个方向都会错：该跑的没进集合 ⇒ 它红了也没人按 [F] 看；
         不该跑的写进集合 ⇒ 永远等不到而被误判为未达成
  [G] 同 tip 其余任何非 success 的 check-run 逐条报红（**不设白名单**）

用法（可直接复制，参数是**具名**的，位置参数会报 usage）：

    uv run --no-sync python scripts/evidence/verify_main_tip.py \\
        --merge-sha <merge commit sha> \\
        --merged-at 2026-10-04T01:29:20Z --baseline-max-number 48

退出码：0 = 总体 PASS · 1 = 总体未达成 · 2 = 前置不可用（依赖缺失 / 本地 HEAD 不在待复核
tip / gh 调用失败 / git 取不到 changed paths），前置不可用**从不**被算成通过。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = "Light-Towers/agent-platform"
WORKFLOW_SUBDIR = os.path.join(".github", "workflows")
# CodeQL 的两个 Analyze check 不来自仓内 workflow 文件（GitHub 默认 code scanning
# setup，主干 push 上实测恒存在），故在派生结果之外单列为 always。
ALWAYS_CHECKS = ("Analyze (actions)", "Analyze (python)")

try:  # PyYAML 由已声明的直接依赖 `uvicorn[standard]` 传递保证（见方案 §2 非目标）。
    import yaml as _yaml
except ModuleNotFoundError:  # pragma: no cover - 仅在依赖缺失环境走到
    _yaml = None


class EvidenceDependencyError(RuntimeError):
    """PyYAML 缺席 ⇒ 拒绝降级成正则解析（正则取 `jobs:` 曾把真阳性红漏成无关项）。"""


def _safe_load(text: str) -> dict:
    if _yaml is None:
        raise EvidenceDependencyError(
            "缺少 PyYAML，无法可靠解析 workflow（刻意不回退到正则：`jobs:` 位于文件末尾时"
            "正则匹配不到终止符 ⇒ 该 check 静默掉出预期集）。请先 `uv sync --all-packages`。"
        )
    return _yaml.safe_load(text)


def pat_to_regex(pat: str) -> re.Pattern:
    """GitHub paths 语义的近似：`**` 跨目录、`*` 不跨目录、`?` 单字符。"""
    out, i = [], 0
    while i < len(pat):
        if pat[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _push_block(cfg: dict):
    """取 `on.push`。YAML 1.1 把裸 `on:` 解成布尔 True 键 ⇒ 两个键都要试。"""
    on = cfg.get("on")
    if on is None:
        on = cfg.get(True)
    return (on or {}).get("push") if isinstance(on, dict) else None


def derive_expected_checks(
    workflow_texts: dict[str, str],
    changed_paths: list[str],
) -> tuple[set[str], dict[str, dict]]:
    """纯函数：由 workflow 文本 + changed paths 派生「本批应出现的 check 名」。

    `workflow_texts` = ``{文件路径: 文件内容}``，不落盘、不打网络，便于单测（方案 §5 判据 3）。
    返回 ``(预期 check 名集合, 逐 workflow 的触发审计)``；审计里带上命中文件，
    这样「该跑没跑」与「不该跑却跑了」都能一眼归因。
    """
    expected: set[str] = set()
    audit: dict[str, dict] = {}
    for path, text in sorted(workflow_texts.items()):
        cfg = _safe_load(text) or {}
        push = _push_block(cfg)
        name = cfg.get("name") or Path(path).name
        job_names = sorted((cfg.get("jobs") or {}).keys())
        if push is None:
            triggered, hit = False, []
        elif isinstance(push, dict) and push.get("paths"):
            pats = push["paths"]
            hit = sorted({c for c in changed_paths for p in pats if pat_to_regex(p).match(c)})
            triggered = bool(hit)
        else:  # `on: push` 无 paths 过滤 ⇒ 主干每次 push 都跑
            triggered, hit = True, []
        audit["%s (%s)" % (name, Path(path).name)] = {
            "触发": triggered,
            "jobs": job_names,
            "命中文件": hit,
        }
        if triggered:
            expected.update(job_names)
    return expected | set(ALWAYS_CHECKS), audit


def load_workflow_texts(root: Path) -> dict[str, str]:
    wd = root / WORKFLOW_SUBDIR
    if not wd.is_dir():
        raise FileNotFoundError("workflow 目录不存在：%s" % wd)
    texts: dict[str, str] = {}
    for entry in sorted(os.listdir(wd)):
        if entry.endswith((".yml", ".yaml")):
            p = wd / entry
            texts[str(p)] = io.open(p, encoding="utf-8-sig").read()
    if not texts:
        raise FileNotFoundError("workflow 目录为空：%s" % wd)
    return texts


def _run(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(
            "%s 失败（rc=%d）：%s" % (" ".join(argv), proc.returncode, (proc.stderr or "").strip()[:300])
        )
    return proc.stdout.strip()


def gh_api(path: str, *, want_key: str | None = None):
    """打 GitHub API。analyses / alerts 返回**顶层数组**，check-runs 返回 `{check_runs: []}`。"""
    data = json.loads(_run(["gh", "api", path]) or "null")
    if want_key is None:
        return data
    return data.get(want_key) if isinstance(data, dict) else data


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_states(runs: list[dict], expected: set[str]) -> tuple[list[dict], list[dict], dict[str, list]]:
    """把 check-runs 拆成「预期内 / 预期外 / 同名多实例」三段，供 [F][G] 判定。"""
    seen: dict[str, list] = {}
    for r in runs:
        seen.setdefault(r["name"], []).append((r["status"], r["conclusion"]))
    missing = sorted(expected - set(seen))
    others = [r for r in runs if r["name"] not in expected]
    return missing, others, seen


def verify(merge_sha: str, merged_at: datetime, baseline_max_number: int) -> tuple[bool, list[str]]:
    """执行七项判定，返回 ``(是否 PASS, 逐条输出行)``。不打印，便于测试与落盘复用。"""
    out: list[str] = []
    ok = True
    tip = _run(["git", "rev-parse", merge_sha])
    out.append("tip = %s   merged_at = %s" % (tip, merged_at.isoformat()))

    # 门禁预期集取自**本地工作区** workflow（见下方 load_workflow_texts），其成立前提是
    # checkout 就停在被复核 tip 上；漂移时预期集与被复核对象错位（该红的 check 没进集合）。
    # ⇒ fail-closed：HEAD != tip 直接前置失败，绝不拿漂移的预期集硬算。
    head = _run(["git", "rev-parse", "HEAD"])
    if head != tip:
        raise RuntimeError(
            "本地 HEAD (%s) != 待复核 tip (%s)：门禁预期集取自本地工作区 workflow，"
            "checkout 漂移即错位；请先 git checkout 该 tip 再复核" % (head[:12], tip[:12])
        )

    changed = _run(["git", "diff", "--name-only", "%s^1" % tip, tip]).splitlines()
    expected, audit = derive_expected_checks(load_workflow_texts(Path(__file__).resolve().parents[2]), changed)
    out.append("=== 门禁预期集（按 changed paths 派生，changed=%d 个文件）===" % len(changed))
    for key, v in sorted(audit.items()):
        out.append("  %-48s 触发=%s jobs=%s 命中=%s" % (key, v["触发"], v["jobs"], v["命中文件"][:4]))
    out.append("  => 预期 check 名 = %s" % sorted(expected))

    # [A] 按 sha 绑定：commit_sha / ref / results_count 在 analyses 列表**顶层**（无 most_recent_instance）。
    analyses = gh_api("repos/%s/code-scanning/analyses?ref=refs/heads/main&per_page=20" % REPO) or []
    after = sorted((a for a in analyses if parse_ts(a["created_at"]) >= merged_at), key=lambda x: x["created_at"])
    if after:
        for a in after:
            out.append(
                "[A] analysis id=%s created=%s cat=%s commit=%s ref=%s results=%s rules=%s"
                % (
                    a["id"],
                    a["created_at"],
                    a["category"],
                    str(a.get("commit_sha"))[:7],
                    a.get("ref"),
                    a.get("results_count"),
                    a.get("rules_count"),
                )
            )
        if not [a for a in after if str(a.get("commit_sha", "")).lower() == tip]:
            ok = False
            out.append("[A] 未达成：新 analysis 未落在该 tip（仅时间晚于合入不够）")
    else:
        ok = False
        out.append("[A] 未达成：合入时刻后主干无新 analysis（重扫未完成，不得据旧快照下结论）")

    alerts = gh_api("repos/%s/code-scanning/alerts?state=open&per_page=100" % REPO) or []
    tail = "" if not alerts else "  => " + ", ".join("#%s %s" % (a["number"], a["rule"]["id"]) for a in alerts)
    out.append("[B] open = %d%s" % (len(alerts), tail))
    if alerts:
        ok = False

    all_alerts = gh_api("repos/%s/code-scanning/alerts?per_page=100" % REPO) or []
    dismissed = [a for a in all_alerts if a.get("dismissed_at")]
    out.append("[C] dismissed_at 非空 = %d（总数 %d）" % (len(dismissed), len(all_alerts)))
    if dismissed:
        ok = False
        for a in dismissed:
            out.append("      #%s reason=%s" % (a["number"], a.get("dismissal_reason")))

    max_number = max((a["number"] for a in all_alerts), default=0)
    out.append("[D] 全仓最大告警号 = %d（基线 %d）" % (max_number, baseline_max_number))
    if max_number > baseline_max_number:
        ok = False

    new_since = [a for a in all_alerts if parse_ts(a["created_at"]) >= merged_at]
    out.append("[E] 合入时刻后新建告警 = %d" % len(new_since))
    if new_since:
        ok = False
        for a in new_since:
            out.append("      #%s %s" % (a["number"], a["rule"]["id"]))

    runs = gh_api("repos/%s/commits/%s/check-runs" % (REPO, tip), want_key="check_runs") or []
    missing, others, seen = _record_states(runs, expected)
    if missing:
        ok = False
        out.append("[F] 未达成：预期应触发但未见（fail-closed，不当通过）：%s" % missing)
    for name in sorted(expected & set(seen)):
        states = seen[name]
        bad = [s for s in states if s[0] != "completed" or s[1] not in ("success", "neutral")]
        out.append("[F] %s: %s%s" % (name, states, "  => 未 success/未完成" if bad else ""))
        if bad:
            ok = False

    bad_others = [
        r
        for r in others
        if r["status"] != "completed" or r["conclusion"] not in ("success", "neutral", "skipped")
    ]
    out.append("[G] 预期外 check-run = %d，其中非 success = %d" % (len(others), len(bad_others)))
    for r in others:
        out.append(
            "      预期外：%s app=%s status=%s conclusion=%s"
            % (r["name"], r["app"]["slug"], r["status"], r["conclusion"])
        )
    for r in bad_others:
        ok = False
        out.append(
            "      未定性即判未达成：%s conclusion=%s title=%r"
            % (r["name"], r["conclusion"], (r.get("output") or {}).get("title"))
        )

    out.append("=== 总体：%s ===" % ("PASS" if ok else "未达成"))
    return ok, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--merge-sha", required=True, help="merge commit sha（不是 PR head sha）")
    ap.add_argument("--merged-at", required=True, help="gh 报的 mergedAt，如 2026-10-04T01:29:20Z")
    ap.add_argument("--baseline-max-number", type=int, default=48, help="合入前全仓最大告警号基线")
    ap.add_argument(
        "--out",
        default="",
        help="落盘路径；默认 .evidence-out/<tip 前 8 位>.txt（该目录被 .gitignore 的 `.*/` 规则忽略）",
    )
    args = ap.parse_args(argv)
    try:
        ok, lines = verify(args.merge_sha, parse_ts(args.merged_at), args.baseline_max_number)
    except EvidenceDependencyError as exc:
        print("IMPORT_FAIL：%s" % exc, file=sys.stderr)
        return 2
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print("PRECONDITION_FAIL（不折算成通过）：%s" % exc, file=sys.stderr)
        return 2

    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    dest = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / ".evidence-out" / ("%s.txt" % args.merge_sha[:8])
    dest.parent.mkdir(parents=True, exist_ok=True)
    io.open(dest, "w", encoding="utf-8", newline="").write(text)
    print("已落盘：%s" % dest)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
