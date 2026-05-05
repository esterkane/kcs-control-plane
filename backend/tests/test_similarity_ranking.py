from __future__ import annotations

from app.elasticsearch.client import ElasticsearchClientError
from app.ingestion.kb import NormalizedKbDocument
from app.reranking.providers import RerankItem, StubRerankerProvider
from app.similarity.service import SimilarArticleService, SimilarSearchRequest


def _article(
    article_id: str,
    *,
    title: str,
    summary: str,
    compare_text: str,
    embedding: list[float],
    products: list[str] | None = None,
    components: list[str] | None = None,
    ai_tags: list[str] | None = None,
    category: str | None = "operations",
) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": article_id,
            "remote_document_id": f"{article_id}-remote",
            "title": title,
            "summary": summary,
            "body_markdown": compare_text,
            "symptoms": None,
            "category": category,
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": products or [],
            "components": components or [],
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": ai_tags or [],
            "source_updated_at": "2026-04-28T12:00:00Z",
            "source_index": "source-index",
            "compare_text": compare_text,
            "compare_text_hash": "hash",
            "duplicate_comparison_embedding": embedding,
        }
    )


class FakeReranker(StubRerankerProvider):
    def rerank(self, query: str, documents: list[str]) -> list[RerankItem]:
        return [
            RerankItem(index=0, relevance_score=0.9),
            RerankItem(index=1, relevance_score=0.3),
        ]


class FakeSimilarityService(SimilarArticleService):
    def __init__(self, query_article: NormalizedKbDocument, candidates: list[NormalizedKbDocument]) -> None:
        super().__init__(es_client=None, reranker=FakeReranker())  # type: ignore[arg-type]
        self.query_article = query_article
        self.candidates = {candidate.article_id: candidate for candidate in candidates}

    def get_article_by_id(self, article_id: str) -> NormalizedKbDocument | None:
        if article_id == self.query_article.article_id:
            return self.query_article
        return self.candidates.get(article_id)

    def _lexical_candidates(self, *, article: NormalizedKbDocument, limit: int) -> list[NormalizedKbDocument]:
        return list(self.candidates.values())

    def _embedding_candidates(self, *, article: NormalizedKbDocument, limit: int) -> list[NormalizedKbDocument]:
        return list(self.candidates.values())

    def _chunk_seed_candidates(self, *, article: NormalizedKbDocument, limit: int):
        return {}


def test_similarity_ranking_prefers_stronger_duplicate_candidate() -> None:
    query = _article(
        "query-1",
        title="VPN login failure",
        summary="Users cannot log in.",
        compare_text="Resolution steps for VPN login failure.",
        embedding=[1.0, 0.0],
        products=["Cloud"],
        components=["Identity"],
    )
    strong = _article(
        "candidate-strong",
        title="VPN login failure",
        summary="Users cannot log in after SSO redirect.",
        compare_text="Resolution steps for VPN login failure and redirect loop.",
        embedding=[0.98, 0.02],
        products=["Cloud"],
        components=["Identity"],
    )
    weak = _article(
        "candidate-weak",
        title="Printer setup article",
        summary="Peripheral setup guide.",
        compare_text="Configure office printer queues.",
        embedding=[0.1, 0.9],
        products=["Devices"],
        components=["Printing"],
    )

    service = FakeSimilarityService(query, [strong, weak])
    response = service.search(SimilarSearchRequest(articleId="query-1", limit=2))

    assert response.candidates[0].article_id == "candidate-strong"
    assert response.candidates[0].pair_scores.total_score > response.candidates[1].pair_scores.total_score


def test_lexical_candidates_fall_back_when_compare_text_query_is_too_large() -> None:
    query = _article(
        "query-1",
        title="VPN login failure",
        summary="Users cannot log in.",
        compare_text="word " * 5000,
        embedding=[1.0, 0.0],
    )
    candidate = _article(
        "candidate-1",
        title="VPN login failure",
        summary="Users cannot log in after redirect.",
        compare_text="Resolution steps for VPN login issues.",
        embedding=[0.99, 0.01],
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def search(self, *, index: str, body: dict):
            self.calls.append(body)
            fields = body["query"]["multi_match"]["fields"]
            if "compare_text^1.5" in fields:
                raise ElasticsearchClientError("Query rewrite failed: too many clauses")
            return [{"_source": candidate.model_dump(by_alias=False)}]

    client = RecordingClient()
    service = SimilarArticleService(es_client=client, reranker=FakeReranker())  # type: ignore[arg-type]

    results = service._lexical_candidates(article=query, limit=5)

    assert [item.article_id for item in results] == ["candidate-1"]
    assert len(client.calls) == 2
    assert "duplicate_comparison_embedding" in client.calls[0]["_source"]["includes"]
    assert "compare_text^1.5" in client.calls[0]["query"]["multi_match"]["fields"]
    assert client.calls[1]["query"]["multi_match"]["fields"] == ["title^4", "summary^2.5"]


def test_lexical_candidates_are_disabled_when_configured() -> None:
    query = _article(
        "query-1",
        title="VPN login failure",
        summary="Users cannot log in.",
        compare_text="Resolution steps for VPN login failure.",
        embedding=[1.0, 0.0],
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def search(self, *, index: str, body: dict):
            self.calls.append(body)
            return []

    client = RecordingClient()
    service = SimilarArticleService(
        es_client=client,  # type: ignore[arg-type]
        reranker=FakeReranker(),
        enable_lexical_search=False,
    )

    results = service._lexical_candidates(article=query, limit=5)

    assert results == []
    assert client.calls == []


def test_embedding_candidates_request_vector_fields_explicitly() -> None:
    query = _article(
        "query-1",
        title="VPN login failure",
        summary="Users cannot log in.",
        compare_text="Resolution steps for VPN login failure.",
        embedding=[1.0, 0.0],
    )
    candidate = _article(
        "candidate-1",
        title="VPN login failure",
        summary="Users cannot log in after redirect.",
        compare_text="Resolution steps for VPN login issues.",
        embedding=[0.99, 0.01],
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def search(self, *, index: str, body: dict):
            self.calls.append(body)
            return [{"_source": candidate.model_dump(by_alias=False)}]

    client = RecordingClient()
    service = SimilarArticleService(es_client=client, reranker=FakeReranker())  # type: ignore[arg-type]

    results = service._embedding_candidates(article=query, limit=5)

    assert [item.article_id for item in results] == ["candidate-1"]
    assert client.calls[0]["_source"]["includes"][-1] == "duplicate_body_embedding"
