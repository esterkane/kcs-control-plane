from app.ingestion.kb import NormalizedKbDocument
from app.similarity.service import PairScores, SimilarChunkEvidence, _reason_codes, _shared_metadata


def _article(article_id: str, *, products: list[str], components: list[str], category: str) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": article_id,
            "remote_document_id": f"{article_id}-remote",
            "title": "VPN issue",
            "summary": "Login issue",
            "body_markdown": "Body",
            "symptoms": None,
            "category": category,
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": products,
            "components": components,
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": "2026-04-28T12:00:00Z",
            "source_index": "source-index",
            "compare_text": "compare",
            "compare_text_hash": "hash",
            "duplicate_comparison_embedding": [1.0, 0.0],
        }
    )


def test_evidence_formatting_includes_shared_metadata_and_reasons() -> None:
    left = _article("left", products=["Cloud"], components=["Identity"], category="operations")
    right = _article("right", products=["Cloud"], components=["Identity"], category="operations")
    shared = _shared_metadata(left, right)
    scores = PairScores(
        rrfScore=0.04,
        articleEmbeddingSimilarity=0.8,
        bestChunkSimilarity=0.7,
        titleSimilarity=0.7,
        summarySimilarity=0.6,
        metadataAgreement=1.0,
        rerankScore=0.8,
        totalScore=0.88,
    )
    chunks = [
        SimilarChunkEvidence(
            queryChunkId="q1",
            candidateChunkId="c1",
            similarity=0.72,
            queryHeading="Summary",
            candidateHeading="Resolution",
            queryText="Query chunk",
            candidateText="Candidate chunk",
        )
    ]

    reasons = _reason_codes(scores, shared, chunks)

    assert shared == {
        "products": ["Cloud"],
        "components": ["Identity"],
        "category": ["operations"],
    }
    assert "shared_metadata" in reasons
    assert "high_article_embedding_similarity" in reasons
    assert "chunk_seeded_match" in reasons

