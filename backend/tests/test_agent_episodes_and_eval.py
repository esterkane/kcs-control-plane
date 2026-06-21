"""Episode repository persistence shape + agreement-eval numbers on the committed fixture."""

from __future__ import annotations

from app.agents.episodes import EpisodeRepository
from app.agents.eval import evaluate_agreement, load_labeled_clusters
from app.agents.models import AgentEpisode, AgentProposal, EdgeRef, RoutingDecision


class SpyEsClient:
    def __init__(self) -> None:
        self._indices: set[str] = set()
        self.bulk_calls: list[tuple[str, list]] = []
        self.created_indices: list[str] = []

    def index_exists(self, *, index: str) -> bool:
        return index in self._indices

    def create_index(self, *, index: str, mapping) -> None:
        self._indices.add(index)
        self.created_indices.append(index)

    def bulk_index(self, *, index: str, documents) -> None:
        self.bulk_calls.append((index, documents))


def _episode() -> AgentEpisode:
    return AgentEpisode(
        episodeId="episode-1",
        clusterId="family-1",
        ts="2026-04-28T12:00:00Z",
        agent="supervisor",
        memberArticleIds=["a", "b"],
        strongestEdges=[
            EdgeRef(edgeId="e1", leftArticleId="a", rightArticleId="b", label="exact_duplicate", totalScore=0.95)
        ],
        evidenceRefs=["e1:reason:shared_metadata"],
        proposal=AgentProposal(
            decision="approved_family",
            justification="strong",
            confidence=0.9,
            citedEdgeIds=["e1"],
            provider="deterministic",
            model="deterministic",
        ),
        routingDecision=RoutingDecision(action="auto_approve", rationale="strong"),
        draftId="draft-1",
        humanOutcome=None,
        provider="deterministic",
        model="deterministic",
    )


def test_episode_repository_creates_index_and_persists_document() -> None:
    spy = SpyEsClient()
    repository = EpisodeRepository(es_client=spy, episode_index="kcs-kb-agent-episodes-v1")  # type: ignore[arg-type]

    repository.log(_episode())

    assert spy.created_indices == ["kcs-kb-agent-episodes-v1"]
    assert len(spy.bulk_calls) == 1
    index, documents = spy.bulk_calls[0]
    assert index == "kcs-kb-agent-episodes-v1"
    doc_id, doc = documents[0]
    assert doc_id == "episode-1"
    # Persisted in snake_case with human_outcome present (null) for the learning loop.
    assert doc["cluster_id"] == "family-1"
    assert doc["routing_decision"]["action"] == "auto_approve"
    assert doc["human_outcome"] is None


def test_episode_repository_does_not_recreate_existing_index() -> None:
    spy = SpyEsClient()
    spy._indices.add("kcs-kb-agent-episodes-v1")
    repository = EpisodeRepository(es_client=spy, episode_index="kcs-kb-agent-episodes-v1")  # type: ignore[arg-type]

    repository.log(_episode())

    assert spy.created_indices == []
    assert len(spy.bulk_calls) == 1


# --- agreement eval on the committed fixture (offline, deterministic provider) --------


def test_agreement_eval_matches_hand_computed_numbers() -> None:
    labeled = load_labeled_clusters()
    report = evaluate_agreement(labeled)

    # 8 clusters; 6 agree with the recorded human decisions.
    assert report.total == 8
    assert report.correct == 6
    assert report.accuracy == 0.75

    per_class = {metric.label: metric for metric in report.per_class}
    assert per_class["approved_family"].support == 3
    assert per_class["approved_family"].correct == 2
    assert per_class["approved_family"].accuracy == round(2 / 3, 4)

    assert per_class["pending_review"].support == 2
    assert per_class["pending_review"].correct == 1
    assert per_class["pending_review"].accuracy == 0.5

    assert per_class["rejected_family"].support == 1
    assert per_class["rejected_family"].correct == 1
    assert per_class["rejected_family"].accuracy == 1.0

    assert per_class["split_required"].support == 2
    assert per_class["split_required"].correct == 2
    assert per_class["split_required"].accuracy == 1.0


def test_agreement_eval_confusion_matrix_is_exact() -> None:
    report = evaluate_agreement(load_labeled_clusters())
    confusion = report.confusion

    # Disagreements: one human-approved predicted pending; one human-pending predicted approved.
    assert confusion["approved_family"]["approved_family"] == 2
    assert confusion["approved_family"]["pending_review"] == 1
    assert confusion["pending_review"]["approved_family"] == 1
    assert confusion["pending_review"]["pending_review"] == 1
    assert confusion["rejected_family"]["rejected_family"] == 1
    assert confusion["split_required"]["split_required"] == 2
    # No spurious cross-class predictions.
    assert confusion["split_required"]["approved_family"] == 0
    assert confusion["rejected_family"]["split_required"] == 0
