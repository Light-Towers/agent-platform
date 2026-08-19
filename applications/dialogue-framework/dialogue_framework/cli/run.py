"""run 子命令：启动对话（单次或 API server）。"""

import argparse

from dialogue_framework.shared.config import get_settings


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("run", help="启动对话")
    parser.add_argument("--message", "-m", help="单次对话消息")
    parser.add_argument("--session", default="default", help="会话 ID")
    parser.add_argument("--server", action="store_true", help="启动 API server")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    if args.server:
        return _run_server()
    if args.message:
        return _run_once(args.message, args.session)
    print("请用 --message 指定消息或 --server 启动服务")
    return 1


def _run_once(message: str, session: str) -> int:
    import asyncio

    from dialogue_framework.agent.message_processor import MessageProcessor

    async def _chat():
        mp = MessageProcessor()
        result = await mp.process(session, message)
        print(result["response"])
        return result.get("fallback", False)

    fallback = asyncio.run(_chat())
    return 1 if fallback else 0


def _run_server() -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "dialogue_framework.api.server:app",
        host=settings.host,
        port=settings.port,
    )
    return 0
