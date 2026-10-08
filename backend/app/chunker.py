"""Markdown 按标题层级切块。

策略：以 ## / ### 为切点，保留章节路径作为 heading 元数据；
超长章节内部按段落聚合到 ~1200 字；过短的相邻小节合并，避免碎块。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 1200
MIN_CHARS = 120

_HEADING = re.compile(r"^(#{2,4})\s+(.*)$")


@dataclass
class Chunk:
    seq: int
    heading: str
    content: str


def _split_long(text: str) -> list[str]:
    """超过 MAX_CHARS 的章节按段落聚合切分。"""
    parts: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) > MAX_CHARS:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return parts


def chunk_markdown(title: str, text: str) -> list[Chunk]:
    """按标题层级切块；代码块内的 # 不会被误判（_HEADING 锚定行首 #）。"""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = [("（开头）", [f"# {title}"])]
    for line in lines:
        m = _HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), [line]))
        else:
            sections[-1][1].append(line)

    raw: list[tuple[str, str]] = []
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        if len(body) > MAX_CHARS:
            for piece in _split_long(body):
                raw.append((heading, piece))
        else:
            raw.append((heading, body))

    # 合并过短块：并入前一块，但标题串接保留（引用溯源依赖标题）
    merged: list[tuple[str, str]] = []
    for heading, body in raw:
        if merged and len(body) < MIN_CHARS and len(merged[-1][1]) + len(body) <= MAX_CHARS:
            prev_h, prev_b = merged[-1]
            merged[-1] = (f"{prev_h}；{heading}", f"{prev_b}\n\n{body}")
        else:
            merged.append((heading, body))

    return [
        Chunk(seq=i, heading=h, content=c)
        for i, (h, c) in enumerate(merged)
    ]
