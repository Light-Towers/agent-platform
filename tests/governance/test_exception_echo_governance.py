"""C 类堆栈回显横切（CodeQL ``py/stack-trace-exposure``）的治理测试：P8 门禁。

对应 Batch 4 的「第③层强制门禁」：HTTP/SSE 对外响应体不得回显异常消息或堆栈，
脱敏边界点唯一（kernel ``agent_core.guardrails.errors``）。

**本文件同时是"规则非空转"的证据**：正例用的是修复前的真实原文行
（``skill_loader/app.py`` 3 处 + ``agent_server`` / ``knowledge-service`` 的 SSE 帧），
若判定面写得过窄，这些用例会先红。

脚本非包内模块，按文件路径加载（与 ``test_path_io_governance.py`` 同法）。
"""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture_p8", "scripts/lint_architecture.py")


# ---------------------------------------------------------------------------
# 单行判定：应命中（Batch 4 修复前的真实站点原文）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'yield _sse({"type": "error", "error": str(exc)})',
        'push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})',
        '{"error": f"Agent 处理失败: {e}", "llm_config": _llm.config_info()},',
        '{"error": f"warehouse 请求失败: {e}", "url": url}, status_code=502',
        '"error": str(e),',
        'return JSONResponse({"error": f"boom: {exc}"}, status_code=500)',
        'raise HTTPException(status_code=500, detail=str(err))',
        'return {"tb": traceback.format_exc()}',
        'resp = make_error_response(500, "INTERNAL_ERROR", f"内部异常：{exception}")',
    ],
)
def test_p8_flags_exception_echo(line):
    assert lint._is_exception_echo_line(line.strip()) is True


def test_p8_flags_class_name_plus_message_mix():
    """仅类名合规，但 ``类名: 消息`` 混写仍须命中（先剔类名再判消息）。"""
    assert lint._is_exception_echo_line('return f"工具执行失败：{type(e).__name__}: {e}"') is True


# ---------------------------------------------------------------------------
# 单行判定：应放行（合规去向 / 契约保留面）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        # 服务端日志：异常全貌的合规去向
        'logger.error(f"流程执行异常: {e}")',
        'logging.exception("stream failed: %s", exc)',
        'log.warning(f"重试中: {str(e)}")',
        # 注释行（文档/方案常引用旧写法）
        '# 旧写法：yield _sse({"error": str(exc)}) 属违规',
        # 仅类名，不含消息
        '"error_type": type(e).__name__,',
        'raise UpstreamError(f"warehouse 传输层故障：{type(exc).__name__}") from exc',
        # 4xx 客户端错误回显：D-2=A 保留现有 {detail} 信封，不在本不变量内
        'raise HTTPException(status_code=400, detail=f"JSON 解析失败：{exc}") from exc',
        'raise HTTPException(status_code=422, detail=f"ExecutionContext 校验失败：{exc}")',
        # Batch 4 修复后的合规写法
        'yield _sse({"type": "error", "error": mask_exception_for_client(exc)})',
        '"error": mask_exception_for_client(e, logger=logger, context="POST /api/chat"),',
    ],
)
def test_p8_allows_legitimate_lines(line):
    assert lint._is_exception_echo_line(line.strip()) is False


# ---------------------------------------------------------------------------
# 文件粒度前置：只有 HTTP/SSE 出口模块进判定面
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "@router.post('/query')\nasync def query():\n    ...\n",
        "async def h():\n    return JSONResponse({'ok': True})\n",
        "push_to_session(session_id, SSEEvent.ERROR, payload)\n",
        "yield _sse(frame)\n",
        "return FileResponse(path)\n",
    ],
)
def test_p8_recognizes_http_exit_modules(text):
    assert lint._is_http_exit_module(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # tool 观察字符串 / 内部节点：不经 HTTP 出口装饰器，属 P8 作用域外（另案登记）
        'def run_tool(q):\n    return f"查询出现异常：{str(e)}"\n',
        "async def _execute_tool(name, args):\n    return {'body': {'error': str(exc)}}\n",
    ],
)
def test_p8_skips_non_exit_modules(text):
    assert lint._is_http_exit_module(text) is False


# ---------------------------------------------------------------------------
# 当前树零违规 + 端到端扫描面
# ---------------------------------------------------------------------------


def test_p8_current_tree_has_zero_violations():
    assert lint.check_exception_echo_in_api_responses() == []


def test_p8_whitelist_is_deliberately_empty():
    """本不变量不允许静默例外：白名单必须保持为空。"""
    assert lint._EXC_ECHO_WHITELIST == ()


def test_p8_scan_flags_probes_and_spares_compliant_sites(tmp_path, monkeypatch):
    """埋探针验证判定面：出口违规各报一条，非出口/4xx/日志行放行。"""
    api_dir = tmp_path / "applications/foo/api"
    api_dir.mkdir(parents=True)
    (api_dir / "__init__.py").write_text("", encoding="utf-8")
    # 违规 1：SSE 帧回显消息
    (api_dir / "stream.py").write_text(
        "@router.post('/query')\n"
        "async def query():\n"
        '    yield _sse({"type": "error", "error": str(exc)})\n',
        encoding="utf-8",
    )
    # 违规 2：手写 JSONResponse 回显消息
    (api_dir / "chat.py").write_text(
        "@app.post('/api/chat')\n"
        "async def chat():\n"
        '    return JSONResponse({"error": f"Agent 处理失败: {e}"}, status_code=500)\n',
        encoding="utf-8",
    )
    # 合规：4xx 输入校验回显 + 日志行 + kernel 脱敏边界点
    (api_dir / "compliant.py").write_text(
        "@app.post('/api/encode')\n"
        "async def encode():\n"
        '    raise HTTPException(status_code=400, detail=f"JSON 解析失败：{exc}") from exc\n'
        '    logger.error(f"流程执行异常: {e}")\n'
        '    return JSONResponse({"error": mask_exception_for_client(e)})\n',
        encoding="utf-8",
    )
    # 合规：非 HTTP/SSE 出口模块（作用域外，另案登记）
    (tmp_path / "applications/foo" / "tools.py").write_text(
        'def run_tool(q):\n    return f"查询出现异常：{str(e)}"\n', encoding="utf-8"
    )
    # 合规：测试代码在排除面内
    tests_dir = tmp_path / "applications/foo/tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text(
        'def test_x():\n    return JSONResponse({"error": str(e)})\n', encoding="utf-8"
    )

    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_exception_echo_in_api_responses()

    assert len(violations) == 2, violations
    flagged = {v.split(":")[0] for v in violations}
    assert flagged == {"applications/foo/api/stream.py", "applications/foo/api/chat.py"}
