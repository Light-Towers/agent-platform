"""文档导入路由。

隔离契约（ADR-0006 T9/T10）：tenant_id 取服务端上下文（请求链路 ContextVar，
未绑定时回退部署级 DEFAULT_TENANT_ID），**不收客户端表单值**；
workspace_id 保留为归属维，写入前经 resolve_workspace 按调用方租户首次注册（幂等）。
``knowledge_id`` 归属维（plan-knowledge-base-model）：多知识库登记，空 = 未归属。

文本解析（``extract_text``）是公共件：``/kb/uploads`` 的 pgvector 本地分支复用
同一份实现，不复制第二遍（解析口径漂移 = 两路上传行为分叉）。
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


def extract_text(filename: str, raw: bytes) -> str:
    """按后缀抽取文本：.md/.markdown/.txt 直接解码，.pdf 用 pypdf。

    公共解析入口（/import 与 /kb/uploads 的 pgvector 本地分支共用）；
    不支持的后缀抛 ValueError，由调用方决定 HTTP 形状。
    """
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in _TEXT_SUFFIXES:
        return raw.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        return _extract_pdf(raw)
    raise ValueError(f"不支持的文件类型: {suffix or '未知'}")


@router.post("/import", response_model=ImportResponse)
async def import_document(
    file: UploadFile,
    workspace_id: str = "default",
    knowledge_id: str = "",
    _auth=Depends(verify_api_key),  # 仅作鉴权闸门（函数体不取凭据值，lint P12）
):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="知识库未启用（DATABASE_URL 未配置）")
    filename = file.filename or "upload"
    raw = await file.read()

    try:
        text = extract_text(filename, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    chunks = split_markdown(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档内容为空或无法切分")
    # 服务端租户边界（不收表单值）+ workspace 归属解析（ADR-0006 D4 方案 A，首次自动注册）
    tenant_id = server_tenant_id(get_settings().default_tenant_id)
    ws = workspace_id or "default"
    await resolve_workspace(pool, tenant_id, ws)
    doc_id = await add_document(
        pool, source=filename, chunks=chunks, workspace_id=ws,
        knowledge_id=(knowledge_id or "").strip(), tenant_id=tenant_id,
    )
    return ImportResponse(doc_id=doc_id, source=filename, chunks=len(chunks))
