"""init 子命令：初始化项目目录。"""

import argparse
from pathlib import Path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("init", help="初始化项目目录")
    parser.add_argument("--dir", default=".", help="项目目录（默认当前）")
    parser.add_argument("--force", action="store_true", help="覆盖已有文件")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)

    env_file = base / ".env"
    if not env_file.exists() or args.force:
        env_file.write_text(
            "STORE_BACKEND=json\n"
            "LLM_API_KEY=\n"
            "LLM_MODEL=gpt-4o-mini\n"
            "EMBEDDING_BACKEND=langchain_openai\n",
            encoding="utf-8",
        )
        print(f"created {env_file}")
    else:
        print(f"skip {env_file} (already exists)")

    flows_dir = base / "flows"
    flows_dir.mkdir(exist_ok=True)
    print(f"ensured {flows_dir}/")
    print("init done")
    return 0
