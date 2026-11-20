"""复杂任务级黄金测试：把 tasks.golden.json 里的"用户提示词 → 多端点编排"逐条执行并断言。

- 复用 harness 的传输层（多令牌 + cassette 录制/回放），故天然支持 live/record/replay 三种模式：
    python -m pytest tests/skill_live_check/ -q                          # live
    SKILL_HTTP_MODE=replay python -m pytest tests/skill_live_check/ -q   # 气隙回放
- 只断言『可达性 + 响应 schema』，不锁具体值（免疫数据漂移）。
- mode=="hitl" 的任务（写操作）不自动执行，skip 并登记，保证"写操作永不自跑"。
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import MODE, _http, load_tokens, resolve_base  # noqa: E402

MANIFEST = HERE.parents[1] / "applications" / "exhibition-agent" / "skills" / "venue-ops" / "live.manifest.json"
GOLDEN = HERE / "tasks.golden.json"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _ctx():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return load_tokens(str(MANIFEST)), resolve_base(m["base_url"])


@pytest.mark.parametrize("task", _golden()["tasks"], ids=lambda t: t["id"])
def test_complex_task(task):
    if task.get("mode") == "hitl" or not task.get("steps"):
        pytest.skip(f"[HITL/非执行] {task['id']}：{task.get('note', '写操作不自主执行')}")

    tokens, base = _ctx()
    for st in task["steps"]:
        key = st.get("jwt", task.get("jwt", "default"))
        jwt = tokens.get(key)
        if not jwt and MODE == "replay":
            jwt = "<replay-no-auth>"  # 气隙回放不发真实请求，无需真令牌
        assert jwt, f"缺令牌 '{key}'（见 manifest.jwt_files / jwt_search）"
        status, j = _http(st["method"], base, st["path"], st.get("params"), jwt)
        code, data = j.get("code"), j.get("data")
        tag = f"{task['id']}/{st.get('label', st['path'])}"

        assert status == st.get("expect_http", 200), f"{tag}: http={status} body={j}"
        assert code == st.get("expect_code", 200), f"{tag}: code={code} body={str(j)[:160]}"
        if st.get("expect_list"):
            assert isinstance(data, list), f"{tag}: 期望 list，实为 {type(data).__name__}"
        if st.get("expect_dict"):
            assert isinstance(data, dict), f"{tag}: 期望 dict，实为 {type(data).__name__}"
        for k in st.get("expect_keys", []):
            assert isinstance(data, dict) and k in data, f"{tag}: 缺字段 {k}（keys={list(data) if isinstance(data, dict) else data}）"
