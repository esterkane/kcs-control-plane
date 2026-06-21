"""Unit tests for the read-only MCP tool implementations.

The tools are exercised directly (no FastMCP / HTTP, no live Elasticsearch)
against fake services, mirroring the mock-based style of the existing API tests
(``test_cluster_api.py`` / ``test_similarity_api.py``).
"""

from __future__ import annotations

import pytest

from app.clustering.service import ClusterDetailResponse, ClusterListResponse
from app.elasticsearch.client import ElasticsearchClientError
from app.mcp.tools import (
    find_similar_impl,
    get_cluster_impl,
    list_review_queue_impl,
)
from app.similarity.service import SimilarSearchResponse


# --- fixtures: canned responses in the same shape the HTTP API returns ----------


def _similar_response() -> SimilarSearchResponse:
    return SimilarSearchResponse.model_validate(
        {
            "queryArticleId": "article-1",
            "candidateCount": 1,
            "candidates": [
                {
                    "articleId": "article-2",
                    "label": "near_duplicate",
                    "title": "Article 2",
                    "summary": "Candidate summary",
                    "pairScores": {
                        "rrfScore": 0.1,
                        "articleEmbeddingSimilarity": 0.8,
                        "bestChunkSimilarity": 0.6,
                        "titleSimilarity": 0.7,
                        "summarySimilarity": 0.6,
                        "metadataAgreement": 0.5,
                        "rerankScore": 0.7,
                        "totalScore": 0.8,
                    },
                    "evidence": {
                        "sharedMetadata": {"products": ["Cloud"]},
                        "mostSimilarChunks": [],
                        "reasons": ["shared_metadata"],
                    },
                }
            ],
        }
    )


def _cluster_detail() -> ClusterDetailResponse:
    return ClusterDetailResponse.model_validate(
        {
            "clusterId": "family-1",
            "articleIds": ["a", "b"],
            "edgeIds": ["edge-1"],
            "memberCount": 2,
            "reviewState": "pending_review",
            "representativeArticleId": "a",
            "representativeTitle": "Article A",
            "memberships": [
                {
                    "articleId": "a",
                    "title": "Article A",
                    "supportingEdgeIds": ["edge-1"],
                    "reasons": ["shared_metadata"],
                    "sharedMetadata": {"products": ["Cloud"]},
                }
            ],
            "thresholds": {
                "topN": 12,
                "includeCve": False,
                "includeChunkSeed": True,
                "maxComponentSize": 12,
                "weakEdgeThreshold": 0.78,
                "analysisMode": "graph",
            },
            "materializedAt": "2026-04-28T12:00:00Z",
            "edges": [
                {
                    "edgeId": "edge-1",
                    "leftArticleId": "a",
                    "rightArticleId": "b",
                    "label": "exact_duplicate",
                    "accepted": True,
                    "totalScore": 0.94,
                    "pairScores": {
                        "rrfScore": 0.1,
                        "articleEmbeddingSimilarity": 0.9,
                        "bestChunkSimilarity": 0.8,
                        "titleSimilarity": 0.9,
                        "summarySimilarity": 0.0,
                        "metadataAgreement": 1.0,
                        "rerankScore": 0.9,
                        "totalScore": 0.94,
                    },
                    "evidence": {
                        "sharedMetadata": {"products": ["Cloud"]},
                        "mostSimilarChunks": [],
                        "reasons": ["shared_metadata"],
                    },
                    "sourceQueryArticleId": "a",
                    "sourceCandidateArticleId": "b",
                    "materializedAt": "2026-04-28T12:00:00Z",
                }
            ],
        }
    )


def _cluster_list(state: str) -> ClusterListResponse:
    return ClusterListResponse.model_validate(
        {
            "count": 1,
            "page": 1,
            "pageSize": 20,
            "totalPages": 1,
            "items": [
                {
                    "clusterId": "family-1",
                    "articleIds": ["a", "b"],
                    "memberCount": 2,
                    "reviewState": state,
                    "representativeArticleId": "a",
                    "representativeTitle": "Article A",
                }
            ],
        }
    )


# --- fakes ----------------------------------------------------------------------


class FakeSimilarityService:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list = []

    def search(self, request):
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return self._response


class FakeClusterService:
    def __init__(self, *, cluster=None, listing=None, error: Exception | None = None) -> None:
        self._cluster = cluster
        self._listing = listing
        self._error = error
        self.list_calls: list = []

    def get_cluster(self, cluster_id: str):
        if self._error is not None:
            raise self._error
        return self._cluster if cluster_id == "family-1" else None

    def list_clusters(self, *, size: int = 20, page: int = 1, review_state: str | None = None):
        self.list_calls.append({"size": size, "page": page, "review_state": review_state})
        if self._error is not None:
            raise self._error
        return self._listing


# --- find_similar ---------------------------------------------------------------


def test_find_similar_success_shape() -> None:
    service = FakeSimilarityService(response=_similar_response())

    result = find_similar_impl("article-1", service=service, limit=5)

    assert "isError" not in result
    assert result["queryArticleId"] == "article-1"
    assert result["candidateCount"] == 1
    assert result["candidates"][0]["articleId"] == "article-2"
    # camelCase contract preserved (by_alias dump).
    assert "pairScores" in result["candidates"][0]
    # request was built with the right limit.
    assert service.calls[0].limit == 5


def test_find_similar_unknown_article_is_business_error() -> None:
    service = FakeSimilarityService(error=ValueError("Article not found: ghost"))

    result = find_similar_impl("ghost", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False
    assert "not found" in result["message"].casefold()


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_find_similar_empty_id_is_validation_error(bad_id: str) -> None:
    service = FakeSimilarityService(response=_similar_response())

    result = find_similar_impl(bad_id, service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False
    # service must not be called on a validation failure.
    assert service.calls == []


def test_find_similar_limit_out_of_range_is_validation_error() -> None:
    service = FakeSimilarityService(response=_similar_response())

    result = find_similar_impl("article-1", service=service, limit=999)

    assert result["isError"] is True
    assert result["errorCategory"] == "validation"


def test_find_similar_backend_error_is_transient() -> None:
    service = FakeSimilarityService(error=ElasticsearchClientError("boom"))

    result = find_similar_impl("article-1", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "transient"
    assert result["isRetryable"] is True
    # no stack trace / internal detail leaks.
    assert "boom" not in result["message"]


# --- get_cluster ----------------------------------------------------------------


def test_get_cluster_success_shape() -> None:
    service = FakeClusterService(cluster=_cluster_detail())

    result = get_cluster_impl("family-1", service=service)

    assert "isError" not in result
    assert result["clusterId"] == "family-1"
    assert result["reviewState"] == "pending_review"
    assert result["edges"][0]["edgeId"] == "edge-1"
    # evidence/provenance preserved.
    assert result["edges"][0]["evidence"]["reasons"] == ["shared_metadata"]


def test_get_cluster_unknown_id_is_business_error() -> None:
    service = FakeClusterService(cluster=_cluster_detail())

    result = get_cluster_impl("does-not-exist", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False


def test_get_cluster_empty_id_is_validation_error() -> None:
    service = FakeClusterService(cluster=_cluster_detail())

    result = get_cluster_impl("  ", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "validation"


def test_get_cluster_backend_error_is_transient() -> None:
    service = FakeClusterService(error=ElasticsearchClientError("es down"))

    result = get_cluster_impl("family-1", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "transient"
    assert result["isRetryable"] is True


# --- list_review_queue ----------------------------------------------------------


def test_list_review_queue_success_shape_and_filter_passthrough() -> None:
    service = FakeClusterService(listing=_cluster_list("pending_review"))

    result = list_review_queue_impl("pending_review", service=service, size=20, page=1)

    assert "isError" not in result
    assert result["count"] == 1
    assert result["items"][0]["reviewState"] == "pending_review"
    # the review_state filter is forwarded to the existing service method.
    assert service.list_calls[0]["review_state"] == "pending_review"


def test_list_review_queue_empty_is_not_an_error() -> None:
    empty = ClusterListResponse.model_validate(
        {"count": 0, "page": 1, "pageSize": 20, "totalPages": 1, "items": []}
    )
    service = FakeClusterService(listing=empty)

    result = list_review_queue_impl("approved_family", service=service)

    assert "isError" not in result
    assert result["count"] == 0
    assert result["items"] == []


def test_list_review_queue_unknown_state_is_validation_error() -> None:
    service = FakeClusterService(listing=_cluster_list("pending_review"))

    result = list_review_queue_impl("not_a_state", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "validation"
    # service must not be called on a validation failure.
    assert service.list_calls == []


def test_list_review_queue_backend_error_is_transient() -> None:
    service = FakeClusterService(error=ElasticsearchClientError("es down"))

    result = list_review_queue_impl("pending_review", service=service)

    assert result["isError"] is True
    assert result["errorCategory"] == "transient"
    assert result["isRetryable"] is True
