from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.clustering.service import (
    ClusterDetailResponse,
    ClusterListResponse,
    ClusterMaterializationSummary,
    ClusterSummaryItem,
    build_duplicate_cluster_service,
)
from app.config import ClusterMaterializationRequest, ClusterReviewUpdateRequest, ExplanationRequest
from app.explanations.service import ClusterSummaryResponse, build_explanation_service


router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/clusters", response_model=ClusterListResponse)
def list_clusters(
    size: int = Query(default=20, ge=1, le=100),
) -> ClusterListResponse:
    service = build_duplicate_cluster_service()
    return service.list_clusters(size=size)


@router.get("/clusters/{cluster_id}", response_model=ClusterDetailResponse)
def get_cluster(cluster_id: str) -> ClusterDetailResponse:
    service = build_duplicate_cluster_service()
    cluster = service.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"Cluster not found: {cluster_id}")
    return cluster


@router.patch("/clusters/{cluster_id}", response_model=ClusterDetailResponse)
def update_cluster(cluster_id: str, request: ClusterReviewUpdateRequest) -> ClusterDetailResponse:
    service = build_duplicate_cluster_service()
    try:
        cluster = service.update_cluster_review_state(cluster_id=cluster_id, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"Cluster not found: {cluster_id}")
    return cluster


@router.get("/articles/{article_id}/cluster", response_model=ClusterSummaryItem)
def get_cluster_for_article(article_id: str) -> ClusterSummaryItem:
    service = build_duplicate_cluster_service()
    cluster = service.get_cluster_for_article(article_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"No cluster found for article: {article_id}")
    return cluster


@router.post("/clusters/materialize", response_model=ClusterMaterializationSummary)
def materialize_clusters(
    request: ClusterMaterializationRequest | None = None,
) -> ClusterMaterializationSummary:
    service = build_duplicate_cluster_service()
    return service.materialize(request or ClusterMaterializationRequest())


@router.post("/clusters/{cluster_id}/summarize", response_model=ClusterSummaryResponse)
def summarize_cluster(
    cluster_id: str,
    request: ExplanationRequest | None = None,
) -> ClusterSummaryResponse:
    service = build_explanation_service()
    try:
        return service.summarize_cluster(cluster_id, request or ExplanationRequest())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
