from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from app.backfill.duplicate_embeddings import CHUNK_INDEX_MAPPING
from app.clustering.service import CLUSTER_INDEX_MAPPING, EDGE_INDEX_MAPPING
from app.config import (
    AnalysisSyncSummary,
    get_duplicate_embedding_provider,
    get_local_analysis_metadata_index,
    get_remote_analysis_publish_lock_seconds,
    get_remote_analysis_chunk_alias,
    get_remote_analysis_duplicate_cluster_alias,
    get_remote_analysis_duplicate_edge_alias,
    get_remote_analysis_es_api_key,
    get_remote_analysis_es_url,
    get_remote_analysis_metadata_index,
    get_remote_analysis_normalized_alias,
    get_source_es_index,
    get_target_chunk_index,
    get_target_duplicate_cluster_index,
    get_target_duplicate_edge_index,
    get_target_es_index,
    get_target_es_url,
    is_remote_analysis_enabled,
)
from app.elasticsearch.client import ElasticsearchClient, ElasticsearchClientError
from app.ingestion.kb import TARGET_INDEX_MAPPING

ProgressCallback = Callable[[str], None]
PUBLISH_LOCK_DOCUMENT_ID = "publish-lock"

SYNC_METADATA_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "run_id": {"type": "keyword"},
            "job_id": {"type": "keyword"},
            "mode": {"type": "keyword"},
            "published_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "synced_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "embedding_provider": {"type": "keyword"},
            "local_indices": {
                "properties": {
                    "articles": {"type": "keyword"},
                    "chunks": {"type": "keyword"},
                    "edges": {"type": "keyword"},
                    "clusters": {"type": "keyword"},
                }
            },
            "remote_aliases": {
                "properties": {
                    "articles": {"type": "keyword"},
                    "chunks": {"type": "keyword"},
                    "edges": {"type": "keyword"},
                    "clusters": {"type": "keyword"},
                }
            },
            "document_counts": {
                "properties": {
                    "articles": {"type": "integer"},
                    "chunks": {"type": "integer"},
                    "edges": {"type": "integer"},
                    "clusters": {"type": "integer"},
                }
            },
            "lock_holder": {"type": "keyword"},
            "acquired_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "expires_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
        },
    },
}


@dataclass(frozen=True)
class SyncIndexSpec:
    key: str
    local_index: str
    remote_alias: str
    mapping: dict[str, Any]
    source_fields: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mapping_fields(mapping: dict[str, Any]) -> list[str]:
    properties = mapping.get("mappings", {}).get("properties", {})
    if not isinstance(properties, dict):
        return []
    return sorted(field_name for field_name in properties if isinstance(field_name, str))


def _sync_specs() -> list[SyncIndexSpec]:
    return [
        SyncIndexSpec(
            key="articles",
            local_index=get_target_es_index(),
            remote_alias=get_remote_analysis_normalized_alias(),
            mapping=TARGET_INDEX_MAPPING,
            source_fields=_mapping_fields(TARGET_INDEX_MAPPING),
        ),
        SyncIndexSpec(
            key="chunks",
            local_index=get_target_chunk_index(),
            remote_alias=get_remote_analysis_chunk_alias(),
            mapping=CHUNK_INDEX_MAPPING,
            source_fields=_mapping_fields(CHUNK_INDEX_MAPPING),
        ),
        SyncIndexSpec(
            key="edges",
            local_index=get_target_duplicate_edge_index(),
            remote_alias=get_remote_analysis_duplicate_edge_alias(),
            mapping=EDGE_INDEX_MAPPING,
            source_fields=_mapping_fields(EDGE_INDEX_MAPPING),
        ),
        SyncIndexSpec(
            key="clusters",
            local_index=get_target_duplicate_cluster_index(),
            remote_alias=get_remote_analysis_duplicate_cluster_alias(),
            mapping=CLUSTER_INDEX_MAPPING,
            source_fields=_mapping_fields(CLUSTER_INDEX_MAPPING),
        ),
    ]


class RemoteAnalysisSyncService:
    def __init__(
        self,
        *,
        local_client: ElasticsearchClient,
        remote_client: ElasticsearchClient,
    ) -> None:
        self.local_client = local_client
        self.remote_client = remote_client
        self.specs = _sync_specs()
        self.metadata_index = get_remote_analysis_metadata_index()
        self.local_metadata_index = get_local_analysis_metadata_index()

    def _ensure_remote_enabled(self) -> None:
        if not is_remote_analysis_enabled():
            raise ElasticsearchClientError(
                "Remote analysis cluster is not configured. Set REMOTE_ANALYSIS_ES_URL and REMOTE_ANALYSIS_ES_API_KEY."
            )
        source_index = get_source_es_index()
        conflicting_aliases = [
            spec.remote_alias
            for spec in self.specs
            if spec.remote_alias == source_index
        ]
        if conflicting_aliases:
            raise ElasticsearchClientError(
                "Remote analysis aliases must not overlap the source KB index. "
                f"Conflicting aliases: {', '.join(conflicting_aliases)}."
            )

    def _recreate_index(self, client: ElasticsearchClient, *, index: str, mapping: dict[str, Any]) -> None:
        if client.index_exists(index=index):
            client.delete_index(index=index)
        client.create_index(index=index, mapping=mapping)

    def _copy_index(
        self,
        *,
        source_client: ElasticsearchClient,
        source_index: str,
        target_client: ElasticsearchClient,
        target_index: str,
        source_fields: list[str],
        progress_callback: ProgressCallback | None = None,
        progress_label: str,
    ) -> int:
        copied = 0
        for batch in source_client.iterate_document_batches(
            index=source_index,
            page_size=250,
            source_includes=source_fields,
        ):
            target_client.bulk_index(index=target_index, documents=batch)
            copied += len(batch)
            if progress_callback is not None and copied % 1000 == 0:
                progress_callback(f"{progress_label}: copied_documents={copied}.")
        if progress_callback is not None and copied > 0 and copied % 1000 != 0:
            progress_callback(f"{progress_label}: copied_documents={copied}.")
        return copied

    def pull_remote_to_local(self, *, progress_callback: ProgressCallback | None = None) -> AnalysisSyncSummary:
        self._ensure_remote_enabled()
        counts: dict[str, int] = {}
        remote_run_id: str | None = None
        for spec in self.specs:
            if progress_callback is not None:
                progress_callback(
                    "Pulling published remote analysis index: "
                    f"alias={spec.remote_alias} -> local_index={spec.local_index}."
                )
            if not self.remote_client.index_exists(index=spec.remote_alias):
                raise ElasticsearchClientError(
                    f"Remote analysis alias or index is missing: {spec.remote_alias}"
                )
            self._recreate_index(self.local_client, index=spec.local_index, mapping=spec.mapping)
            copied = self._copy_index(
                source_client=self.remote_client,
                source_index=spec.remote_alias,
                target_client=self.local_client,
                target_index=spec.local_index,
                source_fields=spec.source_fields,
                progress_callback=progress_callback,
                progress_label=f"Pull progress for {spec.key}",
            )
            counts[spec.key] = copied
            if progress_callback is not None:
                progress_callback(
                    "Pull complete for index: "
                    f"{spec.key} copied_documents={copied}."
                )
        metadata_document = self._read_latest_remote_metadata()
        if metadata_document is not None:
            remote_run_id = metadata_document.get("run_id") if isinstance(metadata_document.get("run_id"), str) else None
            metadata_document["mode"] = "pull_remote_analysis"
            metadata_document["local_indices"] = {spec.key: spec.local_index for spec in self.specs}
            metadata_document["synced_at"] = _now_iso()
            self._write_local_sync_state(metadata_document)
        return AnalysisSyncSummary(
            mode="pull_remote_analysis",
            remoteRunId=remote_run_id,
            articleDocuments=counts.get("articles", 0),
            chunkDocuments=counts.get("chunks", 0),
            edgeDocuments=counts.get("edges", 0),
            clusterDocuments=counts.get("clusters", 0),
            remoteAliases={spec.key: spec.remote_alias for spec in self.specs},
        )

    def _ensure_metadata_index(self) -> None:
        if self.remote_client.index_exists(index=self.metadata_index):
            self.remote_client.put_mapping(
                index=self.metadata_index,
                mapping={"properties": SYNC_METADATA_MAPPING["mappings"]["properties"]},
            )
            return
        self.remote_client.create_index(index=self.metadata_index, mapping=SYNC_METADATA_MAPPING)

    def _ensure_local_metadata_index(self) -> None:
        if self.local_client.index_exists(index=self.local_metadata_index):
            self.local_client.put_mapping(
                index=self.local_metadata_index,
                mapping={"properties": SYNC_METADATA_MAPPING["mappings"]["properties"]},
            )
            return
        self.local_client.create_index(index=self.local_metadata_index, mapping=SYNC_METADATA_MAPPING)

    def _write_local_sync_state(self, document: dict[str, Any]) -> None:
        self._ensure_local_metadata_index()
        self.local_client.bulk_index(
            index=self.local_metadata_index,
            documents=[("latest", document)],
        )

    def get_active_publish_lock(self) -> dict[str, Any] | None:
        if not self.remote_client.index_exists(index=self.metadata_index):
            return None
        lock_document = self.remote_client.get_document(index=self.metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)
        return dict(lock_document) if isinstance(lock_document, dict) else None

    def _read_latest_remote_metadata(self) -> dict[str, Any] | None:
        if not self.remote_client.index_exists(index=self.metadata_index):
            return None
        hits = self.remote_client.search(
            index=self.metadata_index,
            body={
                "size": 1,
                "sort": [{"published_at": "desc"}],
                "query": {
                    "bool": {
                        "must": [{"term": {"mode": "publish_remote_analysis"}}],
                        "must_not": [{"ids": {"values": [PUBLISH_LOCK_DOCUMENT_ID]}}],
                    }
                },
            },
        )
        if not hits:
            return None
        source = hits[0].get("_source")
        return dict(source) if isinstance(source, dict) else None

    def _read_local_sync_state(self) -> dict[str, Any] | None:
        if not self.local_client.index_exists(index=self.local_metadata_index):
            return None
        hits = self.local_client.search(
            index=self.local_metadata_index,
            body={
                "size": 1,
                "query": {"match_all": {}},
            },
        )
        if not hits:
            return None
        source = hits[0].get("_source")
        return dict(source) if isinstance(source, dict) else None

    def _ensure_publish_freshness(self) -> None:
        latest_remote = self._read_latest_remote_metadata()
        if latest_remote is None:
            return
        latest_run_id = latest_remote.get("run_id")
        if not isinstance(latest_run_id, str) or not latest_run_id:
            return
        local_sync = self._read_local_sync_state()
        if local_sync is None:
            raise ElasticsearchClientError(
                "Local working indices are older than the latest published remote analysis snapshot. "
                "Pull published remote analysis before publishing local calculations."
            )
        local_run_id = local_sync.get("run_id")
        if local_run_id != latest_run_id:
            raise ElasticsearchClientError(
                "Local working indices are stale compared with the latest published remote analysis snapshot. "
                f"Local run={local_run_id!r}, latest remote run={latest_run_id!r}. "
                "Pull published remote analysis before publishing local calculations."
            )

    def _acquire_publish_lock(self, *, run_id: str, job_id: str | None = None) -> None:
        self._ensure_metadata_index()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = now + timedelta(seconds=get_remote_analysis_publish_lock_seconds())
        lock_document = {
            "run_id": run_id,
            "job_id": job_id or run_id,
            "mode": "publish_remote_analysis_lock",
            "lock_holder": run_id,
            "acquired_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
        try:
            self.remote_client.create_document(
                index=self.metadata_index,
                document_id=PUBLISH_LOCK_DOCUMENT_ID,
                document=lock_document,
            )
            return
        except ElasticsearchClientError as exc:
            if " 409 " not in f" {exc} " and "response 409" not in str(exc):
                raise
        existing_lock = self.remote_client.get_document(index=self.metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)
        if existing_lock is None:
            self.remote_client.create_document(
                index=self.metadata_index,
                document_id=PUBLISH_LOCK_DOCUMENT_ID,
                document=lock_document,
            )
            return
        expires_at_raw = existing_lock.get("expires_at")
        lock_holder = existing_lock.get("lock_holder") or existing_lock.get("run_id") or "unknown"
        expires_at_value = _parse_iso(expires_at_raw) if isinstance(expires_at_raw, str) else None
        if expires_at_value is not None and expires_at_value <= now:
            self.remote_client.delete_document(index=self.metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)
            self.remote_client.create_document(
                index=self.metadata_index,
                document_id=PUBLISH_LOCK_DOCUMENT_ID,
                document=lock_document,
            )
            return
        raise ElasticsearchClientError(
            "A remote analysis publish lock is already held. "
            f"Current holder={lock_holder!r}, expires_at={expires_at_raw!r}."
        )

    def _release_publish_lock(self, *, run_id: str) -> None:
        existing_lock = self.remote_client.get_document(index=self.metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)
        if existing_lock is None:
            return
        lock_holder = existing_lock.get("lock_holder") or existing_lock.get("run_id")
        if lock_holder == run_id:
            self.remote_client.delete_document(index=self.metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)

    def _cleanup_staged_indices(
        self,
        *,
        staged_indices: dict[str, str],
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        for key, staged_index in staged_indices.items():
            if not self.remote_client.index_exists(index=staged_index):
                continue
            self.remote_client.delete_index(index=staged_index)
            if progress_callback is not None:
                progress_callback(
                    "Deleted staged remote analysis index after failed publish: "
                    f"{key} -> {staged_index}."
                )

    def publish_local_to_remote(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        resume_existing_run: bool = False,
    ) -> AnalysisSyncSummary:
        self._ensure_remote_enabled()
        effective_run_id = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        counts: dict[str, int] = {}
        staged_indices: dict[str, str] = {}
        lock_acquired = False
        try:
            if resume_existing_run:
                existing_lock = self.get_active_publish_lock()
                if existing_lock is None:
                    raise ElasticsearchClientError(
                        "Cannot resume remote analysis publish because no active publish lock exists."
                    )
                lock_run_id = existing_lock.get("run_id")
                if lock_run_id != effective_run_id:
                    raise ElasticsearchClientError(
                        "Cannot resume remote analysis publish because the active lock does not match the requested run. "
                        f"requested_run={effective_run_id!r}, active_run={lock_run_id!r}."
                    )
            else:
                self._ensure_publish_freshness()
                self._acquire_publish_lock(run_id=effective_run_id, job_id=job_id)
                lock_acquired = True
            for spec in self.specs:
                local_count = self.local_client.count_documents(index=spec.local_index, query={"match_all": {}})
                counts[spec.key] = local_count
                staged_index = f"{spec.remote_alias}-run-{effective_run_id}"
                staged_indices[spec.key] = staged_index
                if progress_callback is not None:
                    progress_callback(
                        "Publishing local analysis index to remote stage: "
                        f"local_index={spec.local_index}, staged_remote_index={staged_index}, documents={local_count}."
                    )
                self._recreate_index(self.remote_client, index=staged_index, mapping=spec.mapping)
                copied = self._copy_index(
                    source_client=self.local_client,
                    source_index=spec.local_index,
                    target_client=self.remote_client,
                    target_index=staged_index,
                    source_fields=spec.source_fields,
                    progress_callback=progress_callback,
                    progress_label=f"Publish progress for {spec.key}",
                )
                remote_count = self.remote_client.count_documents(index=staged_index, query={"match_all": {}})
                if copied != local_count or remote_count != local_count:
                    raise ElasticsearchClientError(
                        "Remote publish validation failed: "
                        f"{spec.key} local_count={local_count}, copied={copied}, remote_count={remote_count}."
                    )

            alias_actions: list[dict[str, Any]] = []
            for spec in self.specs:
                for existing_index in self.remote_client.get_alias_indices(alias=spec.remote_alias):
                    alias_actions.append({"remove": {"index": existing_index, "alias": spec.remote_alias}})
                alias_actions.append({"add": {"index": staged_indices[spec.key], "alias": spec.remote_alias}})
            self.remote_client.update_aliases(actions=alias_actions)

            self._ensure_metadata_index()
            metadata_document = {
                "run_id": effective_run_id,
                "job_id": job_id or effective_run_id,
                "mode": "publish_remote_analysis",
                "published_at": _now_iso(),
                "embedding_provider": get_duplicate_embedding_provider(),
                "local_indices": {spec.key: spec.local_index for spec in self.specs},
                "remote_aliases": {spec.key: spec.remote_alias for spec in self.specs},
                "document_counts": counts,
            }
            self.remote_client.bulk_index(
                index=self.metadata_index,
                documents=[("published", metadata_document), (effective_run_id, metadata_document)],
            )
            local_metadata_document = dict(metadata_document)
            local_metadata_document["synced_at"] = _now_iso()
            self._write_local_sync_state(local_metadata_document)

            if progress_callback is not None:
                progress_callback(
                    "Remote analysis publish complete: "
                    f"run_id={effective_run_id}, article_documents={counts.get('articles', 0)}, "
                    f"chunk_documents={counts.get('chunks', 0)}, "
                    f"edge_documents={counts.get('edges', 0)}, "
                    f"cluster_documents={counts.get('clusters', 0)}."
                )
            return AnalysisSyncSummary(
                mode="publish_remote_analysis",
                remoteRunId=effective_run_id,
                articleDocuments=counts.get("articles", 0),
                chunkDocuments=counts.get("chunks", 0),
                edgeDocuments=counts.get("edges", 0),
                clusterDocuments=counts.get("clusters", 0),
                remoteAliases={spec.key: spec.remote_alias for spec in self.specs},
            )
        except Exception:
            self._cleanup_staged_indices(staged_indices=staged_indices, progress_callback=progress_callback)
            raise
        finally:
            if lock_acquired or resume_existing_run:
                self._release_publish_lock(run_id=effective_run_id)


def build_remote_analysis_sync_service() -> RemoteAnalysisSyncService:
    return RemoteAnalysisSyncService(
        local_client=ElasticsearchClient(base_url=get_target_es_url()),
        remote_client=ElasticsearchClient(
            base_url=get_remote_analysis_es_url(),
            api_key=get_remote_analysis_es_api_key(),
        ),
    )
