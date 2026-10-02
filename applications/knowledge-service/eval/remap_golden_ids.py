# -*- coding: utf-8 -*-
"""按 old→new PK 映射重写 golden 文件里的 chunk_id 引用（配合 reindex_sparse_local.py）。

背景：benchmark 集合 auto_id=True，重算稀疏须整集删重插 → 所有 chunk_id 变化。
    golden_queries.real.jsonl 的 relevant_chunk_ids / grade 键 / hard_negative_ids /
    near_duplicate_ids 均按真实 chunk_id 引用，故需同步重映射到新 id（内容不变，审计仍有效）。

安全性：
    - 重写前先落地 `<golden>.preremap.bak`（可回滚）。
    - 映射键为 reindex 从 pristine 备份产出的**原始 chunk_id**，与 golden 引用同源，故应全覆盖。
    - 任何 golden 里出现、但映射表没有的 chunk_id：默认告警并**保留原值**（--strict 则直接失败退出），
      便于人工甄别是否遗漏行，而非静默丢标注。

用法（126 容器内）：
    python eval/remap_golden_ids.py \
        --map eval/runs_server/reindex_pk_map_<ts>.json \
        --golden eval/golden_queries.real.jsonl [--dry-run] [--strict]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

_ID_FIELDS_LIST = ("relevant_chunk_ids", "hard_negative_ids", "near_duplicate_ids")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="按 PK 映射重写 golden 文件的 chunk_id 引用。")
    p.add_argument("--map", dest="map_path", required=True, help="reindex 产出的 old→new PK 映射 json")
    p.add_argument("--golden", required=True, help="待重映射的 golden jsonl（如 golden_queries.real.jsonl）")
    p.add_argument("--dry-run", action="store_true", help="只报告将改多少 id，不写文件")
    p.add_argument("--strict", action="store_true", help="存在未映射 chunk_id 时直接失败退出（默认仅告警保留原值）")
    return p.parse_args(argv)


def _load_map(map_path: Path) -> Dict[str, str]:
    with open(map_path, encoding="utf-8") as f:
        payload = json.load(f)
    raw = payload.get("map", payload) if isinstance(payload, dict) else {}
    return {str(k): str(v) for k, v in raw.items()}


def _iter_data_lines(lines: List[str]):
    """产出 (原行索引, 去注释后的 json 文本)；跳过空行与 # 注释头。"""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield idx, stripped


def _collect_ids(obj: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for field in _ID_FIELDS_LIST:
        for x in obj.get(field) or []:
            ids.add(str(x))
    for k in (obj.get("grade") or {}):
        ids.add(str(k))
    return ids


def _rewrite_obj(obj: Dict[str, Any], pk_map: Dict[str, str]) -> int:
    """就地按映射重写 obj 的 chunk_id 引用，返回命中替换次数。"""
    changed = 0
    for field in _ID_FIELDS_LIST:
        lst = obj.get(field)
        if isinstance(lst, list):
            new_lst = []
            for x in lst:
                sx = str(x)
                nx = pk_map.get(sx)
                if nx is not None:
                    new_lst.append(nx)
                    changed += 1
                else:
                    new_lst.append(x)
            obj[field] = new_lst
    grade = obj.get("grade")
    if isinstance(grade, dict):
        new_grade: Dict[str, Any] = {}
        for k, v in grade.items():
            sk = str(k)
            nk = pk_map.get(sk)
            if nk is not None:
                new_grade[nk] = v
                changed += 1
            else:
                new_grade[k] = v
        obj["grade"] = new_grade
    return changed


def main(argv=None) -> int:
    args = parse_args(argv)
    map_path = Path(args.map_path)
    golden_path = Path(args.golden)

    if not map_path.exists():
        print(f"错误：映射文件不存在：{map_path}", file=sys.stderr)
        return 1
    if not golden_path.exists():
        print(f"错误：golden 文件不存在：{golden_path}", file=sys.stderr)
        return 1

    pk_map = _load_map(map_path)
    print(f"[remap] 映射条目：{len(pk_map)} | 目标 golden：{golden_path}")

    lines = golden_path.read_text(encoding="utf-8").splitlines()
    unmapped: Set[str] = set()
    total_changed = 0
    out_lines: List[str] = []
    rewritten = 0

    for idx, text in _iter_data_lines(lines):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"错误：第 {idx + 1} 行 JSON 解析失败：{exc}", file=sys.stderr)
            return 1
        ids_in_obj = _collect_ids(obj)
        for i in ids_in_obj:
            if i not in pk_map:
                unmapped.add(i)
        changed = _rewrite_obj(obj, pk_map)
        total_changed += changed
        if changed:
            rewritten += 1
        out_lines.append(json.dumps(obj, ensure_ascii=False))
        # 记录原行前缀以便对齐（此处直接以数据行输出，注释头单独处理）

    # 重建输出：保留注释头/空行原样，数据行用重写后的对象。
    final_lines: List[str] = []
    data_iter = iter(out_lines)
    data_idx = {i for i, _ in _iter_data_lines(lines)}
    for idx, line in enumerate(lines):
        if idx in data_idx:
            final_lines.append(next(data_iter))
        else:
            final_lines.append(line)

    if unmapped:
        print(
            f"[remap] 警告：golden 中有 {len(unmapped)} 个 chunk_id 不在映射表（保留原值）：{sorted(unmapped)[:10]}"
            f"{'...' if len(unmapped) > 10 else ''}",
            file=sys.stderr,
        )
        if args.strict:
            print("[remap] --strict：存在未映射 id，拒绝写入。终止。", file=sys.stderr)
            return 1

    print(f"[remap] 将重写 {rewritten} 条 query、共 {total_changed} 处 chunk_id 引用。")
    if args.dry_run:
        print("[remap] --dry-run：未写文件。")
        return 0

    bak_path = golden_path.with_suffix(golden_path.suffix + ".preremap.bak")
    bak_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[remap] 已备份原 golden → {bak_path}")

    golden_path.write_text("\n".join(final_lines) + "\n", encoding="utf-8")
    print(f"[remap] 完成，已写回 {golden_path}")
    print("[remap] 下一步：复跑 run_route_ablation.py（--golden 该文件）与 run_e2e_eval.py 验证层2/e2e。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
