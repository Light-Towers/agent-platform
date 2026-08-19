# -*- coding: utf-8 -*-
"""平台运行时原语（内核零依赖）。

把散落在各 feature 里的「横向基础能力」收口为可复用原语：
  - lease.py   幂等异步租约（生命周期清理协议）

按需增量扩展：新原语（sync bridge / background task runner / resilience policy 等）
在出现第二个复用方时再提取，避免过度设计（不过度设计原则）。
"""
