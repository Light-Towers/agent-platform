# dev-with-backend.ps1 — 本地前端连「服务器上已部署的后端」启动 vite。
#
# 背景：vite.config.ts 的默认代理目标是 127.0.0.1:8000（本机无后端 ⇒ 登录报
#   "请求未能发出 TypeError: Failed to fetch"）。设 VITE_DEV_BACKEND 指向已部署后端即可。
# 现网 agent-platform 是 NodePort 8000:30080；真值 IP 不入库，由运行时环境变量提供。
#
# 用法（在 web/ 目录）：
#   $env:BACKEND = "http://<internal-host>:30080"   # 填你网络里可达的节点地址
#   .\dev-with-backend.ps1
# 未设 BACKEND 时给出提示并退出，避免误用默认回环再次 Failed to fetch。

$ErrorActionPreference = 'Stop'
$BACKEND = $env:BACKEND
if (-not $BACKEND) {
  Write-Error '请先设置后端地址：$env:BACKEND = "http://<可达节点>:30080"（现网 NodePort 30080）'
  exit 1
}
$env:VITE_DEV_BACKEND = $BACKEND

Write-Output "后端代理目标: $BACKEND"
Write-Output "启动 vite: http://localhost:5173/ui/"

# 前台运行 node vite.js（pnpm 是 .cmd，不便在脚本里常驻；node 直调最稳，Ctrl+C 可停）。
$viteJs = Join-Path $PSScriptRoot 'node_modules\vite\bin\vite.js'
if (-not (Test-Path $viteJs)) { throw "未找到 $viteJs，先 pnpm install" }
Set-Location $PSScriptRoot
node $viteJs
