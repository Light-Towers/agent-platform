"""Markdown 切分器：标题感知 + 段落级切块 + 重叠窗口。

借鉴 RAGFlow 的理念——切分质量决定检索上限：保留标题上下文，
避免把块切在语义中间；单块超限才降级为滑窗切分。
"""

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    heading: str = ""


def split_markdown(text: str, max_chars: int = 400, overlap: int = 60) -> list[Chunk]:
    """按标题分段，再按段落聚合到 max_chars 以内。"""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    sections: list[tuple[str, str]] = []  # (heading, body)
    heading = ""
    body_lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith("#"):
            if "".join(body_lines).strip():
                sections.append((heading, "\n".join(body_lines)))
            heading = line.lstrip("#").strip()
            body_lines = []
        else:
            body_lines.append(line)
    if "".join(body_lines).strip():
        sections.append((heading, "\n".join(body_lines)))

    chunks: list[Chunk] = []
    for heading, body in sections:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        buffer = ""
        for para in paragraphs:
            candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if len(candidate) <= max_chars:
                buffer = candidate
                continue
            if buffer:
                chunks.append(Chunk(text=buffer, heading=heading))
            # 单段落超限：滑窗硬切
            if len(para) > max_chars:
                for piece in _window_split(para, max_chars, overlap):
                    chunks.append(Chunk(text=piece, heading=heading))
                buffer = ""
            else:
                buffer = para
        if buffer:
            chunks.append(Chunk(text=buffer, heading=heading))
    return chunks


def _window_split(text: str, size: int, overlap: int) -> list[str]:
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        pieces.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return pieces
