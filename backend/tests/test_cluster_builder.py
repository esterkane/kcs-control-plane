from __future__ import annotations

from app.clustering.service import (
    DuplicateClusterService,
    DuplicateEdgeDocument,
    _cluster_id,
)
from app.config import ClusterMaterializationRequest
from app.ingestion.kb import NormalizedKbDocument
from app.similarity.service import PairScores, SimilarEvidence


class FakeEsClient:
    def __init__(self, existing_clusters: list[dict] | None = None) -> None:
        self.existing_clusters = existing_clusters or []

    def index_exists(self, *, index: str) -> bool:
        return bool(self.existing_clusters)

    def search(self, *, index: str, body: dict) -> list[dict]:
        query = body.get("query", {})
        if "terms" not in query:
            return []
        cluster_ids = set(query["terms"].get("cluster_id", []))
        return [
            {"_source": cluster}
            for cluster in self.existing_clusters
            if cluster.get("cluster_id") in cluster_ids
        ]


class FakeSimilarityService:
    pass


def _article(article_id: str, title: str | None = None) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": article_id,
            "remote_document_id": f"{article_id}-remote",
            "title": title or article_id,
            "summary": None,
            "body_markdown": None,
            "symptoms": None,
            "category": "operations",
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": ["Cloud"],
            "components": ["Identity"],
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": "2026-04-28T12:00:00Z",
            "source_index": "source",
            "compare_text": "Compare text",
            "compare_text_hash": "hash",
            "duplicate_comparison_embedding": [1.0, 0.0],
        }
    )


def _edge(
    left: str,
    right: str,
    *,
    total_score: float,
    label: str = "near_duplicate",
    reasons: list[str] | None = None,
    article_embedding_similarity: float | None = None,
    best_chunk_similarity: float | None = None,
    title_similarity: float | None = None,
    summary_similarity: float | None = None,
    metadata_agreement: float = 1.0,
    rerank_score: float | None = None,
) -> DuplicateEdgeDocument:
    article_embedding_similarity = total_score if article_embedding_similarity is None else article_embedding_similarity
    best_chunk_similarity = total_score if best_chunk_similarity is None else best_chunk_similarity
    title_similarity = total_score if title_similarity is None else title_similarity
    summary_similarity = total_score if summary_similarity is None else summary_similarity
    rerank_score = total_score if rerank_score is None else rerank_score
    return DuplicateEdgeDocument.model_validate(
        {
            "edgeId": f"edge-{left}-{right}",
            "leftArticleId": left,
            "rightArticleId": right,
            "label": label,
            "accepted": True,
            "totalScore": total_score,
            "pairScores": PairScores(
                rrfScore=0.01,
                articleEmbeddingSimilarity=article_embedding_similarity,
                bestChunkSimilarity=best_chunk_similarity,
                titleSimilarity=title_similarity,
                summarySimilarity=summary_similarity,
                metadataAgreement=metadata_agreement,
                rerankScore=rerank_score,
                totalScore=total_score,
            ),
            "evidence": SimilarEvidence(
                sharedMetadata={"products": ["Cloud"]},
                mostSimilarChunks=[],
                reasons=reasons or ["shared_metadata"],
            ),
            "sourceQueryArticleId": left,
            "sourceCandidateArticleId": right,
            "materializedAt": "2026-04-28T12:00:00Z",
        }
    )


def _service(existing_clusters: list[dict] | None = None) -> DuplicateClusterService:
    return DuplicateClusterService(
        es_client=FakeEsClient(existing_clusters=existing_clusters),  # type: ignore[arg-type]
        similarity_service=FakeSimilarityService(),  # type: ignore[arg-type]
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )


def test_cluster_build_is_deterministic_for_same_inputs() -> None:
    service = _service()
    article_titles = {article.article_id: article.title for article in [_article("a"), _article("b"), _article("c")]}
    request = ClusterMaterializationRequest(topN=12, maxComponentSize=12, weakEdgeThreshold=0.78)
    first_edges = [_edge("a", "b", total_score=0.92, label="exact_duplicate"), _edge("b", "c", total_score=0.9)]
    second_edges = list(reversed(first_edges))

    first = service.build_clusters(article_titles=article_titles, edges=first_edges, request=request)
    second = service.build_clusters(article_titles=article_titles, edges=second_edges, request=request)

    assert [cluster.model_dump() for cluster in first] == [cluster.model_dump() for cluster in second]


def test_cluster_build_splits_weak_bridge_components() -> None:
    service = _service()
    article_titles = {
        article.article_id: article.title
        for article in [_article("a"), _article("b"), _article("c"), _article("d")]
    }
    request = ClusterMaterializationRequest(topN=12, maxComponentSize=12, weakEdgeThreshold=0.78)
    edges = [
        _edge("a", "b", total_score=0.91, label="exact_duplicate"),
        _edge("c", "d", total_score=0.9, label="exact_duplicate"),
        _edge("b", "c", total_score=0.7, label="near_duplicate"),
    ]

    clusters = service.build_clusters(article_titles=article_titles, edges=edges, request=request)

    assert [cluster.article_ids for cluster in clusters] == [["a", "b"], ["c", "d"]]
    assert all(cluster.review_state == "pending_review" for cluster in clusters)


def test_cluster_build_marks_oversized_dense_component_for_split() -> None:
    service = _service()
    article_titles = {
        article.article_id: article.title
        for article in [_article("a"), _article("b"), _article("c"), _article("d")]
    }
    request = ClusterMaterializationRequest(topN=12, maxComponentSize=3, weakEdgeThreshold=0.78)
    edges = [
        _edge("a", "b", total_score=0.95, label="exact_duplicate"),
        _edge("a", "c", total_score=0.94, label="exact_duplicate"),
        _edge("a", "d", total_score=0.93, label="exact_duplicate"),
        _edge("b", "c", total_score=0.92, label="exact_duplicate"),
        _edge("b", "d", total_score=0.91, label="exact_duplicate"),
        _edge("c", "d", total_score=0.9, label="exact_duplicate"),
    ]

    clusters = service.build_clusters(article_titles=article_titles, edges=edges, request=request)

    assert len(clusters) == 1
    assert clusters[0].member_count == 4
    assert clusters[0].review_state == "split_required"


def test_cluster_build_splits_oversized_dense_component_by_strong_edges() -> None:
    service = _service()
    article_titles = {
        article.article_id: article.title
        for article in [_article("a"), _article("b"), _article("c"), _article("d")]
    }
    request = ClusterMaterializationRequest(topN=12, maxComponentSize=3, weakEdgeThreshold=0.78)
    edges = [
        _edge("a", "b", total_score=0.95, label="exact_duplicate"),
        _edge("c", "d", total_score=0.94, label="exact_duplicate"),
        _edge(
            "a",
            "c",
            total_score=0.81,
            label="near_duplicate",
            article_embedding_similarity=0.79,
            best_chunk_similarity=0.42,
            title_similarity=0.32,
            metadata_agreement=0.0,
        ),
        _edge(
            "a",
            "d",
            total_score=0.8,
            label="near_duplicate",
            article_embedding_similarity=0.79,
            best_chunk_similarity=0.4,
            title_similarity=0.3,
            metadata_agreement=0.0,
        ),
        _edge(
            "b",
            "c",
            total_score=0.8,
            label="near_duplicate",
            article_embedding_similarity=0.79,
            best_chunk_similarity=0.41,
            title_similarity=0.31,
            metadata_agreement=0.0,
        ),
        _edge(
            "b",
            "d",
            total_score=0.81,
            label="near_duplicate",
            article_embedding_similarity=0.79,
            best_chunk_similarity=0.43,
            title_similarity=0.33,
            metadata_agreement=0.0,
        ),
    ]

    clusters = service.build_clusters(article_titles=article_titles, edges=edges, request=request)

    assert [cluster.article_ids for cluster in clusters] == [["a", "b"], ["c", "d"]]
    assert all(cluster.review_state == "pending_review" for cluster in clusters)


def test_cluster_build_preserves_existing_review_state() -> None:
    request = ClusterMaterializationRequest(topN=12, maxComponentSize=12, weakEdgeThreshold=0.78)
    existing_cluster_id = _cluster_id(["a", "b"])
    service = _service(
        existing_clusters=[
            {
                "cluster_id": existing_cluster_id,
                "article_ids": ["a", "b"],
                "edge_ids": ["edge-a-b"],
                "member_count": 2,
                "review_state": "approved_family",
                "representative_article_id": "a",
                "representative_title": "a",
                "memberships": [],
                "thresholds": request.model_dump(by_alias=False),
                "materialized_at": "2026-04-28T12:00:00Z",
            }
        ]
    )
    article_titles = {article.article_id: article.title for article in [_article("a"), _article("b")]}
    edges = [_edge("a", "b", total_score=0.91, label="exact_duplicate")]

    clusters = service.build_clusters(article_titles=article_titles, edges=edges, request=request)

    assert clusters[0].cluster_id == existing_cluster_id
    assert clusters[0].review_state == "approved_family"
