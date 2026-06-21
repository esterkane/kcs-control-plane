"""Agreement eval: ReviewerAgent (deterministic) vs. recorded human decisions.

Runs fully offline against a committed labeled fixture
(``app/agents/fixtures/agreement_clusters.json``): a held-out set of clusters that each
carry a ``humanReviewState``. The eval runs the deterministic ReviewerAgent over each
cluster and measures overall accuracy plus a per-class confusion over the 4 ReviewState
labels.

A runner (``python -m app.agents.eval``) prints and optionally writes the report.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agents.providers import DeterministicReasoningProvider
from app.clustering.service import ClusterDetailResponse, ReviewState

LABELS: tuple[ReviewState, ...] = (
    "approved_family",
    "pending_review",
    "rejected_family",
    "split_required",
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agreement_clusters.json"


class LabeledCluster(BaseModel):
    human_review_state: ReviewState = Field(alias="humanReviewState")
    cluster: ClusterDetailResponse

    model_config = {"populate_by_name": True}


class PerClassMetric(BaseModel):
    label: str
    support: int
    correct: int
    accuracy: float


class AgreementReport(BaseModel):
    total: int
    correct: int
    accuracy: float
    per_class: list[PerClassMetric] = Field(alias="perClass")
    confusion: dict[str, dict[str, int]]

    model_config = {"populate_by_name": True}


def load_labeled_clusters(path: Path = FIXTURE_PATH) -> list[LabeledCluster]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [LabeledCluster.model_validate(item) for item in raw]


def evaluate_agreement(
    labeled: list[LabeledCluster],
    *,
    provider: DeterministicReasoningProvider | None = None,
) -> AgreementReport:
    """Run the deterministic reviewer over the labeled set and compute agreement."""
    reasoning = provider or DeterministicReasoningProvider()
    confusion: dict[str, dict[str, int]] = {
        human: {predicted: 0 for predicted in LABELS} for human in LABELS
    }
    support: dict[str, int] = defaultdict(int)
    per_class_correct: dict[str, int] = defaultdict(int)
    correct = 0

    for item in labeled:
        proposal = reasoning.propose(item.cluster)
        human = item.human_review_state
        predicted = proposal.decision
        confusion[human][predicted] += 1
        support[human] += 1
        if predicted == human:
            correct += 1
            per_class_correct[human] += 1

    total = len(labeled)
    per_class = [
        PerClassMetric(
            label=label,
            support=support[label],
            correct=per_class_correct[label],
            accuracy=round(per_class_correct[label] / support[label], 4) if support[label] else 0.0,
        )
        for label in LABELS
    ]
    return AgreementReport(
        total=total,
        correct=correct,
        accuracy=round(correct / total, 4) if total else 0.0,
        perClass=per_class,
        confusion=confusion,
    )


def render_markdown(report: AgreementReport) -> str:
    lines = [
        "# ReviewerAgent agreement vs. human decisions (deterministic provider)",
        "",
        f"- Clusters: {report.total}",
        f"- Overall accuracy: {report.accuracy:.4f} ({report.correct}/{report.total})",
        "",
        "## Per-class",
        "",
        "| Label | Support | Correct | Accuracy |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric in report.per_class:
        lines.append(
            f"| {metric.label} | {metric.support} | {metric.correct} | {metric.accuracy:.4f} |"
        )
    lines.append("")
    lines.append("## Confusion (rows = human, cols = predicted)")
    lines.append("")
    lines.append("| human \\ predicted | " + " | ".join(LABELS) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in LABELS) + " |")
    for human in LABELS:
        row = " | ".join(str(report.confusion[human][predicted]) for predicted in LABELS)
        lines.append(f"| {human} | {row} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReviewerAgent agreement eval (offline).")
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)

    labeled = load_labeled_clusters(args.fixture)
    report = evaluate_agreement(labeled)

    payload: dict[str, Any] = report.model_dump(by_alias=True)
    print(json.dumps(payload, indent=2))
    print()
    print(render_markdown(report))

    if args.output_json is not None:
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
