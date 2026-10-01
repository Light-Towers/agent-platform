"""文档导入路由。

隔离契约（ADR-0006 T9/T10）：tenant_id 取服务端上下文（请求链路 ContextVar，
未绑定时回退部署级 DEFAULT_TENANT_ID），**不收客户端表单值**；
workspace_id 保留为归属维，写入前经 resolve_workspace 按调用方租户首次注册（幂等）。
"""

from agent_runtime.db import get_pool
from agent_runtime.workspace_registry import resolve_workspace, server_tenant_id
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from agent_server.api.auth import verify_api_key
from agent_server.config import get_settings
from agent_server.rag.chunker import split_markdown
from agent_server.rag.embed import embed_query  # noqa: F401 — re-export 保持兼容
from agent_server.rag.store import add_document
from agent_server.schemas import ImportResponse

router = APIRouter()

_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


@router.post("/import", response_model=ImportResponse)
async def import_document(
    file: UploadFile,
    workspace_id: str = "default",
    api_key=Depends(verify_api_key),
):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="知识库未启用（DATABASE_URL 未配置）")
    filename = file.filename or "upload"
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    raw = await file.read()

    if suffix in _TEXT_SUFFIXES:
        text = raw.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        text = _extract_pdf(raw)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix or '未知'}")

    chunks = split_markdown(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档内容为空或无法切分")
    # 服务端租户边界（不收表单值）+ workspace 归属解析（ADR-0006 D4 方案 A，首次自动注册）
    tenant_id = server_tenant_id(get_settings().default_tenant_id)
    ws = workspace_id or "default"
    await resolve_workspace(pool, tenant_id, ws)
    doc_id = await add_document(
        pool, source=filename, chunks=chunks, workspace_id=ws, tenant_id=tenant_id
    )
    return ImportResponse(doc_id=doc_id, source=filename, chunks=len(chunks))


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise HTTPException(
            status_code=400, detail="PDF 支持需安装可选依赖: pip install agent-platform[pdf]"
        ) from exc
    import io

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)
