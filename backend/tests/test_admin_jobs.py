from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.admin_jobs import AdminJobManager, JobLogEntry, JobState
from app.main import app


client = TestClient(app)


def test_start_full_refresh_endpoint(monkeypatch) -> None:
    class FakeManager:
        def start_full_refresh(self):
            return {
                "jobId": "job-123",
                "kind": "full_kb_refresh",
                "status": "queued",
                "reusedExistingJob": False,
            }

    monkeypatch.setattr("app.api.routes.admin.get_admin_job_manager", lambda: FakeManager())

    response = client.post("/admin/workflows/full-refresh")

    assert response.status_code == 200
    assert response.json()["jobId"] == "job-123"


def test_get_job_endpoint(monkeypatch) -> None:
    class FakeManager:
        def get_job(self, job_id: str):
            return {
                "jobId": job_id,
                "kind": "full_kb_refresh",
                "status": "running",
                "startedAt": "2026-04-28T12:00:00Z",
                "completedAt": None,
                "logs": [],
            }

    monkeypatch.setattr("app.api.routes.admin.get_admin_job_manager", lambda: FakeManager())

    response = client.get("/admin/jobs/job-123")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_list_jobs_endpoint_filters_running_full_refresh_jobs(monkeypatch) -> None:
    class FakeManager:
        def list_jobs(self, *, kind: str | None = None, status: str | None = None):
            assert kind == "full_kb_refresh"
            assert status == "running"
            return [
                {
                    "jobId": "job-123",
                    "kind": "full_kb_refresh",
                    "status": "running",
                    "startedAt": "2026-04-28T12:00:00Z",
                    "completedAt": None,
                    "logs": [],
                }
            ]

    monkeypatch.setattr("app.api.routes.admin.get_admin_job_manager", lambda: FakeManager())

    response = client.get("/admin/jobs?kind=full_kb_refresh&status=running")

    assert response.status_code == 200
    assert response.json()[0]["jobId"] == "job-123"


def test_get_index_status_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.admin.get_admin_index_status",
        lambda: {
                "articleIndex": {
                    "indexName": "kcs-kb-articles-v1",
                    "totalDocuments": 18397,
                    "uniqueArticleIds": 18397,
                    "coverage": [
                    {
                        "fieldName": "title",
                        "presentCount": 18397,
                        "missingCount": 0,
                        "percentage": 100.0,
                    }
                ],
            },
            "chunkIndex": {
                "indexName": "kcs-kb-article-chunks-v1",
                "totalDocuments": 3183,
                "embeddedDocuments": 3183,
                "missingEmbeddings": 0,
                "embeddingPercentage": 100.0,
                "chunkedArticles": 100,
                "missingArticles": 18297,
                "articleCoveragePercentage": 0.5,
            },
        },
    )

    response = client.get("/admin/index-status")

    assert response.status_code == 200
    assert response.json()["articleIndex"]["indexName"] == "kcs-kb-articles-v1"
    assert response.json()["chunkIndex"]["embeddingPercentage"] == 100.0


def test_stream_job_endpoint(monkeypatch) -> None:
    class FakeManager:
        def get_job(self, job_id: str):
            return {
                "jobId": job_id,
                "kind": "full_kb_refresh",
                "status": "running",
                "startedAt": "2026-04-28T12:00:00Z",
                "completedAt": None,
                "logs": [],
            }

        def iter_sse(self, job_id: str):
            payload = json.dumps(
                {
                    "type": "log",
                    "jobId": job_id,
                    "status": "running",
                    "entry": {
                        "sequence": 1,
                        "level": "info",
                        "message": "Starting full KB refresh pipeline.",
                        "timestamp": "2026-04-28T12:00:00Z",
                    },
                }
            )
            yield f"data: {payload}\n\n"

    monkeypatch.setattr("app.api.routes.admin.get_admin_job_manager", lambda: FakeManager())

    with client.stream("GET", "/admin/jobs/job-123/stream") as response:
        body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert "Starting full KB refresh pipeline." in body


def test_admin_job_manager_reuses_existing_running_job(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.admin_jobs.get_admin_index_status",
        lambda: type(
            "Status",
            (),
            {
                "article_index": type("ArticleIndex", (), {"total_documents": 0, "coverage": []})(),
                "chunk_index": type(
                    "ChunkIndex",
                    (),
                    {"missing_embeddings": 0, "total_documents": 0, "chunked_articles": 0},
                )(),
            },
        )(),
    )
    manager = AdminJobManager()
    first = manager.start_full_refresh()
    second = manager.start_full_refresh()

    assert first.job_id == second.job_id
    assert second.reused_existing_job is True


def test_admin_job_manager_lists_jobs_newest_first() -> None:
    manager = AdminJobManager()
    manager._jobs = {
        "job-older": JobState(
            job_id="job-older",
            kind="full_kb_refresh",
            status="succeeded",
            started_at="2026-04-28T12:00:00Z",
        ),
        "job-newer": JobState(
            job_id="job-newer",
            kind="full_kb_refresh",
            status="running",
            started_at="2026-04-28T12:05:00Z",
        ),
        "job-other-kind": JobState(
            job_id="job-other-kind",
            kind="other_job",
            status="running",
            started_at="2026-04-28T12:10:00Z",
        ),
    }

    jobs = manager.list_jobs(kind="full_kb_refresh", status="running")

    assert [job.job_id for job in jobs] == ["job-newer"]


def test_admin_job_manager_resumes_from_step_two_after_failed_ingestion_complete(monkeypatch) -> None:
    manager = AdminJobManager()
    failed = JobState(
        job_id="job-failed",
        kind="full_kb_refresh",
        status="failed",
        started_at="2026-04-30T12:00:00Z",
    )
    failed.logs = [
        JobLogEntry(sequence=1, level="info", message="Step 1/4: Ingesting remote KB articles.", timestamp="2026-04-30T12:00:00Z"),
        JobLogEntry(sequence=2, level="info", message="Ingestion complete: fetched=10, indexed=10, skipped=0.", timestamp="2026-04-30T12:00:10Z"),
    ]
    manager._jobs = {"job-failed": failed}

    start_step, message = manager._determine_resume_step()

    assert start_step == 2
    assert message is not None
    assert "Step 2/4" in message


def test_admin_job_manager_marks_job_failed_when_runner_exits_without_terminal_status() -> None:
    manager = AdminJobManager()
    manager._jobs = {
        "job-stale": JobState(
            job_id="job-stale",
            kind="full_kb_refresh",
            status="queued",
            started_at="2026-05-03T10:00:00Z",
        )
    }

    manager._run_job_thread("job-stale", lambda _job_id: None)

    job = manager.get_job("job-stale")
    assert job is not None
    assert job.status == "failed"
    assert any("background job exited without reporting a terminal status" in entry.message for entry in job.logs)


def test_admin_job_manager_marks_job_failed_when_runner_raises_base_exception() -> None:
    manager = AdminJobManager()
    manager._jobs = {
        "job-crash": JobState(
            job_id="job-crash",
            kind="full_kb_refresh",
            status="queued",
            started_at="2026-05-03T10:00:00Z",
        )
    }

    manager._run_job_thread("job-crash", lambda _job_id: (_ for _ in ()).throw(SystemExit("boom")))

    job = manager.get_job("job-crash")
    assert job is not None
    assert job.status == "failed"
    assert any("Pipeline failed: boom" in entry.message for entry in job.logs)


def test_admin_job_manager_starts_from_scratch_when_latest_job_succeeded(monkeypatch) -> None:
    manager = AdminJobManager()
    succeeded = JobState(
        job_id="job-succeeded",
        kind="full_kb_refresh",
        status="succeeded",
        started_at="2026-04-30T12:00:00Z",
    )
    manager._jobs = {"job-succeeded": succeeded}

    monkeypatch.setattr(
        "app.admin_jobs.get_admin_index_status",
        lambda: type(
            "Status",
            (),
            {
                "article_index": type("ArticleIndex", (), {"total_documents": 0, "coverage": []})(),
                "chunk_index": type(
                    "ChunkIndex",
                    (),
                    {"missing_embeddings": 0, "total_documents": 0, "chunked_articles": 0},
                )(),
            },
        )(),
    )

    start_step, message = manager._determine_resume_step()

    assert start_step == 1
    assert message is None


def test_admin_job_manager_uses_index_progress_when_job_history_is_missing(monkeypatch) -> None:
    manager = AdminJobManager()

    monkeypatch.setattr(
        "app.admin_jobs.get_admin_index_status",
        lambda: type(
            "Status",
            (),
            {
                "article_index": type(
                    "ArticleIndex",
                    (),
                    {
                        "total_documents": 100,
                        "unique_article_ids": 100,
                        "coverage": [
                            type("Coverage", (), {"field_name": "compare_text", "present_count": 80})(),
                            type("Coverage", (), {"field_name": "duplicate_title_embedding", "present_count": 60})(),
                            type("Coverage", (), {"field_name": "duplicate_summary_embedding", "present_count": 60})(),
                            type("Coverage", (), {"field_name": "duplicate_body_embedding", "present_count": 60})(),
                            type("Coverage", (), {"field_name": "duplicate_comparison_embedding", "present_count": 60})(),
                        ],
                    },
                )(),
                "chunk_index": type(
                    "ChunkIndex",
                    (),
                    {"missing_embeddings": 0, "total_documents": 10, "chunked_articles": 10},
                )(),
            },
        )(),
    )

    start_step, message = manager._determine_resume_step()

    assert start_step == 2
    assert message is not None
    assert "persisted article embedding progress" in message


def test_admin_job_manager_resumes_from_step_three_when_chunk_index_is_partial(monkeypatch) -> None:
    manager = AdminJobManager()

    monkeypatch.setattr(
        "app.admin_jobs.get_admin_index_status",
        lambda: type(
            "Status",
            (),
            {
                "article_index": type(
                    "ArticleIndex",
                    (),
                    {
                        "total_documents": 100,
                        "unique_article_ids": 25,
                        "coverage": [
                            type("Coverage", (), {"field_name": "summary", "present_count": 95})(),
                            type("Coverage", (), {"field_name": "compare_text", "present_count": 100})(),
                            type("Coverage", (), {"field_name": "duplicate_title_embedding", "present_count": 100})(),
                            type("Coverage", (), {"field_name": "duplicate_summary_embedding", "present_count": 95})(),
                            type("Coverage", (), {"field_name": "duplicate_body_embedding", "present_count": 100})(),
                            type("Coverage", (), {"field_name": "duplicate_comparison_embedding", "present_count": 100})(),
                        ],
                    },
                )(),
                "chunk_index": type(
                    "ChunkIndex",
                    (),
                    {"missing_embeddings": 0, "total_documents": 300, "chunked_articles": 24},
                )(),
            },
        )(),
    )

    start_step, message = manager._determine_resume_step()

    assert start_step == 3
    assert message is not None
    assert "Step 3/4" in message
