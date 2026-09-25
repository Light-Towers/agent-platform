# -*- coding: utf-8 -*-
"""
eval 包：检索评测体系（M2，方案 §6）。

- ``golden_queries.jsonl``：脱敏 golden query 数据集（≥50 条，4 类 tag 全覆盖）。
- ``metrics.py``：检索指标纯函数（Recall@K / MRR / HitRate@K / nDCG@K），可独立单测。
- ``run_eval.py``：评测 CLI，逐条调用检索链路（召回→RRF→重排，不含 LLM 生成）并输出指标。
"""
