"""SKILL.md 端点解析器。

从 mingyang-warehouse 的 exhibition-readonly/SKILL.md 解析出 48 个 REST 端点，
提取 method/path/路径参数/查询参数/分组/readiness/描述。

解析策略：
1. 只在 `## 端点速查` 与 `## 平台地基模块` 之间解析（排除地址/调用约定/平台地基部分的示例端点）
2. 按行扫描，跟踪当前 group（### 标题）和 readiness 上下文
3. `## 写操作` 之后统一归为"写操作"组（忽略 ### 子标题）
4. 跳过 curl 行（测试协议里的 curl 命令）
5. 用正则匹配反引号内的 `METHOD /api/...?query`（兼容 {EXHIBITION_API_BASE_URL} 前缀）
6. 提取路径参数 {xxx} 和查询参数 ?key=&key=20
7. 去重（同一 method+path 只保留一个）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_ENDPOINT_RE = re.compile(
    r"`(GET|POST|DELETE)\s+(?:\{EXHIBITION_API_BASE_URL\})?(/api/[\w/{}\-]+)(\?[^\s`]+)?`"
)
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")
_GROUP_RE = re.compile(r"^###\s+(.+?)$")
_SECTION_RE = re.compile(r"^##\s+(.+?)$")
_SKILL_SUB_RE = re.compile(r"^\*\*(\w+)\*\*\s*[（(]([^)）]*)[)）]")
_READINESS_KEYWORDS = ("PARTIAL", "SYNTHETIC", "READY")


@dataclass
class Param:
    name: str
    in_path: bool = False
    required: bool = True
    default: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "in_path": self.in_path,
            "required": self.required,
            "default": self.default,
        }


@dataclass
class Endpoint:
    method: str
    path: str
    group: str
    desc: str = ""
    readiness: str = ""
    params: list[Param] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "path": self.path,
            "group": self.group,
            "desc": self.desc,
            "readiness": self.readiness,
            "params": [p.to_dict() for p in self.params],
        }


_DESC_MAP: dict[str, str] = {
    "/api/health": "健康检查",
    "/api/overview": "概览",
    "/api/business-overview": "业务概览",
    "/api/profile": "画像概览",
    "/api/exhibition": "展会全量",
    "/api/venue": "场馆全量",
    "/api/exhibitor": "展商全量",
    "/api/organizer": "主办全量",
    "/api/audience": "观众全量",
    "/api/contract": "合同记录",
    "/api/safety": "安全记录",
    "/api/safety_monthly": "安全月度",
    "/api/meeting": "会议记录",
    "/api/clue": "线索记录",
    "/api/organizer-project-map": "主办项目映射",
    "/api/timeslot/exhibitions": "时段展会",
    "/api/timeslot/predictions": "时段预测",
    "/api/timeslot/macro": "宏观时段",
    "/api/exhibition-heat": "展会热度",
    "/api/exhibition-forecast": "展会预测",
    "/api/venue-forecast": "场馆预测",
    "/api/portrait/exhibitions": "展会列表",
    "/api/portrait/exhibition/{exhibition_id}": "展会画像",
    "/api/portrait/exhibitors": "展商列表",
    "/api/portrait/exhibitor/{exhibitor_id}": "展商画像",
    "/api/portrait/audiences": "观众列表",
    "/api/portrait/audience/{audience_id}": "观众画像",
    "/api/venue-dimension": "场馆维度",
    "/api/venue-exhibition-profile": "场馆展会画像",
    "/api/venue_party": "场馆参与方",
    "/api/venue-audience-radiation": "观众辐射",
    "/api/venue-positioning": "场馆定位",
    "/api/venue-schedule": "场馆档期",
    "/api/venue-cf-recommend": "场馆适配(合成)",
    "/api/venue-whitepaper": "场馆白皮书",
    "/api/venue-organizer-recommend": "推荐主办(合成)",
    "/api/organizer-venue-recommend": "推荐场馆(合成)",
    "/api/exhibitor-exhibition-recommend": "推荐展会(合成)",
    "/api/exhibitor-exhibition-schedule": "展会排期(合成)",
    "/api/exhibition-cf-recommend": "协同过滤推荐(合成)",
    "/api/external-affinity-recommend": "外部亲和",
    "/api/venue-recruit-strategy": "招商策略(合成)",
    "/api/organizer-risk-signal": "风险信号(合成)",
    "/api/organizer-retention": "主办留存(合成)",
    "/api/venue-retention-risk": "留存风险(合成)",
    "/api/leads": "创建线索",
    "/api/leads/{lead_id}": "删除线索(软)",
    "/api/leads/{lead_id}/confirm": "确认删除",
    "/api/leads/{lead_id}/reject": "驳回",
}


def _parse_query_params(query_str: str) -> list[Param]:
    if not query_str:
        return []
    params: list[Param] = []
    for pair in query_str.split("&"):
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        if not key:
            continue
        params.append(
            Param(
                name=key,
                in_path=False,
                required=False,
                default=val if val else None,
            )
        )
    return params


def _extract_readiness(text: str) -> str:
    for kw in _READINESS_KEYWORDS:
        if kw in text:
            return kw
    return ""


def parse_skill_md(content: str) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    seen: set[tuple[str, str]] = set()

    in_endpoint_section = False
    in_write_section = False
    in_test_protocol = False
    current_group = ""
    current_readiness = ""

    for line in content.splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            title = section_match.group(1).strip()
            if "端点速查" in title:
                in_endpoint_section = True
                in_write_section = False
                in_test_protocol = False
                continue
            if "写操作" in title:
                in_write_section = True
                in_test_protocol = False
                current_group = "写操作"
                current_readiness = ""
                continue
            if "平台地基" in title or "重要边界" in title or "触发场景" in title:
                in_endpoint_section = False
                in_write_section = False
                continue

        if not in_endpoint_section:
            continue

        if "curl" in line.lower():
            continue

        if in_write_section:
            group_match = _GROUP_RE.match(line)
            if group_match:
                title = group_match.group(1).strip()
                if "测试协议" in title:
                    in_test_protocol = True
                else:
                    in_test_protocol = False
                continue
            if in_test_protocol:
                continue
        else:
            group_match = _GROUP_RE.match(line)
            if group_match:
                title = group_match.group(1).strip()
                if "查询域" in title:
                    current_group = "查询域"
                elif "推荐域" in title:
                    current_group = "推荐域"
                elif "洞察域" in title:
                    current_group = "洞察域"
                else:
                    current_group = title
                current_readiness = _extract_readiness(title)
                continue

            skill_sub_match = _SKILL_SUB_RE.match(line.strip())
            if skill_sub_match:
                ctx = skill_sub_match.group(2)
                r = _extract_readiness(ctx)
                if r:
                    current_readiness = r

        for m in _ENDPOINT_RE.finditer(line):
            method = m.group(1)
            path = m.group(2)
            query_str = m.group(3) or ""

            if path.endswith("/") and len(path) > 1:
                path = path.rstrip("/")

            key = (method, path)
            if key in seen:
                continue
            seen.add(key)

            path_params = [
                Param(name=p, in_path=True, required=True)
                for p in _PATH_PARAM_RE.findall(path)
            ]
            query_params = _parse_query_params(query_str.lstrip("?"))
            readiness = current_readiness or _extract_readiness(line)
            desc = _DESC_MAP.get(path, "")

            endpoints.append(
                Endpoint(
                    method=method,
                    path=path,
                    group=current_group or "未分组",
                    desc=desc,
                    readiness=readiness,
                    params=path_params + query_params,
                )
            )

    return endpoints


def load_endpoints(skill_md_path: Path | str) -> list[Endpoint]:
    path = Path(skill_md_path)
    content = path.read_text(encoding="utf-8")
    return parse_skill_md(content)


def default_skill_md_path() -> Path:
    """返回默认 SKILL.md 路径：优先 skill_loader 目录下的副本，其次 mingyang-warehouse 源。"""
    here = Path(__file__).resolve().parent
    local_copy = here / "SKILL.md"
    if local_copy.exists():
        return local_copy

    candidates = [
        Path(r"D:\0-mingyang\code\mingyang-warehouse\skills\exhibition-readonly\SKILL.md"),
        Path("/data/mingyang-warehouse/skills/exhibition-readonly/SKILL.md"),
        Path.home() / "mingyang-warehouse" / "skills" / "exhibition-readonly" / "SKILL.md",
    ]
    for c in candidates:
        if c.exists():
            return c

    return local_copy
