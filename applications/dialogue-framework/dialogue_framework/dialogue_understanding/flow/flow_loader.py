"""FlowLoader：从 YAML 加载 Flow 定义。"""

from dialogue_framework.dialogue_understanding.flow.flow import Flow
from dialogue_framework.shared.yaml_loader import load_yaml


def load_flow(path: str) -> Flow:
    return Flow.from_dict(load_yaml(path))


def load_flows(path: str) -> dict[str, Flow]:
    data = load_yaml(path)
    return {fid: Flow.from_dict({"id": fid, **f}) for fid, f in data.items()}
