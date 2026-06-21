"""Routing logic tests — every branch (auto_approve / send_to_human / split / reject)."""

from __future__ import annotations

from app.agents.models import AgentProposal
from app.agents.routing import (
    AUTO_APPROVE_MIN_CONFIDENCE,
    AUTO_APPROVE_MIN_EDGE_SCORE,
    REJECT_MIN_CONFIDENCE,
    route_proposal,
)


def _proposal(decision: str, confidence: float) -> AgentProposal:
    return AgentProposal(
        decision=decision,  # type: ignore[arg-type]
        justification="test",
        confidence=confidence,
        provider="deterministic",
        model="deterministic",
    )


def test_approved_high_confidence_strong_edges_auto_approves() -> None:
    decision = route_proposal(
        _proposal("approved_family", 0.9),
        {"max_edge_score": 0.95},
    )
    assert decision.action == "auto_approve"


def test_approved_low_confidence_goes_to_human() -> None:
    decision = route_proposal(
        _proposal("approved_family", AUTO_APPROVE_MIN_CONFIDENCE - 0.01),
        {"max_edge_score": 0.95},
    )
    assert decision.action == "send_to_human"


def test_approved_weak_edges_goes_to_human() -> None:
    decision = route_proposal(
        _proposal("approved_family", 0.95),
        {"max_edge_score": AUTO_APPROVE_MIN_EDGE_SCORE - 0.01},
    )
    assert decision.action == "send_to_human"


def test_split_required_routes_to_split() -> None:
    decision = route_proposal(_proposal("split_required", 0.62), {"max_edge_score": 0.9})
    assert decision.action == "split"


def test_rejected_high_confidence_routes_to_reject() -> None:
    decision = route_proposal(
        _proposal("rejected_family", REJECT_MIN_CONFIDENCE + 0.01),
        {"max_edge_score": 0.4},
    )
    assert decision.action == "reject"


def test_rejected_low_confidence_goes_to_human() -> None:
    decision = route_proposal(
        _proposal("rejected_family", REJECT_MIN_CONFIDENCE - 0.01),
        {"max_edge_score": 0.4},
    )
    assert decision.action == "send_to_human"


def test_pending_review_goes_to_human() -> None:
    decision = route_proposal(_proposal("pending_review", 0.5), {"max_edge_score": 0.8})
    assert decision.action == "send_to_human"


def test_auto_approve_requires_both_confidence_and_edge_score() -> None:
    # High confidence but boundary-low edge score must NOT auto-approve.
    low_edges = route_proposal(_proposal("approved_family", 0.99), {"max_edge_score": 0.5})
    assert low_edges.action == "send_to_human"
    # Strong edges but boundary-low confidence must NOT auto-approve.
    low_conf = route_proposal(_proposal("approved_family", 0.1), {"max_edge_score": 0.99})
    assert low_conf.action == "send_to_human"


def test_missing_max_edge_score_defaults_to_zero_and_is_safe() -> None:
    decision = route_proposal(_proposal("approved_family", 0.99), {})
    assert decision.action == "send_to_human"
