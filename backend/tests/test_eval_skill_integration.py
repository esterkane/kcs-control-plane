"""Offline tests for the relevance-eval skill integration.

No live Elasticsearch: the skill is exercised with a fake ``search_fn`` (canned
similar-article rankings) over the committed judgments + thresholds, and the
adapter is exercised with a fake similar-article service (canned hits). The skill
itself (``relevance_eval``) is the only thing actually run end-to-end here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval.skill_adapter import STRATEGY_FLAGS, make_search_fn
from app.similarity.service import (
    PairScores,
    SimilarArticleCandidate,
    SimilarEvidence,
    SimilarSearchRequest,
    SimilarSearchResponse,
)

relevance_eval = pytest.importorskip(
    "relevance_eval",
    reason="install the optional eval extra: pip install -e 'backend/.[eval]'",
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "app" / "eval"
JUDGMENTS_PATH = EVAL_DIR / "judgments.example.json"
THRESHOLDS_PATH = EVAL_DIR / "thresholds.example.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- (a) run_evaluation over committed judgments + thresholds with a fake search_fn ---


def _perfect_search_fn(judgments: dict):
    """A fake search that returns the judged duplicates first, best grade first —
    i.e. a retriever that gets every seed exactly right."""

    def search(article_id: str, strategy: str) -> list[str]:
        value = judgments[article_id]
        if isinstance(value, dict):
            return sorted(value, key=lambda doc_id: value[doc_id], reverse=True)
        return list(value)

    return search


def _empty_search_fn(article_id: str, strategy: str) -> list[str]:
    """A fake retriever that finds nothing — every metric is 0.0."""
    return []


def test_run_evaluation_report_shape_over_committed_files() -> None:
    judgments = _load(JUDGMENTS_PATH)
    strategies = sorted(STRATEGY_FLAGS)

    report = relevance_eval.run_evaluation(
        judgments, _perfect_search_fn(judgments), strategies, ks=(1, 3, 5, 10)
    )

    assert report["queries"] == len(judgments)
    assert report["ks"] == [1, 3, 5, 10]
    assert set(report["strategies"]) == set(strategies)
    for strategy in strategies:
        metrics = report["strategies"][strategy]["metrics"]
        # default metrics: precision / mrr / ndcg, each keyed by str(k).
        assert {"precision", "mrr", "ndcg"} <= set(metrics)
        assert set(metrics["precision"]) == {"1", "3", "5", "10"}


def test_perfect_retriever_passes_committed_thresholds() -> None:
    judgments = _load(JUDGMENTS_PATH)
    thresholds = relevance_eval.load_thresholds(str(THRESHOLDS_PATH))
    strategies = sorted(STRATEGY_FLAGS)

    report = relevance_eval.run_evaluation(
        judgments, _perfect_search_fn(judgments), strategies, ks=(1, 3, 5, 10)
    )
    gate = relevance_eval.evaluate_thresholds(report, thresholds)

    # A retriever that returns the judged duplicates first scores 1.0 everywhere,
    # so every committed threshold passes.
    assert gate["passed"] is True
    assert gate["checks"]
    for check in gate["checks"]:
        assert check["passed"] is True


def test_empty_retriever_fails_committed_thresholds() -> None:
    judgments = _load(JUDGMENTS_PATH)
    thresholds = relevance_eval.load_thresholds(str(THRESHOLDS_PATH))
    strategies = sorted(STRATEGY_FLAGS)

    report = relevance_eval.run_evaluation(
        judgments, _empty_search_fn, strategies, ks=(1, 3, 5, 10)
    )
    gate = relevance_eval.evaluate_thresholds(report, thresholds)

    # Finds nothing => every metric 0.0 => gate fails.
    assert gate["passed"] is False


def test_report_renders_to_json_and_markdown() -> None:
    judgments = _load(JUDGMENTS_PATH)
    report = relevance_eval.run_evaluation(
        judgments, _perfect_search_fn(judgments), sorted(STRATEGY_FLAGS), ks=(1, 3)
    )
    gate = relevance_eval.evaluate_thresholds(
        report, relevance_eval.load_thresholds(str(THRESHOLDS_PATH))
    )

    rendered_json = relevance_eval.to_json(report)
    markdown = relevance_eval.to_markdown(report, gate, title="Duplicate-retrieval evaluation")

    assert json.loads(rendered_json)["strategies"]  # valid, round-trips
    assert "Duplicate-retrieval evaluation" in markdown
    assert "chunk_seeded" in markdown


# --- (b) adapter over a fake similar-article service -----------------------------


def _candidate(article_id: str) -> SimilarArticleCandidate:
    return SimilarArticleCandidate(
        articleId=article_id,
        label="near_duplicate",
        title=f"Title {article_id}",
        summary=None,
        pairScores=PairScores(
            rrfScore=0.1,
            articleEmbeddingSimilarity=0.8,
            bestChunkSimilarity=0.6,
            titleSimilarity=0.7,
            summarySimilarity=0.5,
            metadataAgreement=0.5,
            rerankScore=0.7,
            totalScore=0.8,
        ),
        evidence=SimilarEvidence(
            sharedMetadata={},
            mostSimilarChunks=[],
            reasons=["shared_metadata"],
        ),
    )


class FakeSimilarityService:
    """Returns canned candidate ids and records the request it was given so the
    test can assert which flags a strategy selected."""

    def __init__(self, candidate_ids: list[str]) -> None:
        self._candidate_ids = candidate_ids
        self.requests: list[SimilarSearchRequest] = []

    def search(self, request: SimilarSearchRequest) -> SimilarSearchResponse:
        self.requests.append(request)
        candidates = [_candidate(article_id) for article_id in self._candidate_ids]
        return SimilarSearchResponse(
            queryArticleId=request.article_id,
            candidateCount=len(candidates),
            candidates=candidates,
        )


def test_adapter_extracts_ranked_candidate_ids() -> None:
    service = FakeSimilarityService(["dup-a", "dup-b", "dup-c"])
    search = make_search_fn(service)

    result = search("seed-1", "embedding")

    assert result == ["dup-a", "dup-b", "dup-c"]
    # the seed article id is forwarded as the query.
    assert service.requests[0].article_id == "seed-1"


def test_embedding_strategy_selects_no_chunk_seed() -> None:
    service = FakeSimilarityService(["dup-a"])
    search = make_search_fn(service)

    search("seed-1", "embedding")

    request = service.requests[0]
    assert request.include_chunk_seed is False
    assert request.include_cve is False


def test_chunk_seeded_strategy_selects_chunk_seed() -> None:
    service = FakeSimilarityService(["dup-a"])
    search = make_search_fn(service)

    search("seed-1", "chunk_seeded")

    request = service.requests[0]
    assert request.include_chunk_seed is True
    assert request.include_cve is False


def test_adapter_limit_is_forwarded() -> None:
    service = FakeSimilarityService(["dup-a"])
    search = make_search_fn(service, limit=7)

    search("seed-1", "embedding")

    assert service.requests[0].limit == 7


def test_adapter_rejects_unknown_strategy() -> None:
    service = FakeSimilarityService(["dup-a"])
    search = make_search_fn(service)

    with pytest.raises(ValueError, match="Unknown strategy"):
        search("seed-1", "not_a_strategy")
    # the service must not be called for an unknown strategy.
    assert service.requests == []
