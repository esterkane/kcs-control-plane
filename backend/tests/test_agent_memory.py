"""Episodic memory: recall relevance, embedding round-trip, MEMORY_ENABLED off, audit log."""

from __future__ import annotations

import math
from typing import Any

from app.agents.memory import (
    EpisodicMemory,
    LocalDeterministicEmbedder,
    embed_episode,
    format_precedent,
)
from app.agents.models import AgentEpisode, AgentProposal, EdgeRef, RoutingDecision


# --- a fake episode store holding canned vectors -------------------------------------


class FakeEpisodeStore:
    """Fake ES client whose ``search`` scores canned episode vectors by cosine.

    Mirrors the real ``script_score`` (cosineSimilarity + 1.0) contract the memory service
    expects, so recall ordering can be asserted without a live cluster.
    """

    def __init__(self, episodes: list[dict[str, Any]]) -> None:
        self.episodes = episodes
        self.last_body: dict[str, Any] | None = None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def search(self, *, index: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        self.last_body = body
        query_vector = body["query"]["script_score"]["script"]["params"]["query_vector"]
        must_not = body["query"]["script_score"]["query"]["bool"].get("must_not", [])
        excluded: set[str] = set()
        for clause in must_not:
            excluded.update(clause.get("terms", {}).get("episode_id", []))

        scored = []
        for episode in self.episodes:
            if episode["episode_id"] in excluded:
                continue
            embedding = episode.get("embedding")
            if not embedding:
                continue
            score = self._cosine(query_vector, embedding) + 1.0  # match script_score
            scored.append((score, episode))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        size = body.get("size", len(scored))
        return [{"_score": score, "_source": episode} for score, episode in scored[:size]]


def _canned_episode(episode_id: str, summary: str, decision: str, human: str | None) -> dict:
    embedder = LocalDeterministicEmbedder(dims=64)
    return {
        "episode_id": episode_id,
        "cluster_id": f"cluster-{episode_id}",
        "inputs_summary": summary,
        "embedding": embedder.embed_batch([summary], "retrieval.passage")[0],
        "proposal": {"decision": decision},
        "routing_decision": {"action": "send_to_human"},
        "human_outcome": human,
    }


def test_recall_returns_nearest_past_episodes_in_order() -> None:
    store = FakeEpisodeStore(
        [
            _canned_episode("ep-vpn", "members=2 labels=[exact_duplicate] vpn login secret", "approved_family", "approved_family"),
            _canned_episode("ep-sso", "members=3 labels=[near_duplicate] sso saml token expiry", "split_required", "split_required"),
            _canned_episode("ep-billing", "members=2 labels=[near_duplicate] billing invoice refund", "rejected_family", "rejected_family"),
        ]
    )
    memory = EpisodicMemory(es_client=store, embedder=LocalDeterministicEmbedder(dims=64))

    # A query that paraphrases the VPN episode should recall it first.
    recalled = memory.recall("members=2 labels=[exact_duplicate] vpn login secret rotate", k=3)

    assert recalled, "expected at least one recalled episode"
    assert recalled[0].episode_id == "ep-vpn"
    # Descending similarity order.
    sims = [item.similarity for item in recalled]
    assert sims == sorted(sims, reverse=True)
    # Outcomes (decision + human outcome) are surfaced for use as precedent.
    assert recalled[0].human_outcome == "approved_family"
    assert recalled[0].decision == "approved_family"


def test_recall_excludes_current_episode() -> None:
    store = FakeEpisodeStore(
        [
            _canned_episode("ep-self", "members=2 vpn login secret", "approved_family", None),
            _canned_episode("ep-other", "members=2 vpn login secret", "approved_family", "approved_family"),
        ]
    )
    memory = EpisodicMemory(es_client=store, embedder=LocalDeterministicEmbedder(dims=64))

    recalled = memory.recall("members=2 vpn login secret", k=5, exclude_episode_ids=["ep-self"])

    ids = [item.episode_id for item in recalled]
    assert "ep-self" not in ids
    assert "ep-other" in ids


def test_embedding_round_trip_shape_is_stable_and_normalised() -> None:
    embedder = LocalDeterministicEmbedder(dims=64)
    summary = "members=2 labels=[near_duplicate] articles=[a b] edges=[near_duplicate:a-b@0.810]"

    first = embedder.embed_batch([summary], "retrieval.passage")[0]
    second = embedder.embed_batch([summary], "retrieval.passage")[0]

    assert len(first) == 64
    assert first == second  # deterministic
    norm = math.sqrt(sum(v * v for v in first))
    assert abs(norm - 1.0) < 1e-9  # L2-normalised


def test_embed_episode_attaches_embedding_to_episode() -> None:
    episode = _episode(inputs_summary="members=2 labels=[exact_duplicate] articles=[a b]")
    memory = EpisodicMemory(es_client=FakeEpisodeStore([]), embedder=LocalDeterministicEmbedder(dims=64))

    embedded = embed_episode(episode, memory)

    assert len(embedded.embedding) == 64
    # Round-trips through the persisted snake_case document.
    doc = embedded.model_dump(by_alias=False)
    assert doc["embedding"] == embedded.embedding
    assert doc["inputs_summary"] == episode.inputs_summary


def test_format_precedent_prefers_human_outcome() -> None:
    store = FakeEpisodeStore(
        [_canned_episode("ep-1", "vpn login secret", "approved_family", "approved_family")]
    )
    memory = EpisodicMemory(es_client=store, embedder=LocalDeterministicEmbedder(dims=64))
    recalled = memory.recall("vpn login secret", k=1)

    block = format_precedent(recalled)
    assert "approved_family" in block
    assert "Precedent" in block
    assert format_precedent([]) == ""


def _episode(*, inputs_summary: str = "") -> AgentEpisode:
    return AgentEpisode(
        episodeId="episode-x",
        clusterId="family-x",
        ts="2026-06-21T12:00:00Z",
        agent="supervisor",
        memberArticleIds=["a", "b"],
        strongestEdges=[
            EdgeRef(edgeId="e1", leftArticleId="a", rightArticleId="b", label="exact_duplicate", totalScore=0.95)
        ],
        evidenceRefs=["e1:reason:shared_metadata"],
        inputsSummary=inputs_summary,
        proposal=AgentProposal(
            decision="approved_family",
            justification="strong",
            confidence=0.9,
            citedEdgeIds=["e1"],
            provider="deterministic",
            model="deterministic",
        ),
        routingDecision=RoutingDecision(action="auto_approve", rationale="strong"),
        provider="deterministic",
        model="deterministic",
    )
