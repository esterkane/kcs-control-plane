from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.admin_jobs import JobRunResponse, JobStartResponse, get_admin_job_manager
from app.admin_status import AdminIndexStatusResponse, get_admin_index_status
from app.config import IngestRequest, IngestSummary
from app.ingestion.kb import ingest_kb_articles


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/ingest/kb", response_model=IngestSummary)
def ingest_kb(request: IngestRequest | None = None) -> IngestSummary:
    return ingest_kb_articles(full=(request.full if request is not None else True))


@router.post("/workflows/full-refresh", response_model=JobStartResponse)
def start_full_refresh() -> JobStartResponse:
    return get_admin_job_manager().start_full_refresh()


@router.get("/jobs/{job_id}", response_model=JobRunResponse)
def get_job(job_id: str) -> JobRunResponse:
    job = get_admin_job_manager().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.get("/jobs", response_model=list[JobRunResponse])
def list_jobs(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[JobRunResponse]:
    return get_admin_job_manager().list_jobs(kind=kind, status=status)


@router.get("/index-status", response_model=AdminIndexStatusResponse)
def get_index_status() -> AdminIndexStatusResponse:
    return get_admin_index_status()


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: str) -> StreamingResponse:
    if get_admin_job_manager().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return StreamingResponse(
        get_admin_job_manager().iter_sse(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
