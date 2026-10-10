"""只读控制台页面路由：GET /console.html 返回页面壳。

与 knowledge-service 的 `/import.html` 同惯例：**静态页壳免鉴权、数据接口全部带密钥**
（免鉴权路径集见 agent_core.guardrails.auth.DEFAULT_EXEMPT_PATHS）。
本路由**不返回任何业务数据**——页面上每一行字都来自平台自己的正式接口
（/query、/history、/health），因此不存在"为这场演示新开的口子"。

同源直发 ⇒ 不需要 CORS；也不新增执行路径（只是把已有接口拼成一个界面）。
"""

from pathlib import Path

from agent_core.guardrails.fs import PathTraversalError, safe_join
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# 页面壳目录：agent_server/static（随包一起 COPY 进镜像）。
# 文件名是服务端常量，但路径拼接仍走内核 safe_join —— P7 门禁要求 API 层的路径 IO
# 统一经 containment 判定，不因"这里没有用户输入"而留一条例外（例外即破窗）。
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_PAGE_NAME = "console.html"


@router.get("/console.html", response_class=FileResponse)
async def console_page():
    """返回只读控制台页面壳（不含数据、不含示例内容）。"""
    try:
        path = safe_join(_STATIC_DIR, _PAGE_NAME)
    except PathTraversalError as exc:
        # 常量文件名不可能越界；真发生说明部署被改坏，报 500 且不回显路径细节。
        raise HTTPException(status_code=500, detail="CONSOLE_PAGE_UNAVAILABLE") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="console page not found")
    # no-store：这个壳是打进镜像的，滚动升级后若浏览器沿用缓存壳，屏上跑的是**旧事件契约**
    # 配**新接口**（实跑中已撞到一次：改完页面浏览器仍给旧行为，误判成"修复没生效"）。
    # 页面无 Cookie、无用户数据，不缓存不损可用性。
    return FileResponse(path=path, media_type="text/html", headers={"Cache-Control": "no-store"})
