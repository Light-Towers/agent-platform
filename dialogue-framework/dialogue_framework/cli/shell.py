"""shell 子命令：交互式对话 shell。"""

import argparse

from dialogue_framework.channels.console_channel import ConsoleChannel


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("shell", help="交互式对话 shell")
    parser.add_argument("--session", default="default", help="会话 ID")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import asyncio

    from dialogue_framework.agent.message_processor import MessageProcessor

    async def _shell():
        mp = MessageProcessor()
        channel = ConsoleChannel()
        print("dialogue-framework shell（输入 quit 退出）")
        while True:
            user_input = await channel.receive()
            if not user_input or user_input.lower() in ("quit", "exit"):
                break
            result = await mp.process(args.session, user_input)
            await channel.send(result["response"])
        return 0

    return asyncio.run(_shell())
