"""Procedural learning: recalibrate the duplicate-edge strong threshold, gated.

The threshold recalibrated is the duplicate-edge *strong* threshold ``min_total_score``
used by ``clustering.service._is_strong_near_duplicate`` (default ``STRONG_SCORE`` 0.84
in ``agents.providers``). A candidate threshold classifies an edge as a strong duplicate
when ``total_score >= threshold`` (exact-duplicate edges are always strong, mirroring the
clustering service, so they are excluded from the threshold sweep).

Grouping (honest note): edges/articles carry NO genuine "topic" field. The only real
per-edge grouping dimension is the edge ``label`` (``exact_duplicate`` |
``near_duplicate``). Since exact-duplicate edges bypass the score threshold entirely,
the recalibration is reported **per near_duplicate label and overall** — there is no
invented topic dimension.

Ground truth comes from accumulated human decisions (episodes whose ``human_outcome`` is
set):
- ``approved_family``                  -> the cluster's edges WERE true duplicates (positive)
- ``rejected_family`` / ``split_required`` -> the strong-duplicate claim was WRONG (negative)
Episodes with ``pending_review`` or no human outcome carry no label and are ignored.

The flow is propose -> evaluate on a held-out split -> **apply only if it improves**:
``recalibrate`` returns a proposal + before/after precision/recall report and a boolean
``should_apply``. It NEVER mutates ``ClusterThresholds``. ``apply_recalibration`` is a
separate, explicit step that refuses to write unless the gate said it improves.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "labeled_edges_episodes.json"

# A labeled edge derived from a human-reviewed episode.
EdgeTruth = Literal["positive", "negative"]


@dataclass(frozen=True)
class LabeledEdge:
    """One edge with the human-derived truth and the fields the threshold reads."""

    edge_id: str
    label: str  # "exact_duplicate" | "near_duplicate" — the real grouping dimension
    total_score: float
    truth: EdgeTruth


class PrecisionRecall(BaseModel):
    threshold: float
    grouping: str
    support: int
    true_positive: int = Field(alias="truePositive")
    false_positive: int = Field(alias="falsePositive")
    false_negative: int = Field(alias="falseNegative")
    precision: float
    recall: float
    f1: float

    model_config = {"populate_by_name": True}


class ThresholdProposal(BaseModel):
    current_threshold: float = Field(alias="currentThreshold")
    proposed_threshold: float = Field(alias="proposedThreshold")
    should_apply: bool = Field(alias="shouldApply")
    rationale: str
    current: list[PrecisionRecall]
    proposed: list[PrecisionRecall]

    model_config = {"populate_by_name": True}


# Edges with these human outcomes are treated as positives; rejected/split as negatives.
_POSITIVE_OUTCOMES = {"approved_family"}
_NEGATIVE_OUTCOMES = {"rejected_family", "split_required"}


def labeled_edges_from_episodes(episodes: Iterable[dict]) -> list[LabeledEdge]:
    """Derive labeled edges from human-reviewed episode documents (snake_case dicts).

    Reuses the strongest_edges already recorded on each episode. Only episodes whose
    ``human_outcome`` is a decisive positive/negative contribute labels.
    """
    labeled: list[LabeledEdge] = []
    for episode in episodes:
        outcome = episode.get("human_outcome")
        if outcome in _POSITIVE_OUTCOMES:
            truth: EdgeTruth = "positive"
        elif outcome in _NEGATIVE_OUTCOMES:
            truth = "negative"
        else:
            continue
        for edge in episode.get("strongest_edges", []) or []:
            labeled.append(
                LabeledEdge(
                    edge_id=str(edge.get("edge_id", "")),
                    label=str(edge.get("label", "")),
                    total_score=float(edge.get("total_score", 0.0)),
                    truth=truth,
                )
            )
    return labeled


def _classify_strong(edge: LabeledEdge, *, threshold: float) -> bool:
    """A candidate strong-duplicate classifier: exact edges always strong, else score gate."""
    if edge.label == "exact_duplicate":
        return True
    return edge.total_score >= threshold


def _metrics(edges: list[LabeledEdge], *, threshold: float, grouping: str) -> PrecisionRecall:
    tp = fp = fn = 0
    for edge in edges:
        predicted_strong = _classify_strong(edge, threshold=threshold)
        if edge.truth == "positive" and predicted_strong:
            tp += 1
        elif edge.truth == "negative" and predicted_strong:
            fp += 1
        elif edge.truth == "positive" and not predicted_strong:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return PrecisionRecall(
        threshold=round(threshold, 4),
        grouping=grouping,
        support=len(edges),
        truePositive=tp,
        falsePositive=fp,
        falseNegative=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
    )


def evaluate_threshold(edges: list[LabeledEdge], *, threshold: float) -> list[PrecisionRecall]:
    """Precision/recall per real grouping (near_duplicate label) + overall.

    exact_duplicate edges are not score-gated, so a per-near_duplicate row plus an overall
    row is the honest reporting (no invented topic dimension).
    """
    near = [edge for edge in edges if edge.label == "near_duplicate"]
    rows = [_metrics(edges, threshold=threshold, grouping="overall")]
    if near:
        rows.append(_metrics(near, threshold=threshold, grouping="near_duplicate"))
    return rows


def _overall(rows: list[PrecisionRecall]) -> PrecisionRecall:
    for row in rows:
        if row.grouping == "overall":
            return row
    return rows[0]


@dataclass
class RecalibrationConfig:
    """Sweep + gate parameters."""

    candidate_thresholds: list[float] = field(
        default_factory=lambda: [round(0.78 + 0.01 * step, 2) for step in range(0, 16)]
    )
    # A candidate is accepted only if overall F1 strictly improves AND neither overall
    # precision nor overall recall regresses below the current threshold's.
    min_f1_gain: float = 0.0


def recalibrate(
    *,
    current_threshold: float,
    train_edges: list[LabeledEdge],
    holdout_edges: list[LabeledEdge],
    config: RecalibrationConfig | None = None,
) -> ThresholdProposal:
    """Propose a recalibrated threshold and GATE it on held-out precision/recall.

    Picks the best candidate threshold by overall F1 on the *train* split, then evaluates
    BOTH the current and the proposed threshold on the *held-out* split. ``should_apply``
    is true only if, on the held-out split, the proposed threshold strictly improves
    overall F1 and does not regress overall precision or recall. Never mutates config.
    """
    cfg = config or RecalibrationConfig()

    # 1) Choose the best candidate on the training split (by overall F1).
    best_threshold = current_threshold
    best_f1 = _overall(evaluate_threshold(train_edges, threshold=current_threshold)).f1
    for candidate in cfg.candidate_thresholds:
        candidate_f1 = _overall(evaluate_threshold(train_edges, threshold=candidate)).f1
        if candidate_f1 > best_f1:
            best_f1 = candidate_f1
            best_threshold = candidate

    # 2) Evaluate current vs proposed on the HELD-OUT split (the gate).
    current_rows = evaluate_threshold(holdout_edges, threshold=current_threshold)
    proposed_rows = evaluate_threshold(holdout_edges, threshold=best_threshold)
    current_overall = _overall(current_rows)
    proposed_overall = _overall(proposed_rows)

    improves_f1 = proposed_overall.f1 > current_overall.f1 + cfg.min_f1_gain
    no_precision_regression = proposed_overall.precision >= current_overall.precision
    no_recall_regression = proposed_overall.recall >= current_overall.recall
    should_apply = (
        best_threshold != current_threshold
        and improves_f1
        and no_precision_regression
        and no_recall_regression
    )

    if should_apply:
        rationale = (
            f"Held-out overall F1 {current_overall.f1:.3f} -> {proposed_overall.f1:.3f} "
            f"(precision {current_overall.precision:.3f} -> {proposed_overall.precision:.3f}, "
            f"recall {current_overall.recall:.3f} -> {proposed_overall.recall:.3f}); "
            f"proposing threshold {current_threshold} -> {best_threshold}."
        )
    elif best_threshold == current_threshold:
        rationale = (
            f"No candidate beat the current threshold {current_threshold} on training F1; "
            "keeping current threshold."
        )
    else:
        rationale = (
            f"Candidate {best_threshold} did NOT improve the held-out gate "
            f"(F1 {current_overall.f1:.3f} -> {proposed_overall.f1:.3f}, "
            f"precision {current_overall.precision:.3f} -> {proposed_overall.precision:.3f}, "
            f"recall {current_overall.recall:.3f} -> {proposed_overall.recall:.3f}); rejected."
        )

    return ThresholdProposal(
        currentThreshold=current_threshold,
        proposedThreshold=best_threshold,
        shouldApply=should_apply,
        rationale=rationale,
        current=current_rows,
        proposed=proposed_rows,
    )


class RecalibrationRejected(RuntimeError):
    """Raised if apply is attempted on a proposal whose gate did not improve metrics."""


def apply_recalibration(proposal: ThresholdProposal) -> float:
    """Explicit, gated apply step: return the threshold to write to config.

    Refuses (raises) unless the proposal's gate said it improves precision/recall. This is
    the ONLY function callers use to act on a proposal; it never silently mutates the
    clustering thresholds — it returns the value the caller persists to config (e.g. the
    ``min_total_score`` env/getter), and only when the gate passed.
    """
    if not proposal.should_apply:
        raise RecalibrationRejected(
            "Refusing to apply: the recalibration did not improve held-out precision/recall. "
            f"{proposal.rationale}"
        )
    return proposal.proposed_threshold


def render_markdown(proposal: ThresholdProposal) -> str:
    lines = [
        "# Duplicate-edge threshold recalibration (proposed, gated)",
        "",
        f"- Current threshold: {proposal.current_threshold}",
        f"- Proposed threshold: {proposal.proposed_threshold}",
        f"- Apply: {'YES' if proposal.should_apply else 'NO (rejected)'}",
        f"- Rationale: {proposal.rationale}",
        "",
        "## Held-out precision/recall (current vs proposed)",
        "",
        "| Grouping | Threshold | Support | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tag, rows in (("current", proposal.current), ("proposed", proposal.proposed)):
        for row in rows:
            lines.append(
                f"| {tag}/{row.grouping} | {row.threshold} | {row.support} | "
                f"{row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} |"
            )
    return "\n".join(lines) + "\n"


def load_split(path: Path = FIXTURE_PATH) -> tuple[list[LabeledEdge], list[LabeledEdge]]:
    """Load (train, holdout) labeled edges from the committed offline fixture."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return (
        labeled_edges_from_episodes(data["train"]),
        labeled_edges_from_episodes(data["holdout"]),
    )


def main(argv: list[str] | None = None) -> int:
    """Offline runner: propose + gate a recalibration over the committed fixture.

    Prints the proposal JSON + markdown report. Never mutates config — applying is an
    explicit separate step (``apply_recalibration``) only valid when the gate improves.
    """
    parser = argparse.ArgumentParser(description="Duplicate-edge threshold recalibration (offline, gated).")
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--current-threshold", type=float, default=0.84)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)

    train, holdout = load_split(args.fixture)
    proposal = recalibrate(
        current_threshold=args.current_threshold,
        train_edges=train,
        holdout_edges=holdout,
    )
    payload = proposal.model_dump(by_alias=True)
    print(json.dumps(payload, indent=2))
    print()
    print(render_markdown(proposal))
    if args.output_json is not None:
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_markdown(proposal), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
