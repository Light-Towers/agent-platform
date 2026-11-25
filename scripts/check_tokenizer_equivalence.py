"""行为等价门禁：混排样本在共享实现上的词项集合必须等于入库期望（ADR-0017 / T14）。

- 当前只校验 Python 侧单一实现（agent-runtime 共享模块）。引擎侧（Milvus jieba analyzer）
  的等价比对依赖 T2 的 POC 环境，环境就绪后在本脚本加 ``--mode engine``，不得先假装已验。
- ``--self-test`` 用故意错误的期望集证明本门禁能咬（rc != 0），然后返回 0；
  没有这一步，全绿只说明样本没跑，不说明门禁有效。
- 缺 jieba / 缺样本文件一律 rc=2（前置不可用），**不是 rc=0 通过**。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SAMPLES = Path(__file__).parent / "evidence" / "tokenizer_samples.json"


def _compare(samples: list[dict], tokenizer) -> list[str]:
    failures: list[str] = []
    for sample in samples:
        actual = set(tokenizer.tokenize(sample.get("text") or ""))
        expected = set(sample.get("expected_tokens") or [])
        if actual != expected:
            failures.append(
                f"{sample.get('id', '<unnamed>')}: missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="注入错误期望集，验证门禁会红")
    args = parser.parse_args(argv)

    if not SAMPLES.is_file():
        print(f"前置不可用：样本文件不存在 {SAMPLES}", file=sys.stderr)
        return 2
    try:
        from agent_runtime.retrieval_tokenizer import get_tokenizer
    except RuntimeError as exc:
        print(f"前置不可用：{exc}", file=sys.stderr)
        return 2

    tokenizer = get_tokenizer()
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))

    if args.self_test:
        poisoned = [dict(samples[0], expected_tokens=["__DELIBERATELY_WRONG__"])]
        failures = _compare(poisoned, tokenizer)
        if not failures:
            print("SELF-TEST FAILED: 注入错误期望集后门禁仍报绿", file=sys.stderr)
            return 1
        print(f"SELF-TEST PASS: 注入错误期望集后门禁报红（{failures[0]}）")
        return 0

    failures = _compare(samples, tokenizer)
    if failures:
        for line in failures:
            print(f"FAIL {line}", file=sys.stderr)
        return 1
    print(f"PASS: {len(samples)} 条混排样本词项集合与期望一致（Python 侧；引擎侧待 T2）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
