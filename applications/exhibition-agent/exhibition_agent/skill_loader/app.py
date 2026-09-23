"""会展 Skill 加载服务 — FastAPI 应用。

启动时读取 SKILL.md，解析 48 个端点，提供聊天界面让 LLM 自动选 skill 调用 warehouse。

环境变量：
- WAREHOUSE_BASE_URL：warehouse 后端地址，默认 http://192.168.100.241:8000
- SKILL_MD_PATH：SKILL.md 文件路径，默认 skill_loader 目录下的副本
- LLM_API_KEY：LLM API 密钥（必填才能用 /api/chat）
- LLM_BASE_URL：LLM API 地址，默认 https://api.openai.com/v1
- LLM_MODEL：模型名，默认 gpt-4o-mini
- TOOL_RESULT_MAX_CHARS：tool 结果喂给 LLM 的最大字符数，默认 8000
- MAX_TOOL_ROUNDS：最大 tool calling 轮数，默认 6

启动：
    cd applications/exhibition-agent
    uvicorn exhibition_agent.skill_loader.app:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import ExhibitionAgent
from .llm_client import LLMClient
from .parser import Endpoint, default_skill_md_path, load_endpoints

WAREHOUSE_BASE_URL = os.environ.get(
    "WAREHOUSE_BASE_URL",
    os.environ.get("EXHIBITION_API_BASE_URL", "http://127.0.0.1:8000"),
)
SKILL_MD_PATH = os.environ.get("SKILL_MD_PATH", str(default_skill_md_path()))

_endpoints: list[Endpoint] = []
_llm: LLMClient | None = None
_agent: ExhibitionAgent | None = None


def _ensure_agent() -> ExhibitionAgent:
    global _endpoints, _llm, _agent
    if _agent is None:
        _endpoints = load_endpoints(SKILL_MD_PATH)
        _llm = LLMClient()
        _agent = ExhibitionAgent(WAREHOUSE_BASE_URL, _llm, _endpoints)
    return _agent


app = FastAPI(title="会展 Skill 加载服务", docs_url="/docs")


class ChatRequest(BaseModel):
    messages: list[dict]


class InvokeRequest(BaseModel):
    method: str
    path: str
    params: dict[str, str] = {}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_HTML)


@app.get("/api/config")
async def get_config() -> dict:
    agent = _ensure_agent()
    return {
        "warehouse_base_url": WAREHOUSE_BASE_URL,
        "skill_md_path": SKILL_MD_PATH,
        "endpoint_count": len(agent.endpoints),
        "llm": _llm.config_info() if _llm else {},
    }


@app.get("/api/skills")
async def list_skills() -> dict:
    agent = _ensure_agent()
    return {
        "warehouse_base_url": WAREHOUSE_BASE_URL,
        "endpoints": [ep.to_dict() for ep in agent.endpoints],
        "count": len(agent.endpoints),
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> JSONResponse:
    agent = _ensure_agent()
    if not _llm.configured:
        return JSONResponse(
            {
                "error": "LLM_API_KEY 未配置",
                "hint": "请在服务环境变量中设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重启服务",
                "llm_config": _llm.config_info(),
            },
            status_code=503,
        )

    try:
        result = await agent.chat(req.messages)
        return JSONResponse(result)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            {"error": f"Agent 处理失败: {e}", "llm_config": _llm.config_info()},
            status_code=500,
        )


@app.post("/api/invoke")
async def invoke(req: InvokeRequest) -> JSONResponse:
    path = req.path
    if not path.startswith("/api/"):
        return JSONResponse({"error": "path must start with /api/"}, status_code=400)

    body_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    for k, v in req.params.items():
        if v == "":
            continue
        if f"{{{k}}}" in path:
            path = path.replace(f"{{{k}}}", v)
        elif req.method in ("GET", "DELETE"):
            query_params[k] = v
        else:
            body_params[k] = v

    url = f"{WAREHOUSE_BASE_URL}{path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if req.method == "GET":
                resp = await client.get(url, params=query_params)
            elif req.method == "DELETE":
                resp = await client.delete(url, params=query_params)
            elif req.method == "POST":
                resp = await client.post(url, json=body_params, params=query_params)
            else:
                return JSONResponse(
                    {"error": f"unsupported method: {req.method}"}, status_code=400
                )
        except httpx.RequestError as e:
            return JSONResponse(
                {"error": f"warehouse 请求失败: {e}", "url": url}, status_code=502
            )

    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = resp.text

    return JSONResponse(
        {
            "status_code": resp.status_code,
            "reason": resp.reason_phrase,
            "url": url,
            "method": req.method,
            "body": body,
        }
    )


@app.get("/api/health")
async def health() -> JSONResponse:
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{WAREHOUSE_BASE_URL}/api/health")
            return JSONResponse(
                {
                    "status": "ok",
                    "warehouse_base_url": WAREHOUSE_BASE_URL,
                    "warehouse": resp.json(),
                }
            )
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {
                    "status": "fail",
                    "warehouse_base_url": WAREHOUSE_BASE_URL,
                    "error": str(e),
                },
                status_code=502,
            )


_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>会展智能查询助手</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f6fa; color: #333; height: 100vh; display: flex; flex-direction: column; }
  .header { background: #1a1a2e; color: #fff; padding: 12px 24px; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header .info { flex: 1; display: flex; align-items: center; gap: 16px; font-size: 12px; }
  .header .info .item { display: flex; align-items: center; gap: 4px; }
  .header .info .label { color: #888; }
  .header .info .value { color: #4ecca3; font-family: monospace; }
  .header .info .value.warn { color: #e94560; }
  .header .status { font-size: 12px; padding: 4px 10px; border-radius: 12px; }
  .status.ok { background: #0f3460; color: #4ecca3; }
  .status.fail { background: #e94560; color: #fff; }
  .status.idle { background: #16213e; color: #aaa; }
  .chat-area { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
  .msg { max-width: 80%; padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .msg.user { align-self: flex-end; background: #4361ee; color: #fff; }
  .msg.assistant { align-self: flex-start; background: #fff; border: 1px solid #e0e0e0; }
  .msg.error { align-self: center; background: #fff3cd; border: 1px solid #ffc107; color: #856404; max-width: 90%; }
  .msg.system { align-self: center; background: #e8eeff; color: #555; font-size: 13px; max-width: 90%; }
  .tool-card { align-self: flex-start; max-width: 80%; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; font-size: 13px; overflow: hidden; }
  .tool-card .tc-header { padding: 8px 12px; background: #e9ecef; cursor: pointer; display: flex; align-items: center; gap: 8px; }
  .tool-card .tc-header .method { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; }
  .tool-card .tc-header .method.GET { background: #d4edda; color: #155724; }
  .tool-card .tc-header .method.POST { background: #cce5ff; color: #004085; }
  .tool-card .tc-header .method.DELETE { background: #f8d7da; color: #721c24; }
  .tool-card .tc-header .path { font-family: monospace; color: #555; flex: 1; }
  .tool-card .tc-header .code { font-size: 11px; padding: 2px 6px; border-radius: 3px; }
  .tool-card .tc-header .code.ok { background: #d4edda; color: #155724; }
  .tool-card .tc-header .code.err { background: #f8d7da; color: #721c24; }
  .tool-card .tc-header .toggle { color: #999; }
  .tool-card .tc-body { padding: 8px 12px; display: none; font-family: "Cascadia Code", Consolas, monospace; font-size: 12px; color: #495057; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow-y: auto; }
  .tool-card.open .tc-body { display: block; }
  .input-area { padding: 16px 24px; background: #fff; border-top: 1px solid #e0e0e0; display: flex; gap: 12px; flex-shrink: 0; }
  .input-area input { flex: 1; padding: 10px 16px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
  .input-area input:focus { outline: none; border-color: #4361ee; }
  .input-area button { padding: 10px 24px; background: #4361ee; color: #fff; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; }
  .input-area button:hover { background: #3a56d4; }
  .input-area button:disabled { background: #aaa; cursor: not-allowed; }
  .loading { align-self: flex-start; padding: 12px 16px; background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; font-size: 14px; color: #888; }
  .loading .dots::after { content: ''; animation: dots 1.5s infinite; }
  @keyframes dots { 0%,20% { content: '.'; } 40% { content: '..'; } 60%,100% { content: '...'; } }
  .empty-hint { text-align: center; color: #999; padding: 40px; font-size: 14px; }
  .empty-hint .examples { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; align-items: center; }
  .empty-hint .examples .ex { padding: 8px 16px; background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; cursor: pointer; font-size: 13px; color: #4361ee; }
  .empty-hint .examples .ex:hover { background: #e8eeff; }
</style>
</head>
<body>
<div class="header">
  <h1>会展智能查询助手</h1>
  <div class="info">
    <div class="item"><span class="label">Warehouse:</span><span class="value" id="wh-url">加载中...</span></div>
    <div class="item"><span class="label">LLM:</span><span class="value" id="llm-info">加载中...</span></div>
    <div class="item"><span class="label">端点:</span><span class="value" id="ep-count">-</span></div>
  </div>
  <button onclick="testConn()" style="padding:6px 14px;border:none;border-radius:4px;background:#0f3460;color:#fff;cursor:pointer;font-size:12px;">测试连接</button>
  <span id="conn-status" class="status idle">未连接</span>
</div>
<div class="chat-area" id="chat-area">
  <div class="empty-hint" id="empty-hint">
    输入问题开始查询，LLM 会自动选择合适的端点调用 warehouse
    <div class="examples">
      <div class="ex" onclick="useExample(this)">查一下展会概览</div>
      <div class="ex" onclick="useExample(this)">列出 3 条展会</div>
      <div class="ex" onclick="useExample(this)">场馆档期数据</div>
      <div class="ex" onclick="useExample(this)">查一下合同记录</div>
    </div>
  </div>
</div>
<div class="input-area">
  <input id="user-input" placeholder="输入问题，回车发送..." onkeydown="if(event.key==='Enter')send()">
  <button id="send-btn" onclick="send()">发送</button>
</div>
<script>
let messages = [];
let sending = false;

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const data = await r.json();
    document.getElementById('wh-url').textContent = data.warehouse_base_url;
    document.getElementById('ep-count').textContent = data.endpoint_count;
    const llm = data.llm;
    if (llm && llm.configured) {
      document.getElementById('llm-info').textContent = llm.model;
      document.getElementById('llm-info').classList.remove('warn');
    } else {
      document.getElementById('llm-info').textContent = '未配置';
      document.getElementById('llm-info').classList.add('warn');
    }
  } catch(e) {
    console.error('load config failed', e);
  }
}

function useExample(el) {
  document.getElementById('user-input').value = el.textContent;
  send();
}

function addMsg(role, content) {
  const area = document.getElementById('chat-area');
  const hint = document.getElementById('empty-hint');
  if (hint) hint.remove();
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = content;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div;
}

function addToolCard(tc) {
  const area = document.getElementById('chat-area');
  const card = document.createElement('div');
  card.className = 'tool-card';
  const codeClass = tc.status_code >= 200 && tc.status_code < 300 ? 'ok' : 'err';
  const pathDisplay = tc.path || tc.name;
  card.innerHTML = `
    <div class="tc-header" onclick="this.parentElement.classList.toggle('open')">
      <span class="method ${tc.method||'GET'}">${tc.method||'TOOL'}</span>
      <span class="path">${pathDisplay}</span>
      <span class="code ${codeClass}">${tc.status_code}</span>
      <span class="toggle">▼</span>
    </div>
    <div class="tc-body">参数: ${JSON.stringify(tc.args, null, 2)}\n\n结果摘要: ${tc.result_summary||''}</div>
  `;
  area.appendChild(card);
  area.scrollTop = area.scrollHeight;
}

function addLoading() {
  const area = document.getElementById('chat-area');
  const div = document.createElement('div');
  div.className = 'loading';
  div.id = 'loading-msg';
  div.innerHTML = 'Agent 思考中<span class="dots"></span>';
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function removeLoading() {
  const el = document.getElementById('loading-msg');
  if (el) el.remove();
}

async function send() {
  if (sending) return;
  const input = document.getElementById('user-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  sending = true;
  document.getElementById('send-btn').disabled = true;

  addMsg('user', text);
  messages.push({role: 'user', content: text});
  addLoading();

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({messages: messages})
    });
    const data = await r.json();
    removeLoading();

    if (data.error) {
      addMsg('error', '⚠ ' + data.error + (data.hint ? '\n\n' + data.hint : ''));
    } else {
      if (data.tool_calls && data.tool_calls.length) {
        for (const tc of data.tool_calls) {
          addToolCard(tc);
        }
      }
      if (data.reply) {
        addMsg('assistant', data.reply);
      }
      messages = data.messages || messages;
    }
  } catch(e) {
    removeLoading();
    addMsg('error', '请求失败: ' + e.message);
  }

  sending = false;
  document.getElementById('send-btn').disabled = false;
}

async function testConn() {
  const s = document.getElementById('conn-status');
  s.className = 'status idle'; s.textContent = '连接中...';
  try {
    const r = await fetch('/api/health');
    const data = await r.json();
    if (data.status === 'ok') { s.className = 'status ok'; s.textContent = '已连接 ✓'; }
    else { s.className = 'status fail'; s.textContent = '失败'; }
  } catch(e) { s.className = 'status fail'; s.textContent = '连接失败'; }
}

loadConfig();
</script>
</body>
</html>
"""
