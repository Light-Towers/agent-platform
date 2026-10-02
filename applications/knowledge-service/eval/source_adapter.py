# -*- coding: utf-8 -*-
"""
数据源插拔契约（Phase B，回答"新增数据源怎么接进来评测"）。

核心区分（决定评测口径，不是可选项）：
- **同构 id 源（rrf）**：返回带可归一到 canonical chunk_id 的文档（embedding / hyde / kg）。
  价值来自"同 id 文档的跨路共识增益"（score[chunk_id] += 各路 1/(k+rank)），故进 RRF。
  非 Milvus 原生 id 命名空间（如 kg 的 `kg::{item}::{name}`）须提供 id 别名 sidecar 归一到
  canonical，否则与向量路不同基准、无法公平比较。
- **异构内容源（rerank）**：无 canonical id（如 web 的 title/url/snippet）。进 RRF 无共识增益、
  盲信搜索排名、粒度不可比（既有设计结论），故只在 **rerank 阶段**用 cross-encoder 公平合流。

新增数据源接入清单（缺一不可，`onboarding_checklist()` 输出供写进报告/README）：
  1. 实现适配器：`retrieve(query, state) -> docs`，每 doc 带文本与（若能）id；
  2. 声明合流类别：merge = rrf 或 rerank；
  3. 同构且非 Milvus id → 产出 `<source>_id_map.json` sidecar（`别名 → canonical`）；
     异构 → 标记 needs_id_alias=False 且不得进 RRF；
  4. golden 侧补 `expected_source` 标注（该 query 本应由哪条通道答，供分通道贡献归因）；
  5. 通过 add-one-in 边际贡献门禁（`eval/analysis.contribution_rows`）：证明加源对目标桶
     净提升或不显著（不得为负向显著）才允许默认开启。

框架无关：仅 stdlib，不连 Milvus/Neo4j；具体 retrieve 由运行器注入。
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 合流类别
MERGE_RRF = "rrf"        # 同构：有可归一 canonical id，进加权 RRF
MERGE_RERANK = "rerank"  # 异构：无 canonical id，只在 rerank 阶段合流


@dataclass(frozen=True)
class SourceSpec:
    """一个召回数据源的评测侧契约声明。"""

    name: str
    merge: str                       # MERGE_RRF | MERGE_RERANK
    needs_id_alias: bool = False     # 非 Milvus 原生 id 命名空间 → 需 sidecar 归一

    def __post_init__(self) -> None:
        if self.merge not in (MERGE_RRF, MERGE_RERANK):
            raise ValueError(f"非法合流类别：{self.merge!r}（可选 {MERGE_RRF}/{MERGE_RERANK}）")


# 当前已登记的数据源（与 retrieval.yaml channels 对齐；web 为异构、不进 RRF）
DEFAULT_SOURCES: Tuple[SourceSpec, ...] = (
    SourceSpec("embedding", MERGE_RRF),
    SourceSpec("hyde", MERGE_RRF),
    SourceSpec("kg", MERGE_RRF, needs_id_alias=True),
    SourceSpec("web", MERGE_RERANK),
)


def spec_for(name: str, registry: Sequence[SourceSpec] = DEFAULT_SOURCES) -> Optional[SourceSpec]:
    for s in registry:
        if s.name == name:
            return s
    return None


def rrf_channels(registry: Sequence[SourceSpec] = DEFAULT_SOURCES) -> Tuple[str, ...]:
    """进 RRF 的同构通道（排除 web 等异构源）。"""
    return tuple(s.name for s in registry if s.merge == MERGE_RRF)


def rerank_channels(registry: Sequence[SourceSpec] = DEFAULT_SOURCES) -> Tuple[str, ...]:
    """只在 rerank 阶段合流的异构通道。"""
    return tuple(s.name for s in registry if s.merge == MERGE_RERANK)


def alias_channels(registry: Sequence[SourceSpec] = DEFAULT_SOURCES) -> Tuple[str, ...]:
    """需要 id 别名 sidecar 的通道。"""
    return tuple(s.name for s in registry if s.needs_id_alias)


def default_id_map_path(name: str, eval_dir: Optional[Path] = None) -> Path:
    """泛化 sidecar 命名：`<eval>/<name>_id_map.json`（kg → kg_id_map.json，向后兼容）。"""
    base = eval_dir or Path(__file__).resolve().parent
    return base / f"{name}_id_map.json"


def load_id_map(path: Path) -> Dict[str, str]:
    """读 id 别名 sidecar（`别名 → canonical`）；不存在/非法 → 空表（退化为不归一，不伪造）。"""
    if not path or not Path(path).exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"[source-adapter] 警告：id_map 读取失败，不归一（{path}）：{e}", file=sys.stderr)
        return {}


def alias_ids(docs: List[Dict[str, Any]], id_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """把源侧命名空间 id（如 kg::…）归一到 canonical（Milvus 真实 chunk_id）。

    通用版（取代 kg 专用实现）：id_map 为空 → 原样返回；命中映射 → 复制并替换 chunk_id。
    只改 eval 取回的候选 dict，不碰线上检索代码。
    """
    if not id_map:
        return docs
    out: List[Dict[str, Any]] = []
    for doc in docs:
        cid = str(doc.get("chunk_id", ""))
        canonical = id_map.get(cid)
        out.append({**doc, "chunk_id": canonical} if canonical else doc)
    return out


def parse_id_map_arg(pairs: Sequence[str]) -> Dict[str, Path]:
    """
    解析 `--id-map source=path` 可重复参数 → {source: Path}。

    非法（无 `=` 或空）抛 ValueError，供 argparse type 报错。
    """
    out: Dict[str, Path] = {}
    for p in pairs or []:
        if "=" not in p:
            raise ValueError(f"--id-map 需形如 source=path，实际 {p!r}")
        name, _, path = p.partition("=")
        name = name.strip()
        if not name or not path.strip():
            raise ValueError(f"--id-map 需形如 source=path，实际 {p!r}")
        out[name] = Path(path.strip())
    return out


def onboarding_checklist() -> List[str]:
    """新增数据源接入清单（报告/README 直接引用，把"隐性约定"变显性门禁）。"""
    return [
        "1. 实现 retrieve(query, state) -> docs（每 doc 带文本与（若能）id）",
        "2. 声明合流类别 merge ∈ {rrf（同构可归一 id）, rerank（异构无 id）}",
        "3. 同构非 Milvus id → 产出 <source>_id_map.json（别名→canonical）；异构不得进 RRF",
        "4. golden 补 expected_source 标注（该 query 本应由哪条通道答）",
        "5. 通过 add-one-in 边际贡献门禁（对目标桶净提升或不显著，不得负向显著）才默认开启",
    ]


__all__ = [
    "MERGE_RRF",
    "MERGE_RERANK",
    "SourceSpec",
    "DEFAULT_SOURCES",
    "spec_for",
    "rrf_channels",
    "rerank_channels",
    "alias_channels",
    "default_id_map_path",
    "load_id_map",
    "alias_ids",
    "parse_id_map_arg",
    "onboarding_checklist",
]
