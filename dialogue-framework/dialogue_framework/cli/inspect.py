"""inspect 子命令：检查模型/会话状态。"""

import argparse


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("inspect", help="检查状态")
    parser.add_argument("--models", action="store_true", help="列出所有模型")
    parser.add_argument("--model-name", help="查看指定模型详情")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from dialogue_framework.training.model_storage import ModelStorage

    storage = ModelStorage()

    if args.models:
        models = storage.list_models()
        if not models:
            print("no models found")
        for name in models:
            print(name)
        return 0

    if args.model_name:
        model = storage.load(args.model_name)
        if model is None:
            print(f"model not found: {args.model_name}")
            return 1
        print(f"model: {model.get('model_name')}")
        print(f"examples: {len(model.get('examples', []))}")
        for ex in model.get("examples", []):
            print(f"  {ex['question']} -> {ex['expected_capability']}")
        return 0

    print("请用 --models 或 --model-name 指定检查目标")
    return 1
