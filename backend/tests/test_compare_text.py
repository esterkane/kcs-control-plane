from __future__ import annotations

from app.dedup.compare_text import build_compare_text
from app.ingestion.kb import NormalizedKbDocument


def _document(**overrides: object) -> NormalizedKbDocument:
    base = {
        "article_id": "article-1",
        "remote_document_id": "remote-1",
        "title": "VPN login failure",
        "summary": "Users cannot log in.",
        "body_markdown": """
## References
https://example.com/reference

## Cause
The token expires unexpectedly.

## Resolution
Rotate the client secret.

## Environment
Production tenant only.
""",
        "symptoms": "Authentication prompts loop.",
        "category": "auth",
        "visibility_external": True,
        "visibility_was_published": True,
        "visibility_was_checked_in": True,
        "products": ["Cloud"],
        "components": ["Identity"],
        "product_versions": ["2025.4"],
        "deployments": ["Hosted"],
        "platforms": ["Web"],
        "ai_summary": "AI summary",
        "ai_subtitle": None,
        "ai_questions": ["Why are logins failing?"],
        "ai_tags": ["vpn", "auth"],
        "source_updated_at": "2026-04-28T12:00:00Z",
        "source_index": "source-index",
        "compare_text": None,
        "compare_text_hash": None,
        "duplicate_comparison_embedding": None,
    }
    base.update(overrides)
    return NormalizedKbDocument.model_validate(base)


def test_compare_text_prioritizes_key_fields_and_sections() -> None:
    compare_text = build_compare_text(_document())

    assert compare_text.startswith("# VPN login failure")
    assert "## Summary\nUsers cannot log in." in compare_text
    assert "## Symptoms\nAuthentication prompts loop." in compare_text
    assert "## Cause\nThe token expires unexpectedly." in compare_text
    assert "## Resolution\nRotate the client secret." in compare_text
    assert "## Environment\nProduction tenant only." in compare_text
    assert "## AI Summary\nAI summary" in compare_text
    assert "## AI Questions\n- Why are logins failing?" in compare_text
    assert "## AI Tags\nvpn, auth" in compare_text
    assert "products: Cloud" in compare_text


def test_compare_text_excludes_generic_reference_sections() -> None:
    compare_text = build_compare_text(_document())

    assert "https://example.com/reference" not in compare_text
    assert "## References" not in compare_text

