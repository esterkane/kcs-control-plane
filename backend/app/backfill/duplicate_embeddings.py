from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.config import (
    get_duplicate_embedding_task,
    get_duplicate_embedding_dims,
    get_target_chunk_index,
    get_target_es_index,
    get_target_es_url,
)
from app.dedup.chunking import chunk_article_document
from app.dedup.compare_text import build_compare_text
from app.elasticsearch.client import ElasticsearchClient
from app.embeddings.providers import EmbeddingProvider, create_duplicate_embedding_provider
from app.ingestion.kb import NormalizedKbDocument

CHUNK_INDEX_NAME = "kcs-kb-article-chunks-v1"
CHUNK_EMBEDDING_DIMS = get_duplicate_embedding_dims()


class ChunkDocument(BaseModel):
    chunk_id: str = Field(alias="chunk_id")
    article_id: str = Field(alias="article_id")
    remote_document_id: str = Field(alias="remote_document_id")
    chunk_ordinal: int = Field(alias="chunk_ordinal")
    chunk_kind: str = Field(alias="chunk_kind")
    chunk_heading: str | None = Field(alias="chunk_heading")
    chunk_text: str = Field(alias="chunk_text")
    chunk_word_count: int = Field(alias="chunk_word_count")
    compare_text_hash: str = Field(alias="compare_text_hash")
    duplicate_comparison_embedding: list[float] = Field(alias="duplicate_comparison_embedding")
    source_updated_at: str | None = Field(alias="source_updated_at")
    source_index: str = Field(alias="source_index")

    model_config = {"populate_by_name": True}


CHUNK_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "chunk_id": {"type": "keyword"},
            "article_id": {"type": "keyword"},
            "remote_document_id": {"type": "keyword"},
            "chunk_ordinal": {"type": "integer"},
            "chunk_kind": {"type": "keyword"},
            "chunk_heading": {"type": "keyword"},
            "chunk_text": {"type": "text"},
            "chunk_word_count": {"type": "integer"},
            "compare_text_hash": {"type": "keyword"},
            "duplicate_comparison_embedding": {
                "type": "dense_vector",
                "dims": CHUNK_EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "source_updated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "source_index": {"type": "keyword"},
        },
    },
}


@dataclass(frozen=True)
class BackfillStats:
    scanned_articles: int
    updated_articles: int = 0
    updated_chunks: int = 0
    skipped_articles: int = 0


@dataclass(frozen=True)
class PendingArticleEmbedding:
    document_id: str
    source: dict[str, Any]
    text_hash: str
    compare_text: str
    title_text: str | None
    summary_text: str | None
    body_text: str | None


def compare_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_articles(client: ElasticsearchClient, *, index: str) -> list[tuple[str, dict[str, Any]]]:
    pit_id = client.open_point_in_time(index=index, keep_alive="1m")
    search_after: list[Any] | None = None
    articles: list[tuple[str, dict[str, Any]]] = []
    try:
        while True:
            page = client.search_with_pit(
                pit_id=pit_id,
                keep_alive="1m",
                size=250,
                search_after=search_after,
            )
            pit_id = page.pit_id
            if not page.hits:
                break
            for hit in page.hits:
                if not isinstance(hit.get("_source"), dict):
                    continue
                hit_id = hit.get("_id")
                if not isinstance(hit_id, str):
                    continue
                articles.append((hit_id, hit["_source"]))
            last_sort = page.hits[-1].get("sort")
            search_after = last_sort if isinstance(last_sort, list) else None
    finally:
        client.close_point_in_time(pit_id=pit_id)
    return articles


def create_chunk_index_if_missing(client: ElasticsearchClient, *, index_name: str = CHUNK_INDEX_NAME) -> None:
    if client.index_exists(index=index_name):
        client.put_mapping(
            index=index_name,
            mapping={"properties": CHUNK_INDEX_MAPPING["mappings"]["properties"]},
        )
        return
    client.create_index(index=index_name, mapping=CHUNK_INDEX_MAPPING)


def _normalize_article(source: dict[str, Any]) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(source)


def _has_embedding(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _article_embedding_inputs(article: NormalizedKbDocument) -> tuple[str, str | None, str | None, str | None]:
    compare_text = build_compare_text(article)
    title_text = f"# {article.title}" if article.title else None
    summary_text = f"## Summary\n{article.summary}" if article.summary else None
    body_text = article.body_markdown.strip() if article.body_markdown else None
    return compare_text, title_text, summary_text, body_text


def backfill_article_embeddings(
    *,
    es_client: ElasticsearchClient,
    provider: EmbeddingProvider,
    task: str,
    article_index: str = "kcs-kb-articles-v1",
    batch_size: int = 4,
) -> BackfillStats:
    articles = _load_articles(es_client, index=article_index)
    updates: list[tuple[str, dict[str, Any]]] = []
    pending_articles: list[PendingArticleEmbedding] = []
    skipped = 0

    def flush() -> None:
        nonlocal pending_articles
        if not pending_articles:
            return
        compare_embeddings = provider.embed_batch(
            [pending.compare_text for pending in pending_articles],
            task,
        )
        title_indices = [(index, pending.title_text) for index, pending in enumerate(pending_articles) if pending.title_text]
        summary_indices = [(index, pending.summary_text) for index, pending in enumerate(pending_articles) if pending.summary_text]
        body_indices = [(index, pending.body_text) for index, pending in enumerate(pending_articles) if pending.body_text]

        title_embeddings = provider.embed_batch(
            [text for _, text in title_indices],
            task,
        ) if title_indices else []
        summary_embeddings = provider.embed_batch(
            [text for _, text in summary_indices],
            task,
        ) if summary_indices else []
        body_embeddings = provider.embed_batch(
            [text for _, text in body_indices],
            task,
        ) if body_indices else []

        title_map = {index: embedding for (index, _), embedding in zip(title_indices, title_embeddings, strict=True)}
        summary_map = {index: embedding for (index, _), embedding in zip(summary_indices, summary_embeddings, strict=True)}
        body_map = {index: embedding for (index, _), embedding in zip(body_indices, body_embeddings, strict=True)}
        documents: list[tuple[str, dict[str, Any]]] = []
        for index, (pending, compare_embedding) in enumerate(zip(pending_articles, compare_embeddings, strict=True)):
            updated_source = dict(pending.source)
            updated_source["compare_text"] = pending.compare_text
            updated_source["compare_text_hash"] = pending.text_hash
            updated_source["duplicate_comparison_embedding"] = compare_embedding
            updated_source["duplicate_title_embedding"] = title_map.get(index)
            updated_source["duplicate_summary_embedding"] = summary_map.get(index)
            updated_source["duplicate_body_embedding"] = body_map.get(index)
            documents.append((pending.document_id, updated_source))
        es_client.bulk_index(index=article_index, documents=documents)
        updates.extend(documents)
        pending_articles = []

    for document_id, source in articles:
        article = _normalize_article(source)
        compare_text, title_text, summary_text, body_text = _article_embedding_inputs(article)
        if not compare_text:
            skipped += 1
            continue
        text_hash = compare_text_hash(compare_text)
        existing_hash = source.get("compare_text_hash")
        existing_compare_text = source.get("compare_text")
        has_compare_embedding = _has_embedding(source.get("duplicate_comparison_embedding"))
        has_title_embedding = title_text is None or _has_embedding(source.get("duplicate_title_embedding"))
        has_summary_embedding = summary_text is None or _has_embedding(source.get("duplicate_summary_embedding"))
        has_body_embedding = body_text is None or _has_embedding(source.get("duplicate_body_embedding"))
        if (
            existing_hash == text_hash
            and existing_compare_text == compare_text
            and has_compare_embedding
            and has_title_embedding
            and has_summary_embedding
            and has_body_embedding
        ):
            skipped += 1
            continue

        pending_articles.append(
            PendingArticleEmbedding(
                document_id=document_id,
                source=dict(source),
                text_hash=text_hash,
                compare_text=compare_text,
                title_text=title_text,
                summary_text=summary_text,
                body_text=body_text,
            )
        )
        if len(pending_articles) >= batch_size:
            flush()

    flush()
    return BackfillStats(
        scanned_articles=len(articles),
        updated_articles=len(updates),
        skipped_articles=skipped,
    )


def backfill_chunk_embeddings(
    *,
    es_client: ElasticsearchClient,
    provider: EmbeddingProvider,
    task: str,
    article_index: str = "kcs-kb-articles-v1",
    chunk_index: str = "kcs-kb-article-chunks-v1",
    batch_size: int = 8,
) -> BackfillStats:
    create_chunk_index_if_missing(es_client, index_name=chunk_index)
    articles = _load_articles(es_client, index=article_index)
    total_chunks = 0
    skipped = 0

    for _, source in articles:
        article = _normalize_article(source)
        article_hash = source.get("compare_text_hash")
        compare_text = source.get("compare_text")
        if not isinstance(compare_text, str) or not compare_text.strip():
            compare_text = build_compare_text(article)
            article_hash = compare_text_hash(compare_text)

        if not isinstance(article_hash, str) or not article_hash:
            skipped += 1
            continue

        existing_chunk_count = es_client.count_documents(
            index=chunk_index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"article_id": article.article_id}},
                        {"term": {"compare_text_hash": article_hash}},
                    ]
                }
            },
        )
        if existing_chunk_count > 0:
            skipped += 1
            continue

        es_client.delete_by_query(
            index=chunk_index,
            query={"term": {"article_id": article.article_id}},
        )

        chunks = chunk_article_document(article)
        if not chunks:
            skipped += 1
            continue

        for offset in range(0, len(chunks), batch_size):
            chunk_batch = chunks[offset : offset + batch_size]
            vectors = provider.embed_batch([chunk.text for chunk in chunk_batch], task)
            documents: list[tuple[str, dict[str, Any]]] = []
            for chunk, vector in zip(chunk_batch, vectors, strict=True):
                document = ChunkDocument(
                    chunk_id=chunk.chunk_id,
                    article_id=article.article_id,
                    remote_document_id=article.remote_document_id,
                    chunk_ordinal=chunk.ordinal,
                    chunk_kind=chunk.chunk_kind,
                    chunk_heading=chunk.heading,
                    chunk_text=chunk.text,
                    chunk_word_count=chunk.word_count,
                    compare_text_hash=article_hash,
                    duplicate_comparison_embedding=vector,
                    source_updated_at=article.source_updated_at,
                    source_index=article.source_index,
                )
                documents.append((chunk.chunk_id, document.model_dump(mode="json", by_alias=True)))
            es_client.bulk_index(index=chunk_index, documents=documents)
            total_chunks += len(documents)

    return BackfillStats(
        scanned_articles=len(articles),
        updated_chunks=total_chunks,
        skipped_articles=skipped,
    )


def backfill_article_embeddings_from_env() -> BackfillStats:
    provider, task = create_duplicate_embedding_provider()
    return backfill_article_embeddings(
        es_client=ElasticsearchClient(base_url=get_target_es_url()),
        provider=provider,
        task=task,
        article_index=get_target_es_index(),
    )


def backfill_chunk_embeddings_from_env() -> BackfillStats:
    provider, task = create_duplicate_embedding_provider()
    return backfill_chunk_embeddings(
        es_client=ElasticsearchClient(base_url=get_target_es_url()),
        provider=provider,
        task=task,
        article_index=get_target_es_index(),
        chunk_index=get_target_chunk_index(),
    )
