"""AuthoringAgent: DRAFT-only invariant — never writes the source KB index."""

from __future__ import annotations

import pytest

from app.agents.authoring import (
    SOURCE_KB_INDEX,
    AuthoringAgent,
    DraftRepository,
)
from tests.agent_fixtures import (
    RecordingDraftRepository,
    make_article,
    strong_approved_cluster,
)


class SpyEsClient:
    """Records every index touched by a write (create_index / bulk_index / create_document)."""

    def __init__(self) -> None:
        self.written_indices: list[str] = []
        self._indices: set[str] = set()

    def index_exists(self, *, index: str) -> bool:
        return index in self._indices

    def create_index(self, *, index: str, mapping) -> None:
        self.written_indices.append(index)
        self._indices.add(index)

    def bulk_index(self, *, index: str, documents) -> None:
        self.written_indices.append(index)

    def create_document(self, *, index: str, document_id: str, document) -> None:
        self.written_indices.append(index)

    def get_document(self, *, index: str, document_id: str):
        return None


def _reader(article_id: str):
    return make_article(article_id, title=f"Title {article_id}", summary="summary", body="body text")


def test_draft_contains_merged_body_and_provenance() -> None:
    cluster = strong_approved_cluster()
    drafts = RecordingDraftRepository()
    agent = AuthoringAgent(article_reader=_reader, draft_repository=drafts)

    draft = agent.draft_for_cluster(cluster)

    assert draft.status == "draft"
    assert draft.member_article_ids == cluster.article_ids
    assert draft.representative_article_id == cluster.representative_article_id
    # Provenance + every member body merged into the draft.
    for article_id in cluster.article_ids:
        assert article_id in draft.body_markdown
    assert "Provenance" in draft.body_markdown
    assert drafts.saved == [draft]


def test_draft_repository_never_writes_source_kb_index() -> None:
    cluster = strong_approved_cluster()
    spy = SpyEsClient()
    repository = DraftRepository(es_client=spy)  # type: ignore[arg-type]
    agent = AuthoringAgent(article_reader=_reader, draft_repository=repository)

    agent.draft_for_cluster(cluster)

    assert spy.written_indices, "expected the draft to be persisted somewhere"
    # The source KB index is NEVER among the written indices.
    assert SOURCE_KB_INDEX not in spy.written_indices
    assert all(index != SOURCE_KB_INDEX for index in spy.written_indices)


def test_draft_repository_rejects_source_index_target() -> None:
    spy = SpyEsClient()
    with pytest.raises(ValueError):
        DraftRepository(es_client=spy, draft_index=SOURCE_KB_INDEX)  # type: ignore[arg-type]
