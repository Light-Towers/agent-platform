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
- 错误可见性（已修）：此前 `stderr=DEVNULL` 且不解析 opencode 的 `type=="error"`
  事件，上游真实错误被吞成 `[opencode error rc=1: ]` 空壳。现捕获 stderr + 解析
  error 事件，把真实 message 透出到 content 并落网关日志。
- 限流重试（已修）：`Detect Abuse Traffic`(403) 是**突发限流、非永久封禁**——对瞬时
  限流指数退避重试（默认 3 次、2s→4s→8s，env `OPENCODE_GATEWAY_MAX_RETRIES`/`_BACKOFF_BASE`
  可调）；确定性错误（400 token 类型/402 余额/模型不存在）不重试、直接透出。修掉"一次
  限流的错误文本被下游当 SQL、废掉整查询"的脆弱性。
- 全局串行闸 + 最小间隔（2026-10-18 补）：opencode 免费层是 **IP 级限额**（社区调研 +
  全天实测：约 10 RPM / 1 RPS、每日约 50 次，**并发 1 串行才是安全点**，burst 即 403）。
  故每次 `opencode run` 子进程前先过全局闸（默认容量 1）并保证与上次调用至少间隔
  `OPENCODE_GATEWAY_MIN_INTERVAL`（默认 1.2s）——把"并发请求各自起子进程"的突发
  形状压平再发。闸容量 env `OPENCODE_GATEWAY_MAX_CONCURRENCY` 可调（有付费额度时可放大）。
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


#: 限流重试配置（env 可调）：opencode 免费层 "Detect Abuse Traffic" 是**突发限流**
# （非永久封禁），退避重试即可恢复——单查询 ~4-5 次 LLM 调用里偶发一次被限流，
# 若不重试，那一次的错误文本会被下游当成"SQL"导致整查询失败。
_RETRY_ENV = "OPENCODE_GATEWAY_MAX_RETRIES"
_BACKOFF_ENV = "OPENCODE_GATEWAY_BACKOFF_BASE"

#: 全局串行闸（免费层 IP 级限额：社区调研 + 全天实测 ≈ 10 RPM / 1 RPS、每日约
#: 50 次，**并发 1 串行才是安全点**，burst 即 403）。容量 >1 时配合下面的最小
#: 间隔仍把请求速率压在限额内；env 可调（有付费额度/自建端点时可放大）。
_LLM_GATE = asyncio.Semaphore(int(os.environ.get("OPENCODE_GATEWAY_MAX_CONCURRENCY", "1")))
#: 相邻两次 opencode 调用的最小间隔（秒）：单查询内 4-5 次顺序调用 + 跨查询并发
#: 都过此闸，把 burst 形状压平再发（实测 1.2s 间隔下顺序调用零 403）。
_MIN_INTERVAL = float(os.environ.get("OPENCODE_GATEWAY_MIN_INTERVAL", "1.2"))
#: 上次放行的时间戳（monotonic；仅持闸方读写，无锁竞争）
_LAST_CALL_TS = 0.0


async def _acquire_llm_slot() -> None:
    """过闸 + 限速：持闸期间保证与上次 opencode 调用至少间隔 _MIN_INTERVAL。

    调用方必须 `async with _LLM_GATE:` 后调用本函数再起子进程——闸内改时间戳，
    容量 >1 时也不会有两个调用读到同一个 _LAST_CALL_TS。
    """
    global _LAST_CALL_TS
    elapsed = time.monotonic() - _LAST_CALL_TS
    if _LAST_CALL_TS > 0 and elapsed < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL_TS = time.monotonic()

#: 瞬时可重试的上游错误特征（403 反滥用 / 429 限流 / 503）。其余——400 token
# 类型不符、402 余额不足、模型不存在——是确定性错误，重试无益，直接透出。
_RATE_LIMIT_MARKERS = (
    "detect abuse traffic",
    "freetiererror",
    "rate limit",
    "too many requests",
    "429",
    "503",
)


def _is_rate_limit(error: str) -> bool:
    """上游错误是否属"瞬时限流、值得退避重试"。"""
    low = (error or "").lower()
    return any(marker in low for marker in _RATE_LIMIT_MARKERS)


async def _run_opencode_once(prompt: str, model: str) -> tuple[list[str], dict, str, str, int]:
    """跑一次 ``opencode run`` 并解析 NDJSON。

    全程持全局串行闸（免费层 IP 级限额：并发 1 是安全点），放行前保证与上次
    调用至少间隔 _MIN_INTERVAL——跨请求并发与单查询内顺序调用都压平再发。

    Returns:
        ``(text_parts, usage, upstream_error, stderr_txt, returncode)``——
        不 yield、不抛，把一次子进程执行的净结果交还给调用方（便于外层重试）。
    """
    async with _LLM_GATE:
        await _acquire_llm_slot()
        return await _run_opencode_locked(prompt, model)


async def _run_opencode_locked(prompt: str, model: str) -> tuple[list[str], dict, str, str, int]:
    """持闸后的真正执行（拆出来只为让 _run_opencode_once 的闸语义一眼可读）。"""
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
    text_parts: list[str] = []
    usage = {"total": 0, "input": 0, "output": 0}
    upstream_error = ""
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
                text_parts.append(text)
        elif etype == "error":
            # opencode 把上游错误（免费网关 403 反滥用 / 402 余额不足 / 400 token
            # 类型不符 / 模型不存在）作为结构化 error 事件发在 stdout——此前完全不
            # 解析，真实原因被吞成 "[opencode error rc=1: ]" 空壳。这里抽出 message。
            err = evt.get("error") or {}
            data = err.get("data") or {}
            upstream_error = (
                data.get("message") or err.get("message")
                or (err.get("name") + "" if err.get("name") else "")
                or json.dumps(err, ensure_ascii=False)
            )
        elif etype == "step_finish" and "part" in evt:
            tok = evt["part"].get("tokens", {})
            usage["total"] = tok.get("total", usage["total"])
            usage["input"] = tok.get("input", usage["input"])
            usage["output"] = tok.get("output", usage["output"])

    await proc.wait()
    stderr_txt = ""
    if proc.stderr is not None:
        try:
            stderr_txt = (await proc.stderr.read())[:500].decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - 读 stderr 失败不该盖过主流程
            stderr_txt = ""
    return text_parts, usage, upstream_error, stderr_txt, proc.returncode


async def _opencode_events(prompt: str, model: str, req_id: str):
    """把 opencode 结果转成 OpenAI chunk 字典流；对瞬时限流退避重试。

    纯数据生成器：yield dict（OpenAI chat.completion.chunk 结构），不负责 SSE 包装，
    供流式/非流式两条路径共用。重试只针对**瞬时限流**（403 反滥用/429），确定性
    错误（400/402/模型不存在）不重试、直接透出真实 message。
    """
    max_retries = int(os.environ.get(_RETRY_ENV, "3"))
    backoff_base = float(os.environ.get(_BACKOFF_ENV, "2.0"))
    created = int(time.time())
    # 先发一个 role=assistant 的空 chunk（OpenAI 惯例）——只发一次，重试不重发
    yield {
        "id": req_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }

    attempt = 0
    while True:
        text_parts, usage, upstream_error, stderr_txt, rc = await _run_opencode_once(prompt, model)
        if upstream_error:
            _log(f"opencode upstream error: {upstream_error}")
        # 仅"限流 + 还有重试额度"才退避重试；其余（成功/确定性错误/额度用尽）退出循环
        if not (upstream_error and _is_rate_limit(upstream_error)) or attempt >= max_retries:
            break
        attempt += 1
        delay = backoff_base * (2 ** (attempt - 1))  # 2s → 4s → 8s …
        _log(f"rate-limited ({upstream_error[:60]}); retry {attempt}/{max_retries} after {delay:.0f}s")
        await asyncio.sleep(delay)

    for text in text_parts:
        yield {
            "id": req_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }

    if upstream_error or rc != 0:
        # 真实错误透出到 content（OpenAI 流里唯一能带错误的位置）+ 落网关日志。
        # finish_reason=None：把它当作普通 content delta，让下面的收尾 chunk 正常
        # 发 finish_reason=stop + usage，流式路径才能收到 [DONE]（否则客户端挂等）。
        detail = upstream_error or stderr_txt or f"rc={rc}"
        _log(f"opencode run failed rc={rc} stderr={stderr_txt!r}")
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
            "prompt_tokens": usage["input"],
            "completion_tokens": usage["output"],
            "total_tokens": usage["total"],
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
