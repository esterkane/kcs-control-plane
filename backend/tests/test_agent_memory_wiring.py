"""Recall-before-acting wiring: MEMORY_ENABLED off => no recall; on => recall + audit log."""

from __future__ import annotations

from typing import Any

from app.agents.authoring import AuthoringAgent
from app.agents.memory import EpisodicMemory, LocalDeterministicEmbedder
from app.agents.models import AgentProposal
from app.agents.reviewer import ReviewerAgent
from app.agents.supervisor import SupervisorAgent
from tests.agent_fixtures import (
    FakeClusterService,
    RecordingDraftRepository,
    RecordingEpisodeRepository,
    make_article,
    strong_approved_cluster,
)


def _article_reader(article_id: str):
    return make_article(article_id, title=f"Title {article_id}", summary="s", body="b")


class _RecordingProvider:
    """Captures the precedent passed into propose() so we can prove recall wiring."""

    provider_name = "recording"

    def __init__(self) -> None:
        self.precedents: list[str] = []

    def propose(self, cluster, *, precedent: str = "") -> AgentProposal:
        self.precedents.append(precedent)
        return AgentProposal(
            decision="approved_family",
            justification="fixed",
            confidence=0.99,
            provider="recording",
            model="recording",
        )


class _SpyMemoryStore:
    """Fake episode store recording whether search() was called, returning one neighbour."""

    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, *, index: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        self.search_calls += 1
        return [
            {
                "_score": 1.97,  # cosine 0.97 + 1.0
                "_source": {
                    "episode_id": "ep-precedent",
                    "cluster_id": "family-prior",
                    "inputs_summary": "prior",
                    "proposal": {"decision": "approved_family"},
                    "routing_decision": {"action": "auto_approve"},
                    "human_outcome": "approved_family",
                },
            }
        ]


def _build(provider, memory):
    cluster = strong_approved_cluster()
    service = FakeClusterService(cluster)
    supervisor = SupervisorAgent(
        cluster_service=service,
        reviewer=ReviewerAgent(cluster_service=service, reasoning_provider=provider),
        authoring_agent=AuthoringAgent(article_reader=_article_reader, draft_repository=RecordingDraftRepository()),
        episode_repository=RecordingEpisodeRepository(),
        memory=memory,
    )
    return supervisor, cluster


def test_memory_disabled_does_not_recall(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    monkeypatch.delenv("MEMORY_ENABLED", raising=False)  # default false
    provider = _RecordingProvider()
    store = _SpyMemoryStore()
    memory = EpisodicMemory(es_client=store, embedder=LocalDeterministicEmbedder(dims=64))
    supervisor, cluster = _build(provider, memory)

    outcome = supervisor.supervise(cluster.cluster_id)

    assert store.search_calls == 0  # no recall query issued
    assert provider.precedents == [""]  # reviewer got no precedent
    assert outcome is not None
    assert outcome.episode.recalled_episode_ids == []  # nothing recalled / logged


def test_memory_enabled_recalls_and_logs_recalled_ids(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    provider = _RecordingProvider()
    store = _SpyMemoryStore()
    memory = EpisodicMemory(es_client=store, embedder=LocalDeterministicEmbedder(dims=64))
    supervisor, cluster = _build(provider, memory)

    outcome = supervisor.supervise(cluster.cluster_id)

    assert store.search_calls == 1  # recall happened
    assert provider.precedents and "ep-precedent" not in provider.precedents[0]
    # Precedent text surfaced the recalled human outcome to the reviewer.
    assert "approved_family" in provider.precedents[0]
    assert "Precedent" in provider.precedents[0]
    # The recalled episode id is logged on the new episode for auditability.
    assert outcome is not None
    assert outcome.episode.recalled_episode_ids == ["ep-precedent"]
    # The new episode is itself embedded (so it is recallable later).
    assert len(outcome.episode.embedding) == 64


def test_memory_enabled_but_no_memory_injected_is_safe(monkeypatch) -> None:
    monkeypatch.setenv("AGENTS_ENABLED", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    provider = _RecordingProvider()
    supervisor, cluster = _build(provider, memory=None)

    outcome = supervisor.supervise(cluster.cluster_id)

    assert outcome is not None
    assert provider.precedents == [""]
    assert outcome.episode.recalled_episode_ids == []
    assert outcome.episode.embedding == []  # no embedder available, left empty
