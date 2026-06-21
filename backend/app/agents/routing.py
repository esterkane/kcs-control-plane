"""Pure routing function mapping (reviewer proposal, cluster signals) -> routing action.

This function is PURE and fully testable: no IO, no service calls. The SupervisorAgent
applies its result. The four actions:

- ``auto_approve``  — high edge-confidence AND the reviewer proposes ``approved_family``.
                      The supervisor persists ``approved_family`` and attaches a draft.
- ``split``         — the reviewer proposes ``split_required``.
- ``reject``        — the reviewer proposes ``rejected_family`` with sufficient confidence.
- ``send_to_human`` — the ambiguous middle: ``pending_review``, low confidence, or an
                      approve/reject proposal that does not clear its threshold. The
                      supervisor does NOT change review state here.
"""

from __future__ import annotations

from typing import Any

from app.agents.models import AgentProposal, RoutingDecision

# Auto-approval requires BOTH a high-confidence proposal AND strong structural evidence.
AUTO_APPROVE_MIN_CONFIDENCE = 0.8
AUTO_APPROVE_MIN_EDGE_SCORE = 0.84
REJECT_MIN_CONFIDENCE = 0.55


def route_proposal(proposal: AgentProposal, signals: dict[str, Any]) -> RoutingDecision:
    """Map a reviewer proposal + deterministic cluster signals to a routing action."""
    decision = proposal.decision
    confidence = proposal.confidence
    max_edge_score = float(signals.get("max_edge_score", 0.0))

    if decision == "split_required":
        return RoutingDecision(
            action="split",
            rationale=(
                "Reviewer proposed split_required; routing to split "
                f"(max edge score={max_edge_score:.3f})."
            ),
        )

    if decision == "approved_family":
        if confidence >= AUTO_APPROVE_MIN_CONFIDENCE and max_edge_score >= AUTO_APPROVE_MIN_EDGE_SCORE:
            return RoutingDecision(
                action="auto_approve",
                rationale=(
                    "High-confidence approved_family with strong edges "
                    f"(confidence={confidence:.3f} >= {AUTO_APPROVE_MIN_CONFIDENCE}, "
                    f"max edge score={max_edge_score:.3f} >= {AUTO_APPROVE_MIN_EDGE_SCORE}); auto-approving."
                ),
            )
        return RoutingDecision(
            action="send_to_human",
            rationale=(
                "approved_family but below auto-approve bar "
                f"(confidence={confidence:.3f}, max edge score={max_edge_score:.3f}); sending to a human."
            ),
        )

    if decision == "rejected_family":
        if confidence >= REJECT_MIN_CONFIDENCE:
            return RoutingDecision(
                action="reject",
                rationale=(
                    f"Reviewer proposed rejected_family with confidence={confidence:.3f} "
                    f">= {REJECT_MIN_CONFIDENCE}; routing to reject."
                ),
            )
        return RoutingDecision(
            action="send_to_human",
            rationale=(
                f"rejected_family but low confidence ({confidence:.3f} < {REJECT_MIN_CONFIDENCE}); "
                "sending to a human."
            ),
        )

    # pending_review (the ambiguous middle) — always a human decision.
    return RoutingDecision(
        action="send_to_human",
        rationale=(
            f"Reviewer proposed pending_review (confidence={confidence:.3f}); "
            "leaving for a human."
        ),
    )
