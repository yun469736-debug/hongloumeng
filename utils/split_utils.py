"""RAG 文本切块工具，无第三方依赖。"""

from __future__ import annotations

import html
import re
from typing import TypedDict


class TextChunk(TypedDict):
    chunk_id: int
    content: str
    start: int
    end: int
    chapter_id: int
    chapter_title: str
    chapter_chunk_id: int


_CHAPTER = re.compile(
    r"(?m)^[ \t]*第[一二三四五六七八九十百千万零〇两0-9]+[回章][^\n]*"
)


def _clean_text(text: str) -> str:
    """还原段落和诗词换行，保留正文标点与对话。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"</?p\b[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_BOUNDARIES = (
    re.compile(r"\r?\n\s*\r?\n"),
    re.compile(r"\r?\n"),
    re.compile(r"[。！？；.!?;](?:[\"'”’）)]*)\s*"),
    re.compile(r"\s+"),
)


def split_text(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    *,
    split_by_chapter: bool = True,
    drop_preamble: bool = True,
) -> list[TextChunk]:
    """将文本切成可直接传给 embedding 的块。

    长度按 Python 字符数计算，不是模型 token 数。优先在块的后半段
    按空行、换行、句末标点、空白切分，无合适边界时按长度硬切。
    先转换 p/br 标签、解码 HTML 实体并整理空行，再按独立行回目/章名
    分组（兼容“第一百二十回”和“第一二零回”）。默认舍弃首个回目前
    的网站说明、简介；drop_preamble=False 可保留它们为第 0 组。
    没有回目时切分全文；split_by_chapter=False 可关闭章节识别。
    同回相邻块精确重叠 chunk_overlap 个字符，不跨回重叠。

    返回字段：chunk_id 为全局序号（从 0 开始），chapter_id 为识别顺序
    （从 1 开始，无章节为 0），chapter_title 为完整回目，chapter_chunk_id
    为回内序号（从 0 开始）。content 不包含回目；start/end 为去掉回目和
    首尾空白后的清洗版本回正文中的左闭右开位置，不是原文件位置。
    空白文本返回 []；回目保留为元数据，空章节不产生块。
    要求 chunk_size > 0 且 0 <= chunk_overlap < chunk_size。

    示例：
        chunks = split_text(text, chunk_size=800, chunk_overlap=120)
        for chunk in chunks:
            vector = get_cloud_embedding(chunk["content"])
    """
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")
    for name, value in (("chunk_size", chunk_size), ("chunk_overlap", chunk_overlap)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} 必须是整数")
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap 必须满足 0 <= chunk_overlap < chunk_size")
    if not isinstance(split_by_chapter, bool) or not isinstance(drop_preamble, bool):
        raise TypeError("split_by_chapter 和 drop_preamble 必须是布尔值")
    text = _clean_text(text)
    if not text.strip():
        return []

    headings = list(_CHAPTER.finditer(text)) if split_by_chapter else []
    sections: list[tuple[int, str, str]] = []
    if headings:
        if not drop_preamble and text[:headings[0].start()].strip():
            sections.append((0, "", text[:headings[0].start()].strip()))
        for i, heading in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            sections.append((i + 1, heading.group().strip(), text[heading.end():end].strip()))
    else:
        sections.append((0, "", text))

    chunks: list[TextChunk] = []
    for chapter_id, chapter_title, body in sections:
        for chapter_chunk_id, (start, end) in enumerate(_split_spans(body, chunk_size, chunk_overlap)):
            chunks.append({
                "chunk_id": len(chunks),
                "content": body[start:end],
                "start": start,
                "end": end,
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "chapter_chunk_id": chapter_chunk_id,
            })
    return chunks


def _split_spans(text: str, chunk_size: int, chunk_overlap: int):
    """返回单回内连续切块的位置，长段落降级到句末或字符边界。"""
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 边界必须超过重叠区，保证每次都向前推进。
            minimum = start + max(chunk_size // 2, chunk_overlap + 1)
            for boundary in _BOUNDARIES:
                candidates = [
                    match.end()
                    for match in boundary.finditer(text, start, end)
                    if match.end() >= minimum
                ]
                if candidates:
                    end = candidates[-1]
                    break
        yield start, end
        if end == len(text):
            break
        start = end - chunk_overlap
