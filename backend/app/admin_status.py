from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import (
    get_local_analysis_metadata_index,
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
from app.elasticsearch.client import ElasticsearchClient
from app.sync.analysis import PUBLISH_LOCK_DOCUMENT_ID


class CoverageStat(BaseModel):
    field_name: str = Field(alias="fieldName")
    present_count: int = Field(alias="presentCount")
    missing_count: int = Field(alias="missingCount")
    percentage: float

    model_config = {"populate_by_name": True}


class ArticleIndexStatus(BaseModel):
    index_name: str = Field(alias="indexName")
    total_documents: int = Field(alias="totalDocuments")
    unique_article_ids: int = Field(alias="uniqueArticleIds")
    coverage: list[CoverageStat]

    model_config = {"populate_by_name": True}


class ChunkIndexStatus(BaseModel):
    index_name: str = Field(alias="indexName")
    total_documents: int = Field(alias="totalDocuments")
    embedded_documents: int = Field(alias="embeddedDocuments")
    missing_embeddings: int = Field(alias="missingEmbeddings")
    embedding_percentage: float = Field(alias="embeddingPercentage")
    chunked_articles: int = Field(alias="chunkedArticles")
    missing_articles: int = Field(alias="missingArticles")
    article_coverage_percentage: float = Field(alias="articleCoveragePercentage")

    model_config = {"populate_by_name": True}


class AdminIndexStatusResponse(BaseModel):
    article_index: ArticleIndexStatus = Field(alias="articleIndex")
    chunk_index: ChunkIndexStatus = Field(alias="chunkIndex")

    model_config = {"populate_by_name": True}


class RemoteAnalysisAliasStatus(BaseModel):
    alias: str
    backing_indices: list[str] = Field(alias="backingIndices")
    document_count: int = Field(alias="documentCount")

    model_config = {"populate_by_name": True}


class RemotePublishedRunStatus(BaseModel):
    run_id: str = Field(alias="runId")
    published_at: str = Field(alias="publishedAt")
    embedding_provider: str = Field(alias="embeddingProvider")
    document_counts: dict[str, int] = Field(alias="documentCounts")

    model_config = {"populate_by_name": True}


class LocalRemoteSyncStatus(BaseModel):
    remote_run_id: str = Field(alias="remoteRunId")
    published_at: str = Field(alias="publishedAt")
    synced_at: str = Field(alias="syncedAt")
    embedding_provider: str = Field(alias="embeddingProvider")

    model_config = {"populate_by_name": True}


class RemotePublishLockStatus(BaseModel):
    run_id: str = Field(alias="runId")
    acquired_at: str | None = Field(default=None, alias="acquiredAt")
    expires_at: str | None = Field(default=None, alias="expiresAt")

    model_config = {"populate_by_name": True}


class RemoteAnalysisStatusResponse(BaseModel):
    enabled: bool
    url_configured: bool = Field(alias="urlConfigured")
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    source_index: str = Field(alias="sourceIndex")
    source_index_protected: bool = Field(alias="sourceIndexProtected")
    metadata_index: str = Field(alias="metadataIndex")
    local_metadata_index: str = Field(alias="localMetadataIndex")
    local_document_counts: dict[str, int] = Field(alias="localDocumentCounts")
    aliases: dict[str, RemoteAnalysisAliasStatus]
    latest_published_run: RemotePublishedRunStatus | None = Field(default=None, alias="latestPublishedRun")
    local_sync: LocalRemoteSyncStatus | None = Field(default=None, alias="localSync")
    local_snapshot_stale: bool = Field(alias="localSnapshotStale")
    publish_lock: RemotePublishLockStatus | None = Field(default=None, alias="publishLock")
    publish_blocked_reason: str | None = Field(default=None, alias="publishBlockedReason")

    model_config = {"populate_by_name": True}


def _count(client: ElasticsearchClient, *, index: str, query: dict[str, object]) -> int:
    return client.count_documents(index=index, query=query)


def _coverage_stat(
    client: ElasticsearchClient,
    *,
    index: str,
    total_documents: int,
    field_name: str,
) -> CoverageStat:
    present_count = _count(client, index=index, query={"exists": {"field": field_name}})
    missing_count = max(total_documents - present_count, 0)
    percentage = 0.0 if total_documents == 0 else round((present_count / total_documents) * 100, 1)
    return CoverageStat(
        fieldName=field_name,
        presentCount=present_count,
        missingCount=missing_count,
        percentage=percentage,
    )


def get_admin_index_status() -> AdminIndexStatusResponse:
    article_index = get_target_es_index()
    chunk_index = get_target_chunk_index()
    client = ElasticsearchClient(base_url=get_target_es_url())

    total_articles = _count(client, index=article_index, query={"match_all": {}})
    unique_article_ids = client.cardinality_aggregation(index=article_index, field="article_id") if total_articles > 0 else 0
    article_coverage = [
        _coverage_stat(client, index=article_index, total_documents=total_articles, field_name=field_name)
        for field_name in [
            "title",
            "summary",
            "body_markdown",
            "compare_text",
            "compare_text_hash",
            "duplicate_title_embedding",
            "duplicate_summary_embedding",
            "duplicate_body_embedding",
            "duplicate_comparison_embedding",
        ]
    ]

    total_chunks = _count(client, index=chunk_index, query={"match_all": {}}) if client.index_exists(index=chunk_index) else 0
    embedded_chunks = (
        _count(client, index=chunk_index, query={"exists": {"field": "duplicate_comparison_embedding"}})
        if total_chunks > 0
        else 0
    )
    chunked_articles = (
        client.cardinality_aggregation(index=chunk_index, field="article_id")
        if total_chunks > 0
        else 0
    )
    missing_chunk_embeddings = max(total_chunks - embedded_chunks, 0)
    chunk_percentage = 0.0 if total_chunks == 0 else round((embedded_chunks / total_chunks) * 100, 1)
    missing_chunk_articles = max(unique_article_ids - chunked_articles, 0)
    chunk_article_percentage = (
        0.0 if unique_article_ids == 0 else round((chunked_articles / unique_article_ids) * 100, 1)
    )

    return AdminIndexStatusResponse(
        articleIndex=ArticleIndexStatus(
            indexName=article_index,
            totalDocuments=total_articles,
            uniqueArticleIds=unique_article_ids,
            coverage=article_coverage,
        ),
        chunkIndex=ChunkIndexStatus(
            indexName=chunk_index,
            totalDocuments=total_chunks,
            embeddedDocuments=embedded_chunks,
            missingEmbeddings=missing_chunk_embeddings,
            embeddingPercentage=chunk_percentage,
            chunkedArticles=chunked_articles,
            missingArticles=missing_chunk_articles,
            articleCoveragePercentage=chunk_article_percentage,
        ),
    )


def get_remote_analysis_status() -> RemoteAnalysisStatusResponse:
    source_index = get_source_es_index()
    metadata_index = get_remote_analysis_metadata_index()
    local_metadata_index = get_local_analysis_metadata_index()
    aliases = {
        "articles": get_remote_analysis_normalized_alias(),
        "chunks": get_remote_analysis_chunk_alias(),
        "edges": get_remote_analysis_duplicate_edge_alias(),
        "clusters": get_remote_analysis_duplicate_cluster_alias(),
    }
    enabled = is_remote_analysis_enabled()
    api_key_configured = bool(get_remote_analysis_es_api_key())

    if not enabled:
        return RemoteAnalysisStatusResponse(
            enabled=False,
            urlConfigured=False,
            apiKeyConfigured=api_key_configured,
            sourceIndex=source_index,
            sourceIndexProtected=all(alias != source_index for alias in aliases.values()),
            metadataIndex=metadata_index,
            localMetadataIndex=local_metadata_index,
            localDocumentCounts={
                "articles": 0,
                "chunks": 0,
                "edges": 0,
                "clusters": 0,
            },
            aliases={
                key: RemoteAnalysisAliasStatus(alias=alias, backingIndices=[], documentCount=0)
                for key, alias in aliases.items()
            },
            latestPublishedRun=None,
            localSync=None,
            localSnapshotStale=False,
            publishLock=None,
            publishBlockedReason=None,
        )

    local_client = ElasticsearchClient(base_url=get_target_es_url())
    client = ElasticsearchClient(
        base_url=get_remote_analysis_es_url(),
        api_key=get_remote_analysis_es_api_key(),
    )
    alias_status: dict[str, RemoteAnalysisAliasStatus] = {}
    for key, alias in aliases.items():
        backing_indices = client.get_alias_indices(alias=alias)
        document_count = 0
        if backing_indices or client.index_exists(index=alias):
            document_count = client.count_documents(index=alias, query={"match_all": {}})
        alias_status[key] = RemoteAnalysisAliasStatus(
            alias=alias,
            backingIndices=backing_indices,
            documentCount=document_count,
        )

    latest_run: RemotePublishedRunStatus | None = None
    if client.index_exists(index=metadata_index):
        hits = client.search(
            index=metadata_index,
            body={
                "size": 1,
                "sort": [{"published_at": "desc"}],
                "query": {"match_all": {}},
            },
        )
        if hits:
            source = hits[0].get("_source")
            if isinstance(source, dict):
                run_id = source.get("run_id")
                published_at = source.get("published_at")
                embedding_provider = source.get("embedding_provider")
                document_counts = source.get("document_counts")
                if (
                    isinstance(run_id, str)
                    and isinstance(published_at, str)
                    and isinstance(embedding_provider, str)
                    and isinstance(document_counts, dict)
                ):
                    latest_run = RemotePublishedRunStatus(
                        runId=run_id,
                        publishedAt=published_at,
                        embeddingProvider=embedding_provider,
                        documentCounts={
                            str(key): int(value)
                            for key, value in document_counts.items()
                            if isinstance(key, str) and isinstance(value, int | float)
                        },
                    )

    publish_lock: RemotePublishLockStatus | None = None
    if client.index_exists(index=metadata_index):
        lock_source = client.get_document(index=metadata_index, document_id=PUBLISH_LOCK_DOCUMENT_ID)
        if isinstance(lock_source, dict):
            run_id = lock_source.get("run_id")
            acquired_at = lock_source.get("acquired_at")
            expires_at = lock_source.get("expires_at")
            if isinstance(run_id, str):
                publish_lock = RemotePublishLockStatus(
                    runId=run_id,
                    acquiredAt=acquired_at if isinstance(acquired_at, str) else None,
                    expiresAt=expires_at if isinstance(expires_at, str) else None,
                )

    local_document_counts = {
        "articles": local_client.count_documents(index=get_target_es_index(), query={"match_all": {}})
        if local_client.index_exists(index=get_target_es_index())
        else 0,
        "chunks": local_client.count_documents(index=get_target_chunk_index(), query={"match_all": {}})
        if local_client.index_exists(index=get_target_chunk_index())
        else 0,
        "edges": local_client.count_documents(index=get_target_duplicate_edge_index(), query={"match_all": {}})
        if local_client.index_exists(index=get_target_duplicate_edge_index())
        else 0,
        "clusters": local_client.count_documents(index=get_target_duplicate_cluster_index(), query={"match_all": {}})
        if local_client.index_exists(index=get_target_duplicate_cluster_index())
        else 0,
    }

    local_sync: LocalRemoteSyncStatus | None = None
    if local_client.index_exists(index=local_metadata_index):
        hits = local_client.search(
            index=local_metadata_index,
            body={
                "size": 1,
                "query": {"match_all": {}},
            },
        )
        if hits:
            source = hits[0].get("_source")
            if isinstance(source, dict):
                run_id = source.get("run_id")
                published_at = source.get("published_at")
                synced_at = source.get("synced_at")
                embedding_provider = source.get("embedding_provider")
                if (
                    isinstance(run_id, str)
                    and isinstance(published_at, str)
                    and isinstance(synced_at, str)
                    and isinstance(embedding_provider, str)
                ):
                    local_sync = LocalRemoteSyncStatus(
                        remoteRunId=run_id,
                        publishedAt=published_at,
                        syncedAt=synced_at,
                        embeddingProvider=embedding_provider,
                    )

    local_snapshot_stale = False
    if latest_run is not None and local_sync is not None:
        local_snapshot_stale = local_sync.remote_run_id != latest_run.run_id
    elif latest_run is not None and local_sync is None:
        local_snapshot_stale = True

    publish_blocked_reason: str | None = None
    if publish_lock is not None:
        publish_blocked_reason = (
            "A remote analysis publish is already in progress. "
            f"Lock holder: {publish_lock.run_id}."
        )
    elif local_snapshot_stale:
        publish_blocked_reason = (
            "Local working indices are older than the latest published remote analysis snapshot. "
            "Pull published remote analysis before publishing local calculations."
        )

    return RemoteAnalysisStatusResponse(
        enabled=True,
        urlConfigured=True,
        apiKeyConfigured=api_key_configured,
        sourceIndex=source_index,
        sourceIndexProtected=all(alias != source_index for alias in aliases.values()),
        metadataIndex=metadata_index,
        localMetadataIndex=local_metadata_index,
        localDocumentCounts=local_document_counts,
        aliases=alias_status,
        latestPublishedRun=latest_run,
        localSync=local_sync,
        localSnapshotStale=local_snapshot_stale,
        publishLock=publish_lock,
        publishBlockedReason=publish_blocked_reason,
    )
