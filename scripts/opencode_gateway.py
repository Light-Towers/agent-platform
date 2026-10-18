#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opencode-gateway：把 OpenAI 兼容 /v1/chat/completions 请求转发给 `opencode run`。

背景：agent-platform 用 langchain_openai.ChatOpenAI 走 OpenAI 兼容协议，
但开发机对公开端点 opencode.ai/zen/v1 的裸 curl 被 Cloudflare 403 拦截
（数据中心 IP + 缺 opencode 客户端鉴权头）。而 `opencode` CLI 自身能正常
调用模型——它走内置鉴权/路由通道。

本网关不提取 opencode 密钥，而是直接复用 opencode 已可用的通道：
把 OpenAI 格式的 chat/completions 请求翻译成 `opencode run` 子进程调用，
再把其 NDJSON 输出转回 OpenAI SSE 流。agent-platform 只需把
LLM_BASE_URL 指向本网关、LLM_API_KEY 填任意非空串即可离线跑真实 LLM。

用法：
    python scripts/opencode_gateway.py --port 8799 \
        --model opencode/deepseek-v4.1-flash-free

环境变量 OPENCODE_GATEWAY_MODEL 可覆盖默认模型。

**2026-10-18 现状（本开发机实测，三条路均不可用）**：
- `opencode/*-free` 免费模型：`403 FreeTierError "Detect Abuse Traffic"`——数据中心
  IP 被 opencode 反滥用网关封，非代码问题。
- `github-copilot/*`：`400 Personal Access Tokens are not supported`——GITHUB_TOKEN
  是 PAT，Copilot 端点只要 OAuth token。
- 结论：本机跑 opencode 需先解决上面任一项；否则改用任意 OpenAI 兼容端点
  （如同机 siliconflow， LangChain 直连即可，不必经本网关）。
- 错误可见性（本次修）：此前 `stderr=DEVNULL` 且不解析 opencode 的 `type=="error"`
  事件，上游真实错误被吞成 `[opencode error rc=1: ]` 空壳。现捕获 stderr + 解析
  error 事件，把真实 message 透出到 content 并落网关日志。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from shared_schemas import sse_pack


def _log(msg: str) -> None:
    """网关自身日志走 stderr（uvicorn 的 stdout 是响应流，不能污染）。"""
    print(f"[opencode-gateway] {msg}", file=sys.stderr, flush=True)

OPENAI_MODELS = {"opencode": "opencode/deepseek-v4.1-flash-free"}

app = FastAPI(title="opencode-gateway")


def _build_prompt(messages: list[dict[str, Any]]) -> str:
    """把 OpenAI messages 拼成 opencode 能理解的纯文本提示。

    opencode run 只接受单条 prompt 文本，不解析多轮角色。这里把
    messages 序列化为带角色前缀的文本，保留多轮上下文。
    """
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # 处理 content 为 [{"type": "text", "text": ...}] 的情况
            content = "\n".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        role_label = {
            "system": "System",
            "user": "User",
            "assistant": "Assistant",
            "tool": "Tool",
        }.get(role, role.capitalize())
        parts.append(f"{role_label}: {content}")
    return "\n\n".join(parts)


def _sse(data: dict) -> str:
    return sse_pack("", data)


async def _opencode_events(prompt: str, model: str, req_id: str):
    """调用 opencode run --format json，把 NDJSON 转成 OpenAI chunk 字典流。

    纯数据生成器：yield 的是 dict（OpenAI chat.completion.chunk 结构），
    不负责 SSE 包装，供流式/非流式两条路径共用，避免重复解析。
    """
    cmd = [
        "opencode", "run",
        "-m", model,
        "--format", "json",
        "--auto",          # 非交互：自动批准权限，避免卡在审批提示
        "--pure",          # 不加载外部插件，纯模型调用，减少副作用
        prompt,
    ]
    env = dict(os.environ)
    env["TERM"] = "dumb"           # 抑制 opencode TUI 进度条（避免污染日志/流）
    env["NO_COLOR"] = "1"
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=subprocess.DEVNULL,   # 非交互：避免 opencode 读 TTY 报 EBADF
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,     # 捕获 stderr：rc!=0 时它是唯一错误线索（此前 DEVNULL 全丢）
        env=env,
    )
    assert proc.stdout is not None
    created = int(time.time())
    # 先发一个 role=assistant 的空 chunk（OpenAI 惯例）
    yield {
        "id": req_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }

    usage_total = usage_input = usage_output = 0
    upstream_error = ""  # opencode 结构化错误事件的消息（type=="error"）
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")
        if etype == "text" and "part" in evt:
            text = evt["part"].get("text", "")
            if text:
                yield {
                    "id": req_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": text},
                                 "finish_reason": None}],
                }
        elif etype == "error":
            # opencode 把上游错误（如免费网关 403 反滥用 / 402 余额不足 / 400 token
            # 类型不符）作为结构化 error 事件发在 stdout——此前完全不解析，真实原因
            # 被吞成 "[opencode error rc=1: ]" 空壳。这里抽出 message 透出。
            err = evt.get("error") or {}
            data = err.get("data") or {}
            upstream_error = (
                data.get("message") or err.get("message")
                or (err.get("name") + "" if err.get("name") else "")
                or json.dumps(err, ensure_ascii=False)
            )
            _log(f"opencode upstream error: {upstream_error}")
        elif etype == "step_finish" and "part" in evt:
            tok = evt["part"].get("tokens", {})
            usage_total = tok.get("total", usage_total)
            usage_input = tok.get("input", usage_input)
            usage_output = tok.get("output", usage_output)

    await proc.wait()
    stderr_txt = ""
    if proc.stderr is not None:
        try:
            stderr_txt = (await proc.stderr.read())[:500].decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - 读 stderr 失败不该盖过主流程
            stderr_txt = ""

    if upstream_error or proc.returncode != 0:
        # 真实错误透出到 content（OpenAI 流里唯一能带错误的位置）+ 落网关日志。
        # finish_reason=None：把它当作普通 content delta，让下面的收尾 chunk 正常
        # 发 finish_reason=stop + usage，流式路径才能收到 [DONE]（否则客户端挂等）。
        detail = upstream_error or stderr_txt or f"rc={proc.returncode}"
        _log(f"opencode run failed rc={proc.returncode} stderr={stderr_txt!r}")
        yield {
            "id": req_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0,
                         "delta": {"content": f"[opencode error: {detail}]"},
                         "finish_reason": None}],
        }

    yield {
        "id": req_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage_input,
            "completion_tokens": usage_output,
            "total_tokens": usage_total,
        },
    }


async def _opencode_stream(prompt: str, model: str, req_id: str):
    """把 _opencode_events 的字典流包装成 OpenAI SSE 文本流。"""
    async for chunk in _opencode_events(prompt, model, req_id):
        if "usage" in chunk:
            # 最后一个 chunk 带 usage，附加到 SSE 后再发 [DONE]
            yield _sse(chunk)
            yield "data: [DONE]\n\n"
        else:
            yield _sse(chunk)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model") or os.environ.get("OPENCODE_GATEWAY_MODEL",
                                                 "opencode/deepseek-v4.1-flash-free")
    messages = body.get("messages", [])
    stream = body.get("stream", True)
    req_id = f"chatcmpl-{uuid.uuid4().hex}"
    prompt = _build_prompt(messages)

    if not stream:
        # 非流式：复用同一解析路径，累积 delta.content 组装完整对象
        content_parts: list[str] = []
        usage: dict = {}
        async for chunk in _opencode_events(prompt, model, req_id):
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
            if "usage" in chunk:
                usage = chunk["usage"]
        return JSONResponse({
            "id": req_id, "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant",
                                     "content": "".join(content_parts)},
                         "finish_reason": "stop"}],
            "usage": usage or {"prompt_tokens": 0,
                               "completion_tokens": 0,
                               "total_tokens": 0},
        })

    return StreamingResponse(
        _opencode_stream(prompt, model, req_id),
        media_type="text/event-stream",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "opencode"}


def main() -> None:
    parser = argparse.ArgumentParser(description="opencode OpenAI-compatible gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--model", default=os.environ.get(
        "OPENCODE_GATEWAY_MODEL", "opencode/deepseek-v4.1-flash-free"))
    args = parser.parse_args()
    os.environ["OPENCODE_GATEWAY_MODEL"] = args.model
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
