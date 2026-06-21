"""Procedural learning: threshold recalibration is proposed, gated, applied-only-if-better."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.learning import (
    LabeledEdge,
    RecalibrationRejected,
    apply_recalibration,
    apply_recalibration as _apply,  # alias for clarity in asserts
    evaluate_threshold,
    labeled_edges_from_episodes,
    recalibrate,
)

FIXTURE = Path(__file__).resolve().parents[1] / "app" / "agents" / "fixtures" / "labeled_edges_episodes.json"


def _load() -> tuple[list[LabeledEdge], list[LabeledEdge]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        labeled_edges_from_episodes(data["train"]),
        labeled_edges_from_episodes(data["holdout"]),
    )


def test_only_decisive_human_outcomes_become_labeled_edges() -> None:
    train, _ = _load()
    # The pending_review episode (ep-t6) contributes NO labels.
    edge_ids = {edge.edge_id for edge in train}
    assert "e-t6a" not in edge_ids
    # approved -> positive, rejected/split -> negative.
    truths = {edge.edge_id: edge.truth for edge in train}
    assert truths["e-t1a"] == "positive"
    assert truths["e-t4a"] == "negative"
    assert truths["e-t5a"] == "negative"


def test_improving_candidate_is_proposed_and_applied() -> None:
    train, holdout = _load()

    proposal = recalibrate(current_threshold=0.84, train_edges=train, holdout_edges=holdout)

    # Lowering 0.84 -> 0.80 recovers human-approved near-duplicates without admitting the
    # human-rejected ~0.79 edges: precision stays 1.0, recall rises.
    assert proposal.proposed_threshold == 0.80
    assert proposal.should_apply is True

    current_overall = next(r for r in proposal.current if r.grouping == "overall")
    proposed_overall = next(r for r in proposal.proposed if r.grouping == "overall")
    assert proposed_overall.recall > current_overall.recall
    assert proposed_overall.precision >= current_overall.precision
    assert proposed_overall.f1 > current_overall.f1

    # The gated apply step returns the value to write to config.
    assert apply_recalibration(proposal) == 0.80


def test_worsening_candidate_is_rejected_not_applied() -> None:
    # Held-out set engineered so that LOWERING the threshold admits false positives:
    # there are human-rejected near-duplicate edges sitting at 0.80-0.82, so dropping
    # below them tanks precision. A learned change that worsens the gate must be rejected.
    train = [
        # On train, a naive sweep is tempted toward a low threshold to catch the 0.80 positive.
        LabeledEdge("p1", "near_duplicate", 0.90, "positive"),
        LabeledEdge("p2", "near_duplicate", 0.80, "positive"),
        LabeledEdge("n1", "near_duplicate", 0.79, "negative"),
    ]
    holdout = [
        LabeledEdge("hp1", "near_duplicate", 0.90, "positive"),
        # Many human-REJECTED edges cluster at 0.80-0.82: lowering the threshold to 0.80
        # would mark them all strong -> precision collapses.
        LabeledEdge("hn1", "near_duplicate", 0.82, "negative"),
        LabeledEdge("hn2", "near_duplicate", 0.81, "negative"),
        LabeledEdge("hn3", "near_duplicate", 0.80, "negative"),
    ]

    proposal = recalibrate(current_threshold=0.84, train_edges=train, holdout_edges=holdout)

    assert proposal.should_apply is False
    with pytest.raises(RecalibrationRejected):
        _apply(proposal)


def test_evaluate_threshold_reports_overall_and_real_grouping() -> None:
    _, holdout = _load()
    rows = evaluate_threshold(holdout, threshold=0.80)
    groupings = {row.grouping for row in rows}
    # Honest grouping: overall + the real per-label grouping (near_duplicate). No "topic".
    assert "overall" in groupings
    assert "near_duplicate" in groupings


def test_no_candidate_beats_current_keeps_current() -> None:
    # All positives already caught at the current threshold, no negatives near it:
    # nothing to gain, so propose keeps current and refuses to apply.
    edges = [
        LabeledEdge("p1", "exact_duplicate", 0.99, "positive"),
        LabeledEdge("p2", "near_duplicate", 0.95, "positive"),
        LabeledEdge("n1", "near_duplicate", 0.50, "negative"),
    ]
    proposal = recalibrate(current_threshold=0.84, train_edges=edges, holdout_edges=edges)

    assert proposal.proposed_threshold == 0.84
    assert proposal.should_apply is False
