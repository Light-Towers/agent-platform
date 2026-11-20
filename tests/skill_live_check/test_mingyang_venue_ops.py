"""mingyang-venue-ops 实时端点回归（薄壳，逻辑全在 harness.py）。

运行：python -m pytest tests/skill_live_check/ -q
新集成 skill 只需：复制本文件改 MANIFEST 路径 + 在 skill 目录放一份 live.manifest.json。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import run_golden, run_manifest  # noqa: E402

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "applications"
    / "exhibition-agent"
    / "skills"
    / "venue-ops"
    / "live.manifest.json"
)
GOLDEN_DIR = MANIFEST.parents[4] / "tests" / "skill_live_check" / "golden"


def test_mingyang_venue_ops_live():
    results, failed = run_manifest(MANIFEST)
    assert not failed, f"{len(failed)} 个断言失败: " + "; ".join(f"{r[0]}|{r[1]}" for r in failed)


def test_golden_master():
    if not GOLDEN_DIR.is_dir() or not list(GOLDEN_DIR.glob("*.golden.json")):
        pytest.skip("golden 未初始化，先运行: python harness.py <manifest> --regen")
    results, failed = run_golden(MANIFEST, str(GOLDEN_DIR), regen=False)
    assert not failed, f"{len(failed)} 个黄金主失败: " + "; ".join(f"{r[0]}|{r[1]}({r[3]})" for r in failed)
