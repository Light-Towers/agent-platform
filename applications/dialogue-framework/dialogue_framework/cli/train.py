"""train 子命令：对齐 eval 训练。"""

import argparse


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("train", help="训练对话模型")
    parser.add_argument("--data", required=True, help="训练数据文件（JSONL）")
    parser.add_argument("--model-name", default="default", help="模型名称")
    parser.add_argument("--export", help="导出 golden.jsonl 到指定路径")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import asyncio

    from dialogue_framework.training.trainer import Trainer

    async def _train():
        trainer = Trainer()
        count = trainer.load_golden(args.data)
        print(f"loaded {count} examples")
        if args.export:
            trainer.export_golden(args.export)
            print(f"exported to {args.export}")
        result = await trainer.train(args.model_name)
        print(f"trained: {result}")
        return 0

    return asyncio.run(_train())
