"""SupervisorAgent: routing -> persistence policy, episode logging, feature-flag isolation."""

from __future__ import annotations

import pytest

from app.agents.authoring import AuthoringAgent
from app.agents.models import AgentProposal
from app.agents.reviewer import ReviewerAgent
from app.agents.supervisor import SupervisorAgent
from tests.agent_fixtures import (
    FakeClusterService,
    RecordingDraftRepository,
    RecordingEpisodeRepository,
    make_article,
    make_cluster,
    make_edge,
    strong_approved_cluster,
)


def _article_reader(article_id: str):
    return make_article(article_id, title=f"Title {article_id}", summary="s", body="b")


class _FixedProvider:
    provider_name = "fixed"

    def __init__(self, decision: str, confidence: float = 0.99) -> None:
        self._decision = decision
        self._confidence = confidence

    def propose(self, cluster, *, precedent: str = "") -> AgentProposal:
        self.last_precedent = precedent
        return AgentProposal(
            decision=self._decision,  # type: ignore[arg-type]
            justification="fixed",
            confidence=self._confidence,
            provider="fixed",
            model="fixed",
        )


def _build_supervisor(cluster, provider) -> tuple[SupervisorAgent, FakeClusterService, RecordingDraftRepository, RecordingEpisodeRepository]:
    service = FakeClusterService(cluster)
    drafts = RecordingDraftRepository()
    episodes = RecordingEpisodeRepository()
    supervisor = SupervisorAgent(
        cluster_service=service,
        reviewer=ReviewerAgent(cluster_service=service, reasoning_provider=provider),
        authoring_agent=AuthoringAgent(article_reader=_article_reader, draft_repository=drafts),
        episode_repository=episodes,
    )
    return supervisor, service, drafts, episodes


def test_disabled_by_default_is_noop(monkeypatch) -> None:
    monkeypatch.delenv("AGENTS_ENABLED", raising=False)
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("approved_family"))

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome is None
    # Nothing persisted, nothing logged, no draft.
    assert service.review_updates == []
    assert drafts.saved == []
    assert episodes.logged == []


def test_auto_approve_persists_state_and_attaches_draft(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("approved_family"))

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome is not None
    assert outcome.routing_decision.action == "auto_approve"
    assert outcome.review_state_persisted == "approved_family"
    assert service.review_updates == [
        {"cluster_id": cluster.cluster_id, "review_state": "approved_family"}
    ]
    assert len(drafts.saved) == 1
    assert outcome.draft is not None
    assert outcome.episode.draft_id == drafts.saved[0].draft_id
    assert len(episodes.logged) == 1


def test_split_persists_split_state_no_draft(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("split_required"))

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome.routing_decision.action == "split"
    assert outcome.review_state_persisted == "split_required"
    assert service.review_updates[0]["review_state"] == "split_required"
    assert drafts.saved == []
    assert outcome.draft is None


def test_reject_persists_rejected_state_no_draft(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("rejected_family"))

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome.routing_decision.action == "reject"
    assert outcome.review_state_persisted == "rejected_family"
    assert drafts.saved == []


def test_send_to_human_does_not_change_state(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    # pending_review -> always send_to_human.
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("pending_review"))

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome.routing_decision.action == "send_to_human"
    assert outcome.review_state_persisted is None
    # The ambiguous middle leaves review state untouched (humans in the loop).
    assert service.review_updates == []
    assert drafts.saved == []


def test_approved_but_low_confidence_sends_to_human_not_auto_approve(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(
        cluster, _FixedProvider("approved_family", confidence=0.5)
    )

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome.routing_decision.action == "send_to_human"
    assert service.review_updates == []


def test_episode_logged_with_full_shape(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    cluster = strong_approved_cluster()
    supervisor, service, drafts, episodes = _build_supervisor(cluster, _FixedProvider("approved_family"))

    supervisor.supervise(cluster.cluster_id)

    assert len(episodes.logged) == 1
    episode = episodes.logged[0]
    assert episode.cluster_id == cluster.cluster_id
    assert episode.agent == "supervisor"
    assert episode.member_article_ids == cluster.article_ids
    assert episode.strongest_edges  # strongest edges captured
    assert episode.evidence_refs  # evidence refs captured (not fabricated)
    assert episode.proposal.decision == "approved_family"
    assert episode.routing_decision.action == "auto_approve"
    assert episode.human_outcome is None  # filled later by a human
    assert episode.provider == "fixed"
    # Serialises to a snake_case document for ES.
    doc = episode.model_dump(by_alias=False)
    assert doc["cluster_id"] == cluster.cluster_id
    assert "routing_decision" in doc
