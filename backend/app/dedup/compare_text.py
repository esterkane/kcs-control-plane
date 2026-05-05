from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.ingestion.kb import NormalizedKbDocument

IMPORTANT_SECTION_ORDER = (
    "summary",
    "cause",
    "resolution",
    "workaround",
    "environment",
)
GENERIC_SECTION_TITLES = {
    "references",
    "reference",
    "external ids",
    "external id",
    "links",
    "related links",
    "additional resources",
}


@dataclass(frozen=True)
class MarkdownSection:
    heading: str | None
    normalized_heading: str | None
    content: str


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def parse_markdown_sections(markdown: str | None) -> list[MarkdownSection]:
    if markdown is None or not markdown.strip():
        return []

    lines = markdown.splitlines()
    sections: list[MarkdownSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    in_code_fence = False

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(
                MarkdownSection(
                    heading=current_heading,
                    normalized_heading=_normalize_heading(current_heading) if current_heading else None,
                    content=content,
                )
            )
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
        if not in_code_fence and stripped.startswith("#"):
            flush()
            current_heading = stripped.lstrip("#").strip()
            continue
        current_lines.append(line)
    flush()
    return sections


def _metadata_hints(document: NormalizedKbDocument) -> list[str]:
    hints: list[str] = []
    pairs = (
        ("products", document.products),
        ("components", document.components),
        ("versions", document.product_versions),
        ("deployments", document.deployments),
        ("platforms", document.platforms),
    )
    for label, values in pairs:
        if values:
            hints.append(f"{label}: {', '.join(values)}")
    return hints


def _format_section(heading: str, content: str) -> str:
    return f"## {heading}\n{content.strip()}"


def build_compare_text(document: NormalizedKbDocument) -> str:
    blocks: list[str] = []
    if document.title:
        blocks.append(f"# {document.title}")
    if document.summary:
        blocks.append(_format_section("Summary", document.summary))
    if document.symptoms:
        blocks.append(_format_section("Symptoms", document.symptoms))

    sections = parse_markdown_sections(document.body_markdown)
    important_sections: dict[str, str] = {}
    remaining_sections: list[str] = []
    for section in sections:
        heading = section.heading or "Body"
        normalized_heading = section.normalized_heading
        if normalized_heading in GENERIC_SECTION_TITLES:
            continue
        formatted = _format_section(heading, section.content)
        if normalized_heading in IMPORTANT_SECTION_ORDER and normalized_heading not in important_sections:
            important_sections[normalized_heading] = formatted
        else:
            remaining_sections.append(formatted)

    for section_name in IMPORTANT_SECTION_ORDER:
        formatted = important_sections.get(section_name)
        if formatted:
            blocks.append(formatted)
    blocks.extend(remaining_sections)

    if document.ai_summary:
        blocks.append(_format_section("AI Summary", document.ai_summary))
    if document.ai_questions:
        question_lines = "\n".join(f"- {question}" for question in document.ai_questions)
        blocks.append(_format_section("AI Questions", question_lines))
    if document.ai_tags:
        blocks.append(_format_section("AI Tags", ", ".join(document.ai_tags)))

    hints = _metadata_hints(document)
    if hints:
        blocks.append(_format_section("Metadata Hints", "\n".join(f"- {hint}" for hint in hints)))

    return "\n\n".join(block for block in blocks if block.strip()).strip()

