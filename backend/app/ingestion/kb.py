from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import (
    IngestSummary,
    get_duplicate_embedding_dims,
    get_source_es_api_key,
    get_source_es_index,
    get_source_es_url,
    get_target_es_index,
    get_target_es_url,
)
from app.elasticsearch.client import ElasticsearchClient
from app.text_sanitize import sanitize_text

TARGET_INDEX_NAME = "kcs-kb-articles-v1"
TARGET_EMBEDDING_DIMS = get_duplicate_embedding_dims()
PLACEHOLDER_VALUES = {"", "-", "null", "none", "unknown"}
PUBLISHED_STATES = {"published"}
ARCHIVED_STATES = {"archived"}
EXPORT_ONLY_FIELDS = {"_score", "_ignored", "_ingestion_errors"}
PRESERVED_ENRICHMENT_FIELDS = (
    "compare_text",
    "compare_text_hash",
    "duplicate_comparison_embedding",
    "duplicate_title_embedding",
    "duplicate_summary_embedding",
    "duplicate_body_embedding",
)

WORKFLOW_STATE_FIELDS = (
    "workflow_state",
    "workflowState",
    "status",
    "state",
    "publication_state",
    "lifecycle_state",
)
ARCHIVED_FIELDS = (
    "archived",
    "is_archived",
    "isArchived",
)
UPDATED_AT_FIELDS = (
    "updated_at",
    "updatedAt",
    "modified_at",
    "modifiedAt",
    "modified_date",
    "salesforce_last_modified_date",
    "last_updated_at",
    "lastUpdatedAt",
    "created_date",
)


class NormalizedKbDocument(BaseModel):
    article_id: str = Field(alias="article_id")
    remote_document_id: str = Field(alias="remote_document_id")
    title: str | None
    summary: str | None
    body_markdown: str | None = Field(alias="body_markdown")
    symptoms: str | None
    category: str | None
    visibility_external: bool | None = Field(alias="visibility_external")
    visibility_was_published: bool | None = Field(alias="visibility_was_published")
    visibility_was_checked_in: bool | None = Field(alias="visibility_was_checked_in")
    products: list[str]
    components: list[str]
    product_versions: list[str] = Field(alias="product_versions")
    deployments: list[str]
    platforms: list[str]
    ai_summary: str | None = Field(alias="ai_summary")
    ai_subtitle: str | None = Field(alias="ai_subtitle")
    ai_questions: list[str] = Field(alias="ai_questions")
    ai_tags: list[str] = Field(alias="ai_tags")
    source_updated_at: str | None = Field(alias="source_updated_at")
    source_index: str = Field(alias="source_index")
    compare_text: str | None = Field(default=None, alias="compare_text")
    compare_text_hash: str | None = Field(default=None, alias="compare_text_hash")
    duplicate_comparison_embedding: list[float] | None = Field(
        default=None,
        alias="duplicate_comparison_embedding",
    )
    duplicate_title_embedding: list[float] | None = Field(
        default=None,
        alias="duplicate_title_embedding",
    )
    duplicate_summary_embedding: list[float] | None = Field(
        default=None,
        alias="duplicate_summary_embedding",
    )
    duplicate_body_embedding: list[float] | None = Field(
        default=None,
        alias="duplicate_body_embedding",
    )

    model_config = {"populate_by_name": True}

    @field_validator(
        "article_id",
        "remote_document_id",
        "title",
        "summary",
        "body_markdown",
        "symptoms",
        "category",
        "ai_summary",
        "ai_subtitle",
        "source_updated_at",
        "source_index",
        "compare_text",
        "compare_text_hash",
        mode="before",
    )
    @classmethod
    def _sanitize_string_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return sanitize_text(value)
        return value

    @field_validator(
        "products",
        "components",
        "product_versions",
        "deployments",
        "platforms",
        "ai_questions",
        "ai_tags",
        mode="before",
    )
    @classmethod
    def _sanitize_list_fields(cls, value: object) -> object:
        if isinstance(value, list):
            return [sanitize_text(item) if isinstance(item, str) else item for item in value]
        return value


TARGET_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "article_id": {"type": "keyword"},
            "remote_document_id": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "body_markdown": {"type": "text"},
            "symptoms": {"type": "text"},
            "category": {"type": "keyword"},
            "visibility_external": {"type": "boolean"},
            "visibility_was_published": {"type": "boolean"},
            "visibility_was_checked_in": {"type": "boolean"},
            "products": {"type": "keyword"},
            "components": {"type": "keyword"},
            "product_versions": {"type": "keyword"},
            "deployments": {"type": "keyword"},
            "platforms": {"type": "keyword"},
            "ai_summary": {"type": "text"},
            "ai_subtitle": {"type": "text"},
            "ai_questions": {"type": "text"},
            "ai_tags": {"type": "keyword"},
            "source_updated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "source_index": {"type": "keyword"},
            "compare_text": {"type": "text"},
            "compare_text_hash": {"type": "keyword"},
            "duplicate_comparison_embedding": {
                "type": "dense_vector",
                "dims": TARGET_EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "duplicate_title_embedding": {
                "type": "dense_vector",
                "dims": TARGET_EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "duplicate_summary_embedding": {
                "type": "dense_vector",
                "dims": TARGET_EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "duplicate_body_embedding": {
                "type": "dense_vector",
                "dims": TARGET_EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
        },
    },
}


@dataclass(frozen=True)
class IngestionResult:
    fetched_documents: int
    indexed_documents: int
    skipped_documents: int


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = sanitize_text(str(value)).strip()
    if text.casefold() in PLACEHOLDER_VALUES:
        return None
    return text or None


def _normalize_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value)
    if text is None:
        return None
    lowered = text.casefold()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def _deduplicate_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return _deduplicate_strings(str(item) for item in value)
    if isinstance(value, dict):
        return _deduplicate_strings(
            str(item)
            for item in value.values()
            if _normalize_text(item) is not None
        )
    text = _normalize_text(value)
    if text is None:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return _normalize_list(parsed)

    if any(delimiter in text for delimiter in ("|", ";", "\n")):
        parts = [part.strip() for part in text.replace("\n", ";").replace("|", ";").split(";")]
        return _deduplicate_strings(part for part in parts)

    return [text]


def _first_text(source: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        if field_name in EXPORT_ONLY_FIELDS:
            continue
        value = _normalize_text(source.get(field_name))
        if value is not None:
            return value
    return None


def _first_bool(source: Mapping[str, Any], *field_names: str) -> bool | None:
    for field_name in field_names:
        value = _normalize_bool(source.get(field_name))
        if value is not None:
            return value
    return None


def _first_list(source: Mapping[str, Any], *field_names: str) -> list[str]:
    for field_name in field_names:
        values = _normalize_list(source.get(field_name))
        if values:
            return values
    return []


def _ai_fields(source: Mapping[str, Any]) -> Mapping[str, Any]:
    raw_ai_fields = source.get("ai_fields")
    if isinstance(raw_ai_fields, Mapping):
        return raw_ai_fields
    return {}


def _workflow_state(source: Mapping[str, Any]) -> str | None:
    for field_name in WORKFLOW_STATE_FIELDS:
        value = _normalize_text(source.get(field_name))
        if value is not None:
            return value.casefold()
    return None


def _is_archived(source: Mapping[str, Any]) -> bool:
    if _workflow_state(source) in ARCHIVED_STATES:
        return True
    return any(_normalize_bool(source.get(field_name)) is True for field_name in ARCHIVED_FIELDS)


def should_index_document(hit: Mapping[str, Any]) -> bool:
    remote_document_id = _normalize_text(hit.get("_id"))
    if remote_document_id is None:
        return False
    if remote_document_id.casefold().endswith("-draft"):
        return False

    source = hit.get("_source")
    if not isinstance(source, Mapping):
        return False
    if _is_archived(source):
        return False

    workflow_state = _workflow_state(source)
    if workflow_state is not None and workflow_state not in PUBLISHED_STATES:
        return False

    article_id = _normalize_text(source.get("id"))
    return article_id is not None


def normalize_document(hit: Mapping[str, Any], *, source_index: str) -> NormalizedKbDocument | None:
    if not should_index_document(hit):
        return None

    source = hit["_source"]
    assert isinstance(source, Mapping)
    ai_fields = _ai_fields(source)
    article_id = _normalize_text(source.get("id"))
    remote_document_id = _normalize_text(hit.get("_id"))
    assert article_id is not None
    assert remote_document_id is not None

    return NormalizedKbDocument(
        article_id=article_id,
        remote_document_id=remote_document_id,
        title=_first_text(source, "title", "content_title", "name"),
        summary=_first_text(source, "summary", "content_summary", "article_summary", "description"),
        body_markdown=_first_text(
            source,
            "body_markdown",
            "content_body",
            "body",
            "content",
            "markdown",
        ),
        symptoms=_first_text(source, "symptoms", "content_symptoms"),
        category=_first_text(source, "category"),
        visibility_external=_first_bool(source, "visibility_external", "external_visibility", "is_external"),
        visibility_was_published=_first_bool(source, "visibility_was_published", "was_published"),
        visibility_was_checked_in=_first_bool(source, "visibility_was_checked_in", "was_checked_in"),
        products=_first_list(source, "products", "product_names", "metadata_products"),
        components=_first_list(source, "components", "metadata_components"),
        product_versions=_first_list(
            source,
            "product_versions",
            "versions",
            "metadata_product_versions",
            "metadata_deployment_versions",
        ),
        deployments=_first_list(source, "deployments", "metadata_deployments"),
        platforms=_first_list(source, "platforms", "metadata_platforms"),
        ai_summary=_first_text(source, "ai_summary") or _first_text(ai_fields, "ai_summary", "summary"),
        ai_subtitle=_first_text(source, "ai_subtitle") or _first_text(ai_fields, "ai_subtitle", "subtitle"),
        ai_questions=_first_list(source, "ai_questions") or _first_list(
            ai_fields,
            "ai_questions",
            "ai_questions_answered",
            "questions",
        ),
        ai_tags=_first_list(source, "ai_tags") or _first_list(ai_fields, "ai_tags", "tags"),
        source_updated_at=_first_text(source, *UPDATED_AT_FIELDS),
        source_index=source_index,
    )


def create_target_index_if_missing(client: ElasticsearchClient, *, index_name: str = TARGET_INDEX_NAME) -> None:
    if client.index_exists(index=index_name):
        client.put_mapping(
            index=index_name,
            mapping={"properties": TARGET_INDEX_MAPPING["mappings"]["properties"]},
        )
        return
    client.create_index(index=index_name, mapping=TARGET_INDEX_MAPPING)


def _merge_preserved_enrichment(
    *,
    normalized_documents: list[tuple[str, dict[str, Any]]],
    existing_documents: Mapping[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    merged: list[tuple[str, dict[str, Any]]] = []
    for document_id, normalized_source in normalized_documents:
        existing_source = existing_documents.get(document_id, {})
        merged_source = dict(normalized_source)
        for field_name in PRESERVED_ENRICHMENT_FIELDS:
            value = existing_source.get(field_name)
            if value is not None:
                merged_source[field_name] = value
        merged.append((document_id, merged_source))
    return merged


def run_full_ingestion(
    *,
    source_client: ElasticsearchClient,
    target_client: ElasticsearchClient,
    source_index: str,
    target_index: str = TARGET_INDEX_NAME,
    batch_size: int = 250,
    pit_keep_alive: str = "1m",
) -> IngestionResult:
    create_target_index_if_missing(target_client, index_name=target_index)
    pit_id = source_client.open_point_in_time(index=source_index, keep_alive=pit_keep_alive)
    search_after: list[Any] | None = None
    fetched_documents = 0
    indexed_documents = 0

    try:
        while True:
            page = source_client.search_with_pit(
                pit_id=pit_id,
                keep_alive=pit_keep_alive,
                size=batch_size,
                search_after=search_after,
            )
            pit_id = page.pit_id
            if not page.hits:
                break

            fetched_documents += len(page.hits)
            normalized_documents: list[tuple[str, dict[str, Any]]] = []
            for hit in page.hits:
                document = normalize_document(hit, source_index=source_index)
                if document is None:
                    continue
                normalized_documents.append(
                    (
                        document.remote_document_id,
                        document.model_dump(mode="json", by_alias=True),
                    )
                )

            existing_documents = target_client.get_documents_by_ids(
                index=target_index,
                document_ids=[document_id for document_id, _ in normalized_documents],
            )
            merged_documents = _merge_preserved_enrichment(
                normalized_documents=normalized_documents,
                existing_documents=existing_documents,
            )
            target_client.bulk_index(index=target_index, documents=merged_documents)
            indexed_documents += len(merged_documents)
            search_after = page.hits[-1].get("sort")
            if not isinstance(search_after, list):
                search_after = None
    finally:
        source_client.close_point_in_time(pit_id=pit_id)

    return IngestionResult(
        fetched_documents=fetched_documents,
        indexed_documents=indexed_documents,
        skipped_documents=fetched_documents - indexed_documents,
    )


def ingest_kb_articles(*, full: bool) -> IngestSummary:
    if not full:
        raise ValueError("Only full ingestion is supported at this stage")

    source_index = get_source_es_index()
    target_index = get_target_es_index()
    result = run_full_ingestion(
        source_client=ElasticsearchClient(
            base_url=get_source_es_url(),
            api_key=get_source_es_api_key(),
        ),
        target_client=ElasticsearchClient(base_url=get_target_es_url()),
        source_index=source_index,
        target_index=target_index,
    )
    return IngestSummary(
        sourceIndex=source_index,
        targetIndex=target_index,
        fetchedDocuments=result.fetched_documents,
        indexedDocuments=result.indexed_documents,
        skippedDocuments=result.skipped_documents,
    )
