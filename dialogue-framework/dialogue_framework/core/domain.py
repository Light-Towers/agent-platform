"""Domain：领域定义（intents/entities/flows），启动时从 YAML 加载单例。"""

from dataclasses import dataclass, field


@dataclass
class Domain:
    intents: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    flows: dict[str, dict] = field(default_factory=dict)
    responses: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Domain":
        return cls(
            intents=data.get("intents", []),
            entities=data.get("entities", []),
            flows=data.get("flows", {}),
            responses=data.get("responses", {}),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "Domain":
        from dialogue_framework.shared.yaml_loader import load_yaml

        return cls.from_dict(load_yaml(path))
