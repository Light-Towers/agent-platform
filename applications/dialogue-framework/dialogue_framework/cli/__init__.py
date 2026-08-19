"""CLI 入口：子命令分发（init/run/train/export/inspect/shell）。"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dialogue-framework",
        description="LLM 驱动的对话系统框架",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    from dialogue_framework.cli.export import add_subparser as add_export
    from dialogue_framework.cli.init import add_subparser as add_init
    from dialogue_framework.cli.inspect import add_subparser as add_inspect
    from dialogue_framework.cli.run import add_subparser as add_run
    from dialogue_framework.cli.shell import add_subparser as add_shell
    from dialogue_framework.cli.train import add_subparser as add_train

    add_init(subparsers)
    add_run(subparsers)
    add_train(subparsers)
    add_export(subparsers)
    add_inspect(subparsers)
    add_shell(subparsers)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
