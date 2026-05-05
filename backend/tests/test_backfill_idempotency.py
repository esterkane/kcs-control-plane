from __future__ import annotations

from dataclasses import dataclass

from app.backfill.duplicate_embeddings import backfill_article_embeddings, compare_text_hash
from app.dedup.compare_text import build_compare_text
from app.ingestion.kb import NormalizedKbDocument


@dataclass
class FakeProvider:
    calls: int = 0

    def embed_batch(self, texts: list[str], task: str) -> list[list[float]]:
        self.calls += 1
        return [[0.1, 0.2] for _ in texts]


class FakeElasticsearchClient:
    def __init__(self, article_sources: list[tuple[str, dict[str, object]]]) -> None:
        self.article_sources = article_sources
        self.bulk_calls: list[list[tuple[str, dict[str, object]]]] = []

    def open_point_in_time(self, *, index: str, keep_alive: str) -> str:
        return "pit-1"

    def search_with_pit(
        self,
        *,
        pit_id: str,
        keep_alive: str,
        size: int,
        query: dict[str, object] | None = None,
        source_includes: list[str] | None = None,
        search_after: list[object] | None = None,
    ):
        if search_after is not None:
            return type("Page", (), {"hits": [], "pit_id": pit_id})()
        hits = [
            {"_id": document_id, "_source": source, "sort": [index + 1]}
            for index, (document_id, source) in enumerate(self.article_sources)
        ]
        return type("Page", (), {"hits": hits, "pit_id": pit_id})()

    def close_point_in_time(self, *, pit_id: str) -> None:
        return None

    def bulk_index(self, *, index: str, documents: list[tuple[str, dict[str, object]]]) -> None:
        self.bulk_calls.append(documents)


def test_backfill_skips_when_compare_text_hash_and_embedding_are_current() -> None:
    article = NormalizedKbDocument.model_validate(
        {
            "article_id": "article-1",
            "remote_document_id": "remote-1",
            "title": "VPN login failure",
            "summary": "Users cannot log in.",
            "body_markdown": "## Resolution\nRotate the client secret.",
            "symptoms": "Looping prompts",
            "category": "auth",
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": ["Cloud"],
            "components": ["Identity"],
            "product_versions": ["2025.4"],
            "deployments": ["Hosted"],
            "platforms": ["Web"],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": "2026-04-28T12:00:00Z",
            "source_index": "source-index",
            "compare_text": None,
            "compare_text_hash": None,
            "duplicate_comparison_embedding": None,
        }
    )
    text = build_compare_text(article)
    article_source = article.model_dump(mode="json", by_alias=True)
    article_source["compare_text"] = text
    article_source["compare_text_hash"] = compare_text_hash(text)
    article_source["duplicate_comparison_embedding"] = [0.1, 0.2]
    article_source["duplicate_title_embedding"] = [0.1, 0.2]
    article_source["duplicate_summary_embedding"] = [0.1, 0.2]
    article_source["duplicate_body_embedding"] = [0.1, 0.2]

    es_client = FakeElasticsearchClient([("remote-1", article_source)])
    provider = FakeProvider()

    stats = backfill_article_embeddings(
        es_client=es_client,
        provider=provider,
        task="retrieval.passage",
    )

    assert stats.updated_articles == 0
    assert stats.skipped_articles == 1
    assert provider.calls == 0
    assert es_client.bulk_calls == []


def test_backfill_sanitizes_lone_surrogates_before_hashing_and_embedding() -> None:
    article_source = {
        "article_id": "article-2",
        "remote_document_id": "remote-2",
        "title": "VPN\ud800 login failure",
        "summary": "Users cannot\ud800 log in.",
        "body_markdown": "## Resolution\nRotate\ud800 the client secret.",
        "symptoms": "Looping prompts",
        "category": "auth",
        "visibility_external": True,
        "visibility_was_published": True,
        "visibility_was_checked_in": True,
        "products": ["Cloud"],
        "components": ["Identity"],
        "product_versions": ["2025.4"],
        "deployments": ["Hosted"],
        "platforms": ["Web"],
        "ai_summary": None,
        "ai_subtitle": None,
        "ai_questions": [],
        "ai_tags": [],
        "source_updated_at": "2026-04-28T12:00:00Z",
        "source_index": "source-index",
        "compare_text": None,
        "compare_text_hash": None,
        "duplicate_comparison_embedding": None,
    }

    es_client = FakeElasticsearchClient([("remote-2", article_source)])
    provider = FakeProvider()

    stats = backfill_article_embeddings(
        es_client=es_client,
        provider=provider,
        task="retrieval.passage",
    )

    assert stats.updated_articles == 1
    assert provider.calls == 4
    updated_document = es_client.bulk_calls[0][0][1]
    assert "\ud800" not in updated_document["compare_text"]
    assert isinstance(updated_document["duplicate_title_embedding"], list)
    assert isinstance(updated_document["duplicate_summary_embedding"], list)
    assert isinstance(updated_document["duplicate_body_embedding"], list)
