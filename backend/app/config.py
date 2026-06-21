from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field
from dotenv import load_dotenv

LOCAL_NORMALIZED_INDEX = "kcs-kb-articles-v1"

load_dotenv()


class HealthResponse(BaseModel):
    service: str
    status: str


class ProviderConfig(BaseModel):
    embeddings: str
    duplicate_embedding_provider: str = Field(alias="duplicateEmbeddingProvider")
    duplicate_embedding_task: str = Field(alias="duplicateEmbeddingTask")
    reranking: str
    llm_explanation: str = Field(alias="llmExplanation")

    model_config = {"populate_by_name": True}


class SourceElasticsearchConfig(BaseModel):
    url: str
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    index: str

    model_config = {"populate_by_name": True}


class TargetElasticsearchConfig(BaseModel):
    url: str
    normalized_index: str = Field(alias="normalizedIndex")
    chunk_index: str = Field(alias="chunkIndex")
    duplicate_edge_index: str = Field(alias="duplicateEdgeIndex")
    duplicate_cluster_index: str = Field(alias="duplicateClusterIndex")

    model_config = {"populate_by_name": True}


class RemoteAnalysisElasticsearchConfig(BaseModel):
    url: str
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    enabled: bool
    normalized_alias: str = Field(alias="normalizedAlias")
    chunk_alias: str = Field(alias="chunkAlias")
    duplicate_edge_alias: str = Field(alias="duplicateEdgeAlias")
    duplicate_cluster_alias: str = Field(alias="duplicateClusterAlias")
    metadata_index: str = Field(alias="metadataIndex")

    model_config = {"populate_by_name": True}


class EmbeddingEndpointConfig(BaseModel):
    provider: str
    url: str
    model: str
    api_key_configured: bool = Field(alias="apiKeyConfigured")

    model_config = {"populate_by_name": True}


class RerankerEndpointConfig(BaseModel):
    provider: str
    url: str
    model: str
    api_key_configured: bool = Field(alias="apiKeyConfigured")

    model_config = {"populate_by_name": True}


class EffectiveConfig(BaseModel):
    app_name: str = Field(alias="appName")
    environment: str
    providers: ProviderConfig
    source_elasticsearch: SourceElasticsearchConfig = Field(alias="sourceElasticsearch")
    target_elasticsearch: TargetElasticsearchConfig = Field(alias="targetElasticsearch")
    remote_analysis_elasticsearch: RemoteAnalysisElasticsearchConfig = Field(alias="remoteAnalysisElasticsearch")
    embedding_endpoints: list[EmbeddingEndpointConfig] = Field(alias="embeddingEndpoints")
    reranker_endpoints: list[RerankerEndpointConfig] = Field(alias="rerankerEndpoints")
    explanation_provider: str = Field(alias="explanationProvider")
    explanation_model: str = Field(alias="explanationModel")
    deepsearch_enabled: bool = Field(alias="deepsearchEnabled")

    model_config = {"populate_by_name": True}


class IngestRequest(BaseModel):
    full: bool = True


class IngestSummary(BaseModel):
    source_index: str = Field(alias="sourceIndex")
    target_index: str = Field(alias="targetIndex")
    fetched_documents: int = Field(alias="fetchedDocuments")
    indexed_documents: int = Field(alias="indexedDocuments")
    skipped_documents: int = Field(alias="skippedDocuments")

    model_config = {"populate_by_name": True}


class ClusterMaterializationRequest(BaseModel):
    top_n: int = Field(default=12, alias="topN", ge=1, le=50)
    include_cve: bool = Field(default=False, alias="includeCve")
    include_chunk_seed: bool = Field(default=True, alias="includeChunkSeed")
    max_component_size: int = Field(default=12, alias="maxComponentSize", ge=2, le=100)
    weak_edge_threshold: float = Field(default=0.78, alias="weakEdgeThreshold", ge=0.0, le=1.0)
    analysis_mode: str = Field(default="graph", alias="analysisMode")

    model_config = {"populate_by_name": True}


class ExplanationRequest(BaseModel):
    include_research: bool = Field(default=False, alias="includeResearch")

    model_config = {"populate_by_name": True}


class ClusterReviewUpdateRequest(BaseModel):
    review_state: str = Field(alias="reviewState")

    model_config = {"populate_by_name": True}


class AnalysisSyncSummary(BaseModel):
    mode: str
    remote_run_id: str | None = Field(default=None, alias="remoteRunId")
    article_documents: int = Field(alias="articleDocuments")
    chunk_documents: int = Field(alias="chunkDocuments")
    edge_documents: int = Field(alias="edgeDocuments")
    cluster_documents: int = Field(alias="clusterDocuments")
    remote_aliases: dict[str, str] = Field(alias="remoteAliases")

    model_config = {"populate_by_name": True}


def get_source_es_url() -> str:
    return os.getenv("SOURCE_ES_URL", "")


def get_source_es_api_key() -> str:
    return os.getenv("SOURCE_ES_API_KEY", "")


def get_source_es_index() -> str:
    return os.getenv("SOURCE_ES_INDEX", "kb-articles-source-index")


def get_target_es_url() -> str:
    return os.getenv("ELASTICSEARCH_LOCAL_URL", "http://elasticsearch:9200")


def get_target_es_index() -> str:
    return LOCAL_NORMALIZED_INDEX


def get_target_chunk_index() -> str:
    return "kcs-kb-article-chunks-v1"


def get_target_duplicate_edge_index() -> str:
    return "kcs-kb-duplicate-edges-v1"


def get_target_duplicate_cluster_index() -> str:
    return "kcs-kb-duplicate-clusters-v1"


def get_remote_analysis_es_url() -> str:
    return os.getenv("REMOTE_ANALYSIS_ES_URL", "").strip() or get_source_es_url()


def get_remote_analysis_es_api_key() -> str:
    return os.getenv("REMOTE_ANALYSIS_ES_API_KEY", "").strip() or get_source_es_api_key()


def is_remote_analysis_enabled() -> bool:
    return bool(get_remote_analysis_es_url().strip())


def get_remote_analysis_normalized_alias() -> str:
    return os.getenv("REMOTE_ANALYSIS_NORMALIZED_ALIAS", "kb-analysis-articles-v1")


def get_remote_analysis_chunk_alias() -> str:
    return os.getenv("REMOTE_ANALYSIS_CHUNK_ALIAS", "kb-analysis-article-chunks-v1")


def get_remote_analysis_duplicate_edge_alias() -> str:
    return os.getenv("REMOTE_ANALYSIS_DUPLICATE_EDGE_ALIAS", "kb-analysis-duplicate-edges-v1")


def get_remote_analysis_duplicate_cluster_alias() -> str:
    return os.getenv("REMOTE_ANALYSIS_DUPLICATE_CLUSTER_ALIAS", "kb-analysis-duplicate-clusters-v1")


def get_remote_analysis_metadata_index() -> str:
    return os.getenv("REMOTE_ANALYSIS_METADATA_INDEX", "kb-analysis-sync-state-v1")


def get_local_analysis_metadata_index() -> str:
    return os.getenv("LOCAL_ANALYSIS_METADATA_INDEX", "kb-analysis-local-sync-state-v1")


def get_remote_analysis_publish_lock_seconds() -> int:
    raw = os.getenv("REMOTE_ANALYSIS_PUBLISH_LOCK_SECONDS", "1800").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1800
    return max(value, 60)


def get_remote_analysis_sync_batch_size() -> int:
    raw = os.getenv("REMOTE_ANALYSIS_SYNC_BATCH_SIZE", "100").strip()
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(10, min(value, 500))


def get_remote_analysis_http_timeout_seconds() -> float:
    raw = os.getenv("REMOTE_ANALYSIS_HTTP_TIMEOUT_SECONDS", "180").strip()
    try:
        value = float(raw)
    except ValueError:
        return 180.0
    return max(value, 30.0)


def get_environment() -> str:
    return os.getenv("APP_ENV", "development")


def get_duplicate_embedding_provider() -> str:
    return os.getenv("DUPLICATE_EMBEDDING_PROVIDER", "local")


def get_duplicate_embedding_task() -> str:
    return os.getenv("DUPLICATE_EMBEDDING_TASK", "retrieval.passage")


def get_local_embedding_url() -> str:
    return os.getenv("LOCAL_EMBEDDING_URL", "http://local-embeddings:7997/v1/embeddings")


def get_local_embedding_fallback_urls() -> list[str]:
    raw = os.getenv(
        "LOCAL_EMBEDDING_FALLBACK_URLS",
        "http://host.docker.internal:7997/v1/embeddings",
    )
    return [value.strip() for value in raw.split(",") if value.strip()]


def get_local_embedding_model() -> str:
    return os.getenv("LOCAL_EMBEDDING_MODEL", "jinaai/jina-embeddings-v3-hf")


def get_jina_embedding_url() -> str:
    return os.getenv("JINA_EMBEDDING_URL", "https://api.jina.ai/v1/embeddings")


def get_jina_api_key() -> str:
    return os.getenv("JINA_API_KEY", "")


def get_jina_embedding_model() -> str:
    return os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3")


def get_jina_reranker_url() -> str:
    return os.getenv("JINA_RERANKER_URL", "https://api.jina.ai/v1/rerank")


def get_jina_reranker_model() -> str:
    return os.getenv("JINA_RERANKER_MODEL", "jina-reranker-v2-base-multilingual")


def get_duplicate_embedding_dims() -> int:
    return int(os.getenv("DUPLICATE_EMBEDDING_DIMS", "1024"))


def get_llm_explanation_provider() -> str:
    return os.getenv("LLM_EXPLANATION_PROVIDER", "stub")


def get_gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")


def get_gemini_api_url() -> str:
    model = get_gemini_model()
    return os.getenv(
        "GEMINI_API_URL",
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )


def are_agents_enabled() -> bool:
    """Feature flag for the multi-agent editorial supervisor (default OFF).

    When false, no agent routes/jobs are mounted and the supervisor must no-op:
    existing UI/API behaviour stays byte-for-byte unchanged.
    """
    return os.getenv("AGENTS_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}


def get_agent_reasoning_provider() -> str:
    """Reasoning provider for the ReviewerAgent (default deterministic, offline)."""
    return os.getenv("AGENT_REASONING_PROVIDER", "deterministic")


def get_agent_episode_index() -> str:
    return os.getenv("AGENT_EPISODE_INDEX", "kcs-kb-agent-episodes-v1")


def is_memory_enabled() -> bool:
    """Feature flag for episodic recall-before-acting (default OFF).

    Independent of ``AGENTS_ENABLED``. When false, NO recall happens: the supervisor
    path embeds/logs episodes exactly as before but never queries past episodes for
    precedent, so behaviour stays reproducible and byte-for-byte unchanged.
    """
    return os.getenv("MEMORY_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}


def get_memory_recall_k() -> int:
    """How many most-similar past episodes recall returns as precedent (default 5)."""
    raw = os.getenv("MEMORY_RECALL_K", "5").strip()
    try:
        value = int(raw)
    except ValueError:
        return 5
    return value if value > 0 else 5


def get_agent_draft_index() -> str:
    return os.getenv("AGENT_DRAFT_INDEX", "kcs-kb-agent-drafts-v1")


def is_deepsearch_enabled() -> bool:
    return os.getenv("DEEPSEARCH_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}


def get_deepsearch_url() -> str:
    return os.getenv("DEEPSEARCH_URL", "https://app-api.deepsearch.com/v1/compute")


def get_deepsearch_api_key() -> str:
    return os.getenv("DEEPSEARCH_API_KEY", "")


@lru_cache(maxsize=1)
def get_effective_config() -> EffectiveConfig:
    source_api_key = get_source_es_api_key()

    return EffectiveConfig(
        appName="kcs-control-plane",
        environment=get_environment(),
        providers=ProviderConfig(
            embeddings=os.getenv("EMBEDDINGS_PROVIDER", "stub"),
            duplicateEmbeddingProvider=get_duplicate_embedding_provider(),
            duplicateEmbeddingTask=get_duplicate_embedding_task(),
            reranking=os.getenv("RERANKER_PROVIDER", "stub"),
            llmExplanation=os.getenv("LLM_EXPLANATION_PROVIDER", "stub"),
        ),
        sourceElasticsearch=SourceElasticsearchConfig(
            url=get_source_es_url(),
            apiKeyConfigured=bool(source_api_key),
            index=get_source_es_index(),
        ),
        targetElasticsearch=TargetElasticsearchConfig(
            url=get_target_es_url(),
            normalizedIndex=get_target_es_index(),
            chunkIndex=get_target_chunk_index(),
            duplicateEdgeIndex=get_target_duplicate_edge_index(),
            duplicateClusterIndex=get_target_duplicate_cluster_index(),
        ),
        remoteAnalysisElasticsearch=RemoteAnalysisElasticsearchConfig(
            url=get_remote_analysis_es_url(),
            apiKeyConfigured=bool(get_remote_analysis_es_api_key()),
            enabled=is_remote_analysis_enabled(),
            normalizedAlias=get_remote_analysis_normalized_alias(),
            chunkAlias=get_remote_analysis_chunk_alias(),
            duplicateEdgeAlias=get_remote_analysis_duplicate_edge_alias(),
            duplicateClusterAlias=get_remote_analysis_duplicate_cluster_alias(),
            metadataIndex=get_remote_analysis_metadata_index(),
        ),
        embeddingEndpoints=[
            EmbeddingEndpointConfig(
                provider="local",
                url=get_local_embedding_url(),
                model=get_local_embedding_model(),
                apiKeyConfigured=False,
            ),
            EmbeddingEndpointConfig(
                provider="jina",
                url=get_jina_embedding_url(),
                model=get_jina_embedding_model(),
                apiKeyConfigured=bool(get_jina_api_key()),
            ),
        ],
        rerankerEndpoints=[
            RerankerEndpointConfig(
                provider="jina",
                url=get_jina_reranker_url(),
                model=get_jina_reranker_model(),
                apiKeyConfigured=bool(get_jina_api_key()),
            )
        ],
        explanationProvider=get_llm_explanation_provider(),
        explanationModel=get_gemini_model(),
        deepsearchEnabled=is_deepsearch_enabled(),
    )
