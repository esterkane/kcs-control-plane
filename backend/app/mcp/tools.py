"""MCP tool handlers wrapping the duplicate-detection / cluster-review core.

These are plain, importable functions — no FastMCP or HTTP coupling — so they can
be unit-tested directly with fake services. ``app/mcp/server.py`` registers thin
FastMCP wrappers that supply the real service singletons.

Every handler is wrapped by :func:`app.mcp.errors.guard`, so it either returns a
structured success payload or a structured error payload — never a raised
exception or a stack trace.

The handlers are thin adapters: they validate inputs, call the existing service
methods, and shape the result into a JSON-serialisable dict that mirrors the
shape the HTTP API returns (the same pydantic models, dumped with ``by_alias`` so
the camelCase contract matches). No similarity/cluster business logic lives here.

All three tools are READ-ONLY. No mutation of review state, no ingestion, no
publish.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.clustering.service import ClusterDetailResponse, ClusterListResponse
from app.config import ClusterReviewUpdateRequest  # noqa: F401  (imported for type docs only)
from app.mcp.errors import ToolBusinessError, ToolValidationError, guard
from app.similarity.service import SimilarSearchRequest, SimilarSearchResponse

# Review states the review-queue tool accepts (mirrors the cluster service literal).
VALID_REVIEW_STATES = (
    "pending_review",
    "approved_family",
    "rejected_family",
    "split_required",
)
MAX_SIMILAR_LIMIT = 50
MAX_QUEUE_SIZE = 100


class SimilarityServiceLike(Protocol):
    def search(self, request: SimilarSearchRequest) -> SimilarSearchResponse: ...


class ClusterServiceLike(Protocol):
    def get_cluster(self, cluster_id: str) -> ClusterDetailResponse | None: ...

    def list_clusters(
        self, *, size: int = ..., page: int = ..., review_state: str | None = ...
    ) -> ClusterListResponse: ...


def _require_nonempty_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"`{field}` must be a non-empty string.")
    return value.strip()


def _require_int_in_range(value: int, *, field: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
        raise ToolValidationError(
            f"`{field}` must be an integer between {low} and {high}.", details={field: value}
        )
    return value


@guard("find_similar")
def find_similar_impl(
    article_id: str,
    *,
    service: SimilarityServiceLike,
    include_cve: bool = False,
    include_chunk_seed: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    """Find likely duplicate / near-duplicate articles for an existing article.

    Thin adapter over ``SimilarArticleService.search``. Returns the same shape as
    ``GET /kb/articles/{article_id}/similar`` (a ``SimilarSearchResponse``). An
    unknown article id is surfaced as a business error rather than a crash.
    """
    article_id = _require_nonempty_id(article_id, field="article_id")
    _require_int_in_range(limit, field="limit", low=1, high=MAX_SIMILAR_LIMIT)
    if not isinstance(include_cve, bool):
        raise ToolValidationError("`include_cve` must be a boolean.", details={"include_cve": include_cve})
    if not isinstance(include_chunk_seed, bool):
        raise ToolValidationError(
            "`include_chunk_seed` must be a boolean.", details={"include_chunk_seed": include_chunk_seed}
        )

    try:
        response = service.search(
            SimilarSearchRequest(
                articleId=article_id,
                includeCve=include_cve,
                includeChunkSeed=include_chunk_seed,
                limit=limit,
            )
        )
    except ValueError as exc:
        # The similarity service raises ValueError("Article not found: ...") for an
        # unknown id — the HTTP route maps this to 404; here it is a business error.
        raise ToolBusinessError(str(exc), details={"articleId": article_id}) from exc

    return response.model_dump(by_alias=True)


@guard("get_cluster")
def get_cluster_impl(
    cluster_id: str,
    *,
    service: ClusterServiceLike,
) -> dict[str, Any]:
    """Fetch a persisted duplicate cluster and its supporting edges by id.

    Thin adapter over ``DuplicateClusterService.get_cluster``. Returns the same
    shape as ``GET /kb/clusters/{cluster_id}`` (a ``ClusterDetailResponse``,
    including memberships, thresholds, and supporting edges with evidence). An
    unknown cluster id is surfaced as a business error rather than a 404/None.
    """
    cluster_id = _require_nonempty_id(cluster_id, field="cluster_id")
    cluster = service.get_cluster(cluster_id)
    if cluster is None:
        raise ToolBusinessError(
            f"Cluster not found: {cluster_id}", details={"clusterId": cluster_id}
        )
    return cluster.model_dump(by_alias=True)


@guard("list_review_queue")
def list_review_queue_impl(
    state: str,
    *,
    service: ClusterServiceLike,
    size: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """List persisted clusters in a given review state (the review queue).

    Thin adapter over ``DuplicateClusterService.list_clusters`` with a
    ``review_state`` filter (the same method the ``GET /kb/clusters?reviewState=``
    route uses). Returns the same shape as that route (a ``ClusterListResponse``
    of cluster summaries). An empty queue is a normal, non-error result
    (``count == 0``, ``items == []``).
    """
    if not isinstance(state, str) or state not in VALID_REVIEW_STATES:
        raise ToolValidationError(
            f"`state` must be one of {VALID_REVIEW_STATES}.", details={"state": state}
        )
    _require_int_in_range(size, field="size", low=1, high=MAX_QUEUE_SIZE)
    _require_int_in_range(page, field="page", low=1, high=10000)

    response = service.list_clusters(size=size, page=page, review_state=state)
    return response.model_dump(by_alias=True)
