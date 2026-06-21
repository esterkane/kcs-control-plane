"""AuthoringAgent: drafts a canonical merged article for an approved family.

This implements the README's previously-"not implemented" milestone — but as a DRAFT
ONLY. The draft is persisted to a dedicated drafts/episodes store
(``kcs-kb-agent-drafts-v1``). It is NEVER written back to the read-only source KB index
(``kcs-kb-articles-v1``); the repository hard-guards against that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Protocol

from app.agents.models import PROMPT_VERSION, AuthoringDraft
from app.clustering.service import ClusterDetailResponse
from app.config import (
    get_agent_draft_index,
    get_target_es_index,
)
from app.elasticsearch.client import ElasticsearchClient
from app.ingestion.kb import NormalizedKbDocument

AGENT_NAME = "authoring"

# The read-only source KB index drafts must never be written to.
SOURCE_KB_INDEX = get_target_es_index()  # "kcs-kb-articles-v1"


DRAFT_INDEX_MAPPING: dict[str, Any] = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "draft_id": {"type": "keyword"},
            "cluster_id": {"type": "keyword"},
            "title": {"type": "text"},
            "body_markdown": {"type": "text"},
            "member_article_ids": {"type": "keyword"},
            "representative_article_id": {"type": "keyword"},
            "provider": {"type": "keyword"},
            "model": {"type": "keyword"},
            "prompt_version": {"type": "keyword"},
            "generated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "status": {"type": "keyword"},
        },
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _draft_id(cluster_id: str) -> str:
    digest = sha1(cluster_id.encode("utf-8")).hexdigest()[:16]
    return f"draft-{digest}"


class ArticleReader(Protocol):
    def __call__(self, article_id: str) -> NormalizedKbDocument: ...


class DraftRepositoryProtocol(Protocol):
    def save(self, draft: AuthoringDraft) -> None: ...

    def get(self, draft_id: str) -> AuthoringDraft | None: ...


class DraftRepository:
    """Persists drafts to the dedicated drafts index via the existing ``_ensure_index``
    pattern. Refuses to ever target the source KB index."""

    def __init__(self, *, es_client: ElasticsearchClient, draft_index: str | None = None) -> None:
        self.es_client = es_client
        self.draft_index = draft_index or get_agent_draft_index()
        if self.draft_index == SOURCE_KB_INDEX:
            raise ValueError("Draft index must never be the read-only source KB index.")

    def _ensure_index(self) -> None:
        if not self.es_client.index_exists(index=self.draft_index):
            self.es_client.create_index(index=self.draft_index, mapping=DRAFT_INDEX_MAPPING)

    def save(self, draft: AuthoringDraft) -> None:
        self._ensure_index()
        self.es_client.bulk_index(
            index=self.draft_index,
            documents=[(draft.draft_id, draft.model_dump(by_alias=False))],
        )

    def get(self, draft_id: str) -> AuthoringDraft | None:
        document = self.es_client.get_document(index=self.draft_index, document_id=draft_id)
        return AuthoringDraft.model_validate(document) if document else None


class AuthoringAgent:
    def __init__(
        self,
        *,
        article_reader: ArticleReader,
        draft_repository: DraftRepositoryProtocol,
        provider_name: str = "deterministic",
        model_name: str = "deterministic",
    ) -> None:
        self.article_reader = article_reader
        self.draft_repository = draft_repository
        self.provider_name = provider_name
        self.model_name = model_name

    def draft_for_cluster(self, cluster: ClusterDetailResponse) -> AuthoringDraft:
        """Draft a canonical merged article from the member articles and persist it.

        DRAFT ONLY: the result is written to the drafts store, never the source KB index.
        Provenance (member ids + representative) is preserved on the draft.
        """
        members = [self.article_reader(article_id) for article_id in cluster.article_ids]
        representative = next(
            (article for article in members if article.article_id == cluster.representative_article_id),
            members[0] if members else None,
        )
        title = (
            (representative.title if representative else None)
            or cluster.representative_title
            or f"Merged family {cluster.cluster_id}"
        )
        body = self._merge_body(cluster=cluster, members=members)
        draft = AuthoringDraft(
            draftId=_draft_id(cluster.cluster_id),
            clusterId=cluster.cluster_id,
            title=title,
            bodyMarkdown=body,
            memberArticleIds=list(cluster.article_ids),
            representativeArticleId=cluster.representative_article_id,
            provider=self.provider_name,
            model=self.model_name,
            promptVersion=PROMPT_VERSION,
            generatedAt=_now_iso(),
        )
        self.draft_repository.save(draft)
        return draft

    def _merge_body(
        self,
        *,
        cluster: ClusterDetailResponse,
        members: list[NormalizedKbDocument],
    ) -> str:
        """Deterministically merge member bodies into a single canonical draft body."""
        lines: list[str] = []
        lines.append(f"# Canonical draft for family {cluster.cluster_id}")
        lines.append("")
        lines.append(
            "> DRAFT — merged from "
            f"{len(members)} member article(s); not written to the source KB."
        )
        lines.append("")
        for article in members:
            lines.append(f"## Source: {article.title or article.article_id} ({article.article_id})")
            if article.summary:
                lines.append("")
                lines.append(article.summary.strip())
            if article.body_markdown:
                lines.append("")
                lines.append(article.body_markdown.strip())
            lines.append("")
        lines.append("---")
        lines.append(
            "Provenance: members="
            + ", ".join(cluster.article_ids)
            + f"; representative={cluster.representative_article_id}."
        )
        return "\n".join(lines).strip() + "\n"


def build_article_reader(es_client: ElasticsearchClient, *, article_index: str | None = None) -> ArticleReader:
    """Read-only article reader over the source KB index (no writes)."""
    index = article_index or SOURCE_KB_INDEX

    def _read(article_id: str) -> NormalizedKbDocument:
        hits = es_client.search(
            index=index,
            body={"size": 1, "query": {"term": {"article_id": article_id}}},
        )
        if not hits:
            raise ValueError(f"Article not found: {article_id}")
        source = hits[0].get("_source")
        if not isinstance(source, dict):
            raise ValueError(f"Article source missing for {article_id}")
        return NormalizedKbDocument.model_validate(source)

    return _read
