"""export 子命令：导出模型/训练数据。"""

import argparse


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("export", help="导出模型或训练数据")
    parser.add_argument("--model-name", default="default", help="模型名称")
    parser.add_argument("--output", required=True, help="导出路径")
    parser.add_argument("--format", choices=["golden", "finetune"], default="golden", help="导出格式")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from dialogue_framework.training.model_storage import ModelStorage

    storage = ModelStorage()
    model = storage.load(args.model_name)
    if model is None:
        print(f"model not found: {args.model_name}")
        return 1

    if args.format == "golden":
        import json
        from pathlib import Path

        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for i, ex in enumerate(model.get("examples", []), 1):
                item = {"id": i, **ex}
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"exported {len(model.get('examples', []))} examples to {path}")
    elif args.format == "finetune":
        import asyncio

        from dialogue_framework.training.finetune.data_generator import DataGenerator

        async def _gen():
            dg = DataGenerator()
            return await dg.generate(model.get("examples", []), args.output, augment=True)

        count = asyncio.run(_gen())
        print(f"exported {count} fine-tune samples to {args.output}")

    return 0
