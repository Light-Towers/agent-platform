# -*- coding: utf-8 -*-
"""/upload 的 knowledge_id 必填校验（治本：空 ID 文档无法登记/发布/检索）。

校验在 resolve_server_tenant / 文件保存之前，空 ID 直抛 422、零外部依赖。
钉两件事：空串与纯空格都拒；报错文案含 KNOWLEDGE_ID_REQUIRED。
"""

from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

from knowledge_service.api.import_router import upload_files


def _file() -> UploadFile:
    return UploadFile(filename="a.pdf", file=io.BytesIO(b"pdf-bytes"))


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_upload_requires_knowledge_id(bad_id):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_files(
            background_tasks=BackgroundTasks(),
            files=[_file()],
            knowledge_id=bad_id,
        ))
    assert exc.value.status_code == 422
    assert "KNOWLEDGE_ID_REQUIRED" in str(exc.value.detail)
