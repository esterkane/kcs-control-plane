from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Callable, Iterator
from uuid import uuid4

from pydantic import BaseModel, Field

from app.admin_status import get_admin_index_status
from app.backfill.duplicate_embeddings import (
    backfill_article_embeddings_from_env,
    backfill_chunk_embeddings_from_env,
)
from app.clustering.service import build_duplicate_cluster_service
from app.config import ClusterMaterializationRequest
from app.ingestion.kb import ingest_kb_articles


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JobLogEntry(BaseModel):
    sequence: int
    level: str
    message: str
    timestamp: str


class JobRunResponse(BaseModel):
    job_id: str = Field(alias="jobId")
    kind: str
    status: str
    started_at: str = Field(alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    logs: list[JobLogEntry]

    model_config = {"populate_by_name": True}


class JobStartResponse(BaseModel):
    job_id: str = Field(alias="jobId")
    kind: str
    status: str
    reused_existing_job: bool = Field(alias="reusedExistingJob")

    model_config = {"populate_by_name": True}


@dataclass
class JobState:
    job_id: str
    kind: str
    status: str
    started_at: str
    completed_at: str | None = None
    logs: list[JobLogEntry] = field(default_factory=list)
    next_sequence: count = field(default_factory=lambda: count(1))

    def as_response(self) -> JobRunResponse:
        return JobRunResponse(
            jobId=self.job_id,
            kind=self.kind,
            status=self.status,
            startedAt=self.started_at,
            completedAt=self.completed_at,
            logs=self.logs,
        )


class AdminJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}
        self._workers: dict[str, threading.Thread] = {}

    def _append_log(self, job_id: str, *, level: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(
                JobLogEntry(
                    sequence=next(job.next_sequence),
                    level=level,
                    message=message,
                    timestamp=_now_iso(),
                )
            )

    def _set_status(self, job_id: str, *, status: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            if status in {"succeeded", "failed"}:
                job.completed_at = _now_iso()

    def _status_for_job(self, job_id: str) -> str | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.status if job is not None else None

    def _determine_resume_step_from_index_status(self) -> tuple[int, str | None]:
        status = get_admin_index_status()
        total_documents = status.article_index.total_documents
        if total_documents == 0:
            return 1, None
        target_chunk_articles = status.article_index.unique_article_ids or total_documents

        coverage = {item.field_name: item.present_count for item in status.article_index.coverage}
        summary_count = coverage.get("summary", 0)
        compare_text_count = coverage.get("compare_text", 0)
        title_embedding_count = coverage.get("duplicate_title_embedding", 0)
        summary_embedding_count = coverage.get("duplicate_summary_embedding", 0)
        body_embedding_count = coverage.get("duplicate_body_embedding", 0)
        comparison_embedding_count = coverage.get("duplicate_comparison_embedding", 0)

        article_embeddings_complete = (
            compare_text_count > 0
            and title_embedding_count >= compare_text_count
            and body_embedding_count >= compare_text_count
            and comparison_embedding_count >= compare_text_count
            and summary_embedding_count >= summary_count
        )
        chunk_build_complete = (
            status.chunk_index.total_documents > 0
            and status.chunk_index.missing_embeddings == 0
            and status.chunk_index.chunked_articles >= target_chunk_articles
        )

        if compare_text_count > 0 and not article_embeddings_complete:
            return 2, "Resuming from Step 2/4 using persisted article embedding progress."

        if not chunk_build_complete:
            return 3, "Resuming from Step 3/4 using persisted article embedding progress."

        if article_embeddings_complete:
            return 4, "Resuming from Step 4/4 using persisted embedding progress."

        return 1, None

    def _determine_resume_step(self) -> tuple[int, str | None]:
        with self._lock:
            completed_jobs = [
                job
                for job in self._jobs.values()
                if job.kind == "full_kb_refresh" and job.status in {"failed", "succeeded"}
            ]

        if not completed_jobs:
            return self._determine_resume_step_from_index_status()

        latest = max(completed_jobs, key=lambda job: (job.started_at, job.job_id))
        if latest.status != "failed":
            return self._determine_resume_step_from_index_status()

        messages = [entry.message for entry in latest.logs]
        if any(message.startswith("Chunk embeddings complete:") for message in messages):
            return 4, f"Resuming after previous failure from Step 4/4 using saved progress from {latest.job_id}."
        if any(message.startswith("Article embeddings complete:") for message in messages):
            return 3, f"Resuming after previous failure from Step 3/4 using saved progress from {latest.job_id}."
        if any(message.startswith("Ingestion complete:") for message in messages):
            return 2, f"Resuming after previous failure from Step 2/4 using saved progress from {latest.job_id}."
        return self._determine_resume_step_from_index_status()

    def _run_full_refresh(self, job_id: str, *, start_step: int = 1) -> None:
        try:
            self._append_log(job_id, level="info", message="Starting full KB refresh pipeline.")
            if start_step > 1:
                self._append_log(
                    job_id,
                    level="info",
                    message=f"Resuming full KB refresh from Step {start_step}/4. Previously indexed calculations will be reused.",
                )
            index_status = get_admin_index_status()

            if start_step <= 1:
                self._append_log(job_id, level="info", message="Step 1/4: Ingesting remote KB articles.")
                ingest_summary = ingest_kb_articles(full=True)
                self._append_log(
                    job_id,
                    level="info",
                    message=(
                        "Ingestion complete: "
                        f"fetched={ingest_summary.fetched_documents}, "
                        f"indexed={ingest_summary.indexed_documents}, "
                        f"skipped={ingest_summary.skipped_documents}."
                    ),
                )
            else:
                self._append_log(
                    job_id,
                    level="info",
                    message=(
                        "Skipping Step 1/4: Reusing previously ingested KB articles. "
                        f"current_total={index_status.article_index.total_documents}."
                    ),
                )

            if start_step <= 2:
                self._append_log(job_id, level="info", message="Step 2/4: Backfilling article embeddings.")
                article_stats = backfill_article_embeddings_from_env()
                self._append_log(
                    job_id,
                    level="info",
                    message=(
                        "Article embeddings complete: "
                        f"scanned={article_stats.scanned_articles}, "
                        f"updated={article_stats.updated_articles}, "
                        f"skipped={article_stats.skipped_articles}."
                    ),
                )
            else:
                self._append_log(job_id, level="info", message="Skipping Step 2/4: Reusing previously embedded articles.")

            if start_step <= 3:
                self._append_log(job_id, level="info", message="Step 3/4: Backfilling chunk embeddings.")
                chunk_stats = backfill_chunk_embeddings_from_env()
                self._append_log(
                    job_id,
                    level="info",
                    message=(
                        "Chunk embeddings complete: "
                        f"scanned={chunk_stats.scanned_articles}, "
                        f"updated_chunks={chunk_stats.updated_chunks}, "
                        f"skipped={chunk_stats.skipped_articles}."
                    ),
                )
            else:
                self._append_log(job_id, level="info", message="Skipping Step 3/4: Reusing previously embedded chunks.")

            self._append_log(job_id, level="info", message="Step 4/4: Materializing duplicate families.")
            cluster_summary = build_duplicate_cluster_service().materialize(
                ClusterMaterializationRequest(),
                progress_callback=lambda message: self._append_log(job_id, level="info", message=message),
                resume_from_persisted_edges=start_step > 3,
            )
            self._append_log(
                job_id,
                level="info",
                message=(
                    "Cluster materialization complete: "
                    f"source_articles={cluster_summary.source_article_count}, "
                    f"accepted_edges={cluster_summary.accepted_edge_count}, "
                    f"clusters={cluster_summary.cluster_count}."
                ),
            )
            self._append_log(job_id, level="info", message="Full KB refresh pipeline finished successfully.")
            self._set_status(job_id, status="succeeded")
        except Exception as exc:
            self._append_log(job_id, level="error", message=f"Pipeline failed: {exc}")
            self._set_status(job_id, status="failed")

    def start_full_refresh(self) -> JobStartResponse:
        with self._lock:
            for job in self._jobs.values():
                if job.kind == "full_kb_refresh" and job.status in {"queued", "running"}:
                    return JobStartResponse(
                        jobId=job.job_id,
                        kind=job.kind,
                        status=job.status,
                        reusedExistingJob=True,
                    )

            job_id = f"job-{uuid4().hex[:12]}"
            job = JobState(
                job_id=job_id,
                kind="full_kb_refresh",
                status="queued",
                started_at=_now_iso(),
            )
            self._jobs[job_id] = job

        start_step, resume_message = self._determine_resume_step()
        if resume_message is not None:
            self._append_log(job_id, level="info", message=resume_message)

        worker = threading.Thread(
            target=self._run_job_thread,
            args=(job_id, lambda current_job_id: self._run_full_refresh(current_job_id, start_step=start_step)),
            daemon=True,
        )
        with self._lock:
            self._workers[job_id] = worker
        worker.start()
        return JobStartResponse(
            jobId=job_id,
            kind=job.kind,
            status=job.status,
            reusedExistingJob=False,
        )

    def _run_job_thread(self, job_id: str, runner: Callable[[str], None]) -> None:
        self._set_status(job_id, status="running")
        try:
            runner(job_id)
        except BaseException as exc:
            if self._status_for_job(job_id) == "running":
                self._append_log(job_id, level="error", message=f"Pipeline failed: {exc}")
                self._set_status(job_id, status="failed")
        finally:
            with self._lock:
                self._workers.pop(job_id, None)
            if self._status_for_job(job_id) == "running":
                self._append_log(
                    job_id,
                    level="error",
                    message="Pipeline failed: background job exited without reporting a terminal status.",
                )
                self._set_status(job_id, status="failed")

    def get_job(self, job_id: str) -> JobRunResponse | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.as_response()

    def list_jobs(self, *, kind: str | None = None, status: str | None = None) -> list[JobRunResponse]:
        with self._lock:
            jobs = list(self._jobs.values())

        if kind is not None:
            jobs = [job for job in jobs if job.kind == kind]
        if status is not None:
            jobs = [job for job in jobs if job.status == status]

        jobs.sort(key=lambda job: (job.started_at, job.job_id), reverse=True)
        return [job.as_response() for job in jobs]

    def iter_sse(self, job_id: str) -> Iterator[str]:
        next_sequence = 1
        while True:
            snapshot = self.get_job(job_id)
            if snapshot is None:
                payload = json.dumps({"type": "error", "message": f"Job not found: {job_id}"})
                yield f"data: {payload}\n\n"
                break

            for entry in snapshot.logs:
                if entry.sequence < next_sequence:
                    continue
                payload = json.dumps(
                    {
                        "type": "log",
                        "jobId": snapshot.job_id,
                        "status": snapshot.status,
                        "entry": entry.model_dump(),
                    }
                )
                yield f"data: {payload}\n\n"
                next_sequence = entry.sequence + 1

            if snapshot.status in {"succeeded", "failed"}:
                payload = json.dumps(
                    {
                        "type": "status",
                        "jobId": snapshot.job_id,
                        "status": snapshot.status,
                        "completedAt": snapshot.completed_at,
                    }
                )
                yield f"data: {payload}\n\n"
                break

            yield ": heartbeat\n\n"
            time.sleep(0.5)


_manager = AdminJobManager()


def get_admin_job_manager() -> AdminJobManager:
    return _manager
