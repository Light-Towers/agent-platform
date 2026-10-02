# -*- coding: utf-8 -*-
"""验证 runtime 执行记忆实现已满足内核协议（ADR-0005 T0，零基类改动）。

runtime_checkable Protocol 的 isinstance 仅校验方法存在性与参数名（structural typing），
故 ``PgEpisodicStore`` / ``PgProceduralStore`` 无需改基类即可满足内核 ``EpisodicStoreProtocol`` /
``ProceduralStoreProtocol``。本测试锁定这一契约，防止未来实现漂移。
"""

from __future__ import annotations

import pytest
from agent_core.memory.execution import (
    EpisodicStoreProtocol,
    ProceduralStoreProtocol,
)


@pytest.mark.parametrize(
    "store_cls, protocol",
    [
        ("PgEpisodicStore", EpisodicStoreProtocol),
        ("PgProceduralStore", ProceduralStoreProtocol),
    ],
)
def test_runtime_store_satisfies_kernel_protocol(store_cls, protocol):
    from agent_runtime.memory_pg import PgEpisodicStore, PgProceduralStore

    target = {"PgEpisodicStore": PgEpisodicStore, "PgProceduralStore": PgProceduralStore}[store_cls]
    # pool=None 仅用于构造；isinstance 校验不调用任何方法（无 DB 依赖）。
    assert isinstance(target(None), protocol)
