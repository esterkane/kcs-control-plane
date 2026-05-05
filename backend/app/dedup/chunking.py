from __future__ import annotations

import re
from dataclasses import dataclass

from app.dedup.compare_text import parse_markdown_sections
from app.ingestion.kb import NormalizedKbDocument

TARGET_WORDS = 220
OVERLAP_WORDS = 40


@dataclass(frozen=True)
class ArticleChunk:
    chunk_id: str
    ordinal: int
    chunk_kind: str
    heading: str | None
    text: str
    word_count: int


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _primary_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            return heading or None
    return None


def _heading_prefix(document_heading: str | None, section_heading: str | None) -> str:
    lines: list[str] = []
    if document_heading:
        lines.append(f"## {document_heading}")
    if section_heading and section_heading != document_heading:
        lines.append(f"## {section_heading}")
    return "\n".join(lines)


def _split_blocks(section_text: str) -> list[str]:
    lines = section_text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    in_code_fence = False

    def flush() -> None:
        nonlocal current
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
        current = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code_fence and current:
                flush()
            current.append(line)
            in_code_fence = not in_code_fence
            if not in_code_fence:
                flush()
            continue

        if in_code_fence:
            current.append(line)
            continue

        if not stripped:
            flush()
            continue

        current.append(line)

    flush()
    return blocks


def _sliding_windows(text: str, prefix: str) -> list[str]:
    words = text.split()
    if len(words) <= TARGET_WORDS:
        prefix_text = f"{prefix}\n" if prefix else ""
        return [f"{prefix_text}{text.strip()}".strip()]

    step = max(TARGET_WORDS - OVERLAP_WORDS, 1)
    windows: list[str] = []
    for start in range(0, len(words), step):
        window_words = words[start : start + TARGET_WORDS]
        if not window_words:
            break
        prefix_text = f"{prefix}\n" if prefix else ""
        windows.append(f"{prefix_text}{' '.join(window_words)}".strip())
        if start + TARGET_WORDS >= len(words):
            break
    return windows


def chunk_markdown_text(markdown: str, *, article_id: str) -> list[ArticleChunk]:
    sections = parse_markdown_sections(markdown)
    document_heading = _primary_heading(markdown)
    chunks: list[ArticleChunk] = []
    ordinal = 0

    for section in sections:
        heading_prefix = _heading_prefix(document_heading, section.heading)
        blocks = _split_blocks(section.content)
        current_blocks: list[str] = []
        current_words = 0

        def flush_current() -> None:
            nonlocal ordinal, current_blocks, current_words
            if not current_blocks:
                return
            ordinal += 1
            prefix_text = f"{heading_prefix}\n" if heading_prefix else ""
            text = f"{prefix_text}{'\n\n'.join(current_blocks)}".strip()
            chunks.append(
                ArticleChunk(
                    chunk_id=f"{article_id}-chunk-{ordinal}",
                    ordinal=ordinal,
                    chunk_kind="body_section",
                    heading=section.heading,
                    text=text,
                    word_count=_word_count(text),
                )
            )
            current_blocks = []
            current_words = 0

        for block in blocks:
            block_words = _word_count(block)
            is_code_fence = block.lstrip().startswith("```")
            if not is_code_fence and block_words > TARGET_WORDS:
                flush_current()
                for window in _sliding_windows(block, heading_prefix):
                    ordinal += 1
                    chunks.append(
                        ArticleChunk(
                            chunk_id=f"{article_id}-chunk-{ordinal}",
                            ordinal=ordinal,
                            chunk_kind="body_section",
                            heading=section.heading,
                            text=window,
                            word_count=_word_count(window),
                        )
                    )
                continue

            projected_words = current_words + block_words
            if current_blocks and projected_words > TARGET_WORDS:
                flush_current()
            current_blocks.append(block)
            current_words += block_words

        flush_current()

    return chunks


def chunk_article_document(document: NormalizedKbDocument) -> list[ArticleChunk]:
    chunks: list[ArticleChunk] = []
    ordinal = 0

    def append_chunk(*, chunk_kind: str, heading: str | None, text: str) -> None:
        nonlocal ordinal
        normalized = text.strip()
        if not normalized:
            return
        ordinal += 1
        chunks.append(
            ArticleChunk(
                chunk_id=f"{document.article_id}-chunk-{ordinal}",
                ordinal=ordinal,
                chunk_kind=chunk_kind,
                heading=heading,
                text=normalized,
                word_count=_word_count(normalized),
            )
        )

    if document.title:
        append_chunk(chunk_kind="title", heading=document.title, text=f"# {document.title}")
    if document.summary:
        append_chunk(chunk_kind="summary", heading="Summary", text=f"## Summary\n{document.summary}")
    if document.symptoms:
        append_chunk(chunk_kind="symptoms", heading="Symptoms", text=f"## Symptoms\n{document.symptoms}")

    body_chunks = chunk_markdown_text(document.body_markdown or "", article_id=document.article_id)
    for chunk in body_chunks:
        ordinal += 1
        chunks.append(
            ArticleChunk(
                chunk_id=f"{document.article_id}-chunk-{ordinal}",
                ordinal=ordinal,
                chunk_kind=chunk.chunk_kind,
                heading=chunk.heading,
                text=chunk.text,
                word_count=chunk.word_count,
            )
        )
    return chunks
