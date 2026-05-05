from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import (
    get_target_chunk_index,
    get_target_es_index,
    get_target_es_url,
)
from app.elasticsearch.client import ElasticsearchClient


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
