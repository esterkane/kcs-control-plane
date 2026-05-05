from __future__ import annotations

from app.dedup.chunking import chunk_article_document, chunk_markdown_text
from app.ingestion.kb import NormalizedKbDocument


def test_chunker_splits_on_headings_and_preserves_heading_text() -> None:
    markdown = """
# Title

## Summary
One two three four five six seven.

## Resolution
Apply the fix and verify the outcome.
"""

    chunks = chunk_markdown_text(markdown, article_id="article-1")

    assert len(chunks) == 2
    assert chunks[0].text.startswith("## Title")
    assert "## Summary" in chunks[0].text
    assert chunks[1].text.startswith("## Title")
    assert "## Resolution" in chunks[1].text


def test_chunker_keeps_code_fences_together() -> None:
    markdown = """
## Resolution
Intro text.

```bash
line1
line2
line3
```

After code block.
"""

    chunks = chunk_markdown_text(markdown, article_id="article-2")

    assert any("```bash" in chunk.text and "line3" in chunk.text for chunk in chunks)
    assert len(chunks) == 1


def test_chunk_article_document_emits_typed_title_summary_and_body_chunks() -> None:
    article = NormalizedKbDocument.model_validate(
        {
            "article_id": "article-3",
            "remote_document_id": "remote-3",
            "title": "VPN login failure",
            "summary": "Users cannot log in.",
            "body_markdown": "## Resolution\nRotate the client secret.",
            "symptoms": None,
            "category": "auth",
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": [],
            "components": [],
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": "2026-04-29T07:00:00Z",
            "source_index": "source-index",
        }
    )

    chunks = chunk_article_document(article)

    assert chunks[0].chunk_kind == "title"
    assert chunks[1].chunk_kind == "summary"
    assert any(chunk.chunk_kind == "body_section" for chunk in chunks)
