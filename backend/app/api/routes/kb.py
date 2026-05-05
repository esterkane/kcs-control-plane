from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import ExplanationRequest
from app.explanations.service import PairExplanationResponse, build_explanation_service
from app.similarity.service import SimilarSearchRequest, SimilarSearchResponse, build_similarity_service


router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/articles/{article_id}/similar", response_model=SimilarSearchResponse)
def similar_articles_for_article(
    article_id: str,
    include_cve: bool = Query(default=False, alias="include_cve"),
    include_chunk_seed: bool = Query(default=True, alias="include_chunk_seed"),
    limit: int = Query(default=10, ge=1, le=50),
) -> SimilarSearchResponse:
    service = build_similarity_service()
    try:
        return service.search(
            SimilarSearchRequest(
                articleId=article_id,
                includeCve=include_cve,
                includeChunkSeed=include_chunk_seed,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/similar/search", response_model=SimilarSearchResponse)
def similar_articles_search(request: SimilarSearchRequest) -> SimilarSearchResponse:
    service = build_similarity_service()
    try:
        return service.search(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/pairs/{pair_id}/explain", response_model=PairExplanationResponse)
def explain_pair(pair_id: str, request: ExplanationRequest | None = None) -> PairExplanationResponse:
    service = build_explanation_service()
    try:
        return service.explain_pair(pair_id, request or ExplanationRequest())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
