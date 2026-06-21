"""ReviewerAgent + deterministic reasoning provider + provider swappability."""

from __future__ import annotations

from app.agents.models import AgentProposal
from app.agents.providers import DeterministicReasoningProvider
from app.agents.reviewer import ReviewerAgent
from tests.agent_fixtures import FakeClusterService, make_cluster, make_edge, strong_approved_cluster


def test_deterministic_strong_fully_connected_is_approved() -> None:
    cluster = strong_approved_cluster()
    proposal = DeterministicReasoningProvider().propose(cluster)
    assert proposal.decision == "approved_family"
    assert proposal.confidence >= 0.7
    # Justification cites edges/scores it used.
    assert proposal.cited_edge_ids
    assert "score" in proposal.justification


def test_deterministic_two_components_is_split() -> None:
    cluster = make_cluster(
        "family-2comp",
        ["a", "b", "c", "d"],
        [
            make_edge("e1", "a", "b", "exact_duplicate", 0.95),
            make_edge("e2", "c", "d", "exact_duplicate", 0.94),
        ],
    )
    assert DeterministicReasoningProvider().propose(cluster).decision == "split_required"


def test_deterministic_meaningful_bridge_is_split() -> None:
    cluster = make_cluster(
        "family-2tri",
        ["a", "b", "c", "d", "e", "f"],
        [
            make_edge("e1", "a", "b", "exact_duplicate", 0.95),
            make_edge("e2", "b", "c", "exact_duplicate", 0.94),
            make_edge("e3", "a", "c", "exact_duplicate", 0.93),
            make_edge("e4", "d", "e", "exact_duplicate", 0.95),
            make_edge("e5", "e", "f", "exact_duplicate", 0.94),
            make_edge("e6", "d", "f", "exact_duplicate", 0.93),
            make_edge("e7", "c", "d", "near_duplicate", 0.79, art_emb=0.79, best_chunk=0.5, title=0.5, meta=0.5),
        ],
    )
    assert DeterministicReasoningProvider().propose(cluster).decision == "split_required"


def test_deterministic_weak_sparse_is_rejected() -> None:
    cluster = make_cluster(
        "family-weak",
        ["s", "t"],
        [make_edge("e1", "s", "t", "near_duplicate", 0.70, art_emb=0.70, best_chunk=0.4, title=0.4, meta=0.4)],
    )
    assert DeterministicReasoningProvider().propose(cluster).decision == "rejected_family"


def test_deterministic_mixed_is_pending_review() -> None:
    cluster = make_cluster(
        "family-mixed",
        ["u", "v"],
        [make_edge("e1", "u", "v", "near_duplicate", 0.80, art_emb=0.80, best_chunk=0.5, title=0.5, meta=0.5)],
    )
    assert DeterministicReasoningProvider().propose(cluster).decision == "pending_review"


def test_single_strong_pair_is_approved_not_split() -> None:
    # A 2-member family on one strong edge must not be treated as a removable-bridge split.
    cluster = make_cluster(
        "family-pair",
        ["p", "q"],
        [make_edge("e1", "p", "q", "near_duplicate", 0.90, art_emb=0.9, best_chunk=0.8, title=0.7, meta=0.8)],
    )
    assert DeterministicReasoningProvider().propose(cluster).decision == "approved_family"


def test_reviewer_fetches_via_tools_and_returns_proposal() -> None:
    cluster = strong_approved_cluster()
    service = FakeClusterService(cluster)
    reviewer = ReviewerAgent(cluster_service=service)
    fetched, proposal = reviewer.review_cluster(cluster.cluster_id)
    assert fetched.cluster_id == cluster.cluster_id
    assert proposal.decision == "approved_family"


class _FakeProvider:
    provider_name = "fake"

    def __init__(self, decision: str) -> None:
        self._decision = decision

    def propose(self, cluster) -> AgentProposal:
        return AgentProposal(
            decision=self._decision,  # type: ignore[arg-type]
            justification="injected",
            confidence=0.99,
            provider="fake",
            model="fake",
        )


def test_provider_is_swappable_via_injection() -> None:
    cluster = strong_approved_cluster()
    reviewer = ReviewerAgent(
        cluster_service=FakeClusterService(cluster),
        reasoning_provider=_FakeProvider("rejected_family"),
    )
    _, proposal = reviewer.review_cluster(cluster.cluster_id)
    # Injected provider overrides the deterministic default.
    assert proposal.decision == "rejected_family"
    assert proposal.provider == "fake"
