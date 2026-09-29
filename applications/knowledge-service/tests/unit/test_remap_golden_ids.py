# -*- coding: utf-8 -*-
"""remap_golden_ids 纯逻辑单测（不连 Milvus，仅文件级映射重写）。"""

import json

from eval import remap_golden_ids as rg


def _write_golden(tmp_path, objs):
    lines = ["# header comment", "# line 2"]
    for o in objs:
        lines.append(json.dumps(o, ensure_ascii=False))
    p = tmp_path / "golden.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_map(tmp_path, mapping):
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"collection": "c", "map": mapping}), encoding="utf-8")
    return p


def test_rewrites_all_id_fields_and_preserves_header(tmp_path):
    golden = _write_golden(
        tmp_path,
        [{
            "qid": "g001",
            "query": "q",
            "relevant_chunk_ids": ["100"],
            "grade": {"100": 2, "200": 0},
            "hard_negative_ids": ["200"],
            "near_duplicate_ids": ["300"],
        }],
    )
    mapf = _write_map(tmp_path, {"100": "900", "200": "901", "300": "902"})

    rc = rg.main(["--map", str(mapf), "--golden", str(golden)])
    assert rc == 0

    text = golden.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# header comment"  # 注释头保留
    obj = json.loads([ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")][0])
    assert obj["relevant_chunk_ids"] == ["900"]
    assert obj["hard_negative_ids"] == ["901"]
    assert obj["near_duplicate_ids"] == ["902"]
    assert set(obj["grade"].keys()) == {"900", "901"}
    assert obj["grade"]["900"] == 2 and obj["grade"]["901"] == 0  # 分值随 id 迁移


def test_unmapped_id_kept_by_default(tmp_path):
    golden = _write_golden(tmp_path, [{"qid": "g1", "relevant_chunk_ids": ["100", "777"], "grade": {}}])
    mapf = _write_map(tmp_path, {"100": "900"})  # 777 不在映射

    rc = rg.main(["--map", str(mapf), "--golden", str(golden)])
    assert rc == 0
    obj = json.loads([ln for ln in golden.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")][0])
    assert obj["relevant_chunk_ids"] == ["900", "777"]  # 未映射保留原值


def test_strict_fails_on_unmapped(tmp_path):
    golden = _write_golden(tmp_path, [{"qid": "g1", "relevant_chunk_ids": ["777"], "grade": {}}])
    mapf = _write_map(tmp_path, {"100": "900"})

    rc = rg.main(["--map", str(mapf), "--golden", str(golden), "--strict"])
    assert rc == 1
    # strict 拒绝写入：原文件未被改，且不应生成 .bak
    assert not golden.with_suffix(golden.suffix + ".preremap.bak").exists()


def test_dry_run_does_not_write(tmp_path):
    golden = _write_golden(tmp_path, [{"qid": "g1", "relevant_chunk_ids": ["100"], "grade": {}}])
    before = golden.read_text(encoding="utf-8")
    mapf = _write_map(tmp_path, {"100": "900"})

    rc = rg.main(["--map", str(mapf), "--golden", str(golden), "--dry-run"])
    assert rc == 0
    assert golden.read_text(encoding="utf-8") == before  # dry-run 不改文件
