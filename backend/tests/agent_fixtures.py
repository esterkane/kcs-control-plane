"""Shared builders for agent tests (no live ES, no network).

Produces ``ClusterDetailResponse`` objects and fakes mirroring the existing
``test_mcp_tools.py`` / ``test_explanation_feature_flags.py`` fake-service style.
"""

from __future__ import annotations

from typing import Any

from app.agents.models import AgentEpisode, AuthoringDraft
from app.clustering.service import ClusterDetailResponse
from app.config import ClusterReviewUpdateRequest
from app.ingestion.kb import NormalizedKbDocument


def make_edge(
    edge_id: str,
    left: str,
    right: str,
    label: str,
    total: float,
    *,
    art_emb: float | None = None,
    best_chunk: float = 0.7,
    title: float = 0.6,
    meta: float = 0.7,
) -> dict[str, Any]:
    if art_emb is None:
        art_emb = max(total, 0.8)
    return {
        "edgeId": edge_id,
        "leftArticleId": left,
        "rightArticleId": right,
        "label": label,
        "accepted": True,
        "totalScore": total,
        "pairScores": {
            "rrfScore": 0.1,
            "articleEmbeddingSimilarity": art_emb,
            "bestChunkSimilarity": best_chunk,
            "titleSimilarity": title,
            "summarySimilarity": 0.5,
            "metadataAgreement": meta,
            "rerankScore": total,
            "totalScore": total,
        },
        "evidence": {
            "sharedMetadata": {"products": ["Cloud"]},
            "mostSimilarChunks": [],
            "reasons": ["shared_metadata"],
        },
        "sourceQueryArticleId": left,
        "sourceCandidateArticleId": right,
        "materializedAt": "2026-04-28T12:00:00Z",
    }


def make_cluster(
    cluster_id: str,
    article_ids: list[str],
    edges: list[dict[str, Any]],
    *,
    rep: str | None = None,
    state: str = "pending_review",
) -> ClusterDetailResponse:
    rep = rep or article_ids[0]
    payload = {
        "clusterId": cluster_id,
        "articleIds": article_ids,
        "edgeIds": [edge["edgeId"] for edge in edges],
        "memberCount": len(article_ids),
        "reviewState": state,
        "representativeArticleId": rep,
        "representativeTitle": f"Title {rep}",
        "memberships": [
            {
                "articleId": article_id,
                "title": f"Title {article_id}",
                "supportingEdgeIds": [
                    edge["edgeId"]
                    for edge in edges
                    if article_id in (edge["leftArticleId"], edge["rightArticleId"])
                ],
                "reasons": ["shared_metadata"],
                "sharedMetadata": {"products": ["Cloud"]},
            }
            for article_id in article_ids
        ],
        "thresholds": {
            "topN": 12,
            "includeCve": False,
            "includeChunkSeed": True,
            "maxComponentSize": 12,
            "weakEdgeThreshold": 0.78,
            "analysisMode": "graph",
        },
        "materializedAt": "2026-04-28T12:00:00Z",
        "edges": edges,
    }
    return ClusterDetailResponse.model_validate(payload)


def strong_approved_cluster() -> ClusterDetailResponse:
    return make_cluster(
        "family-strong",
        ["a", "b", "c"],
        [
            make_edge("e1", "a", "b", "exact_duplicate", 0.95),
            make_edge("e2", "b", "c", "exact_duplicate", 0.93),
            make_edge("e3", "a", "c", "exact_duplicate", 0.92),
        ],
        rep="a",
    )


def make_article(article_id: str, *, title: str, summary: str, body: str) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": article_id,
            "remote_document_id": f"remote-{article_id}",
            "title": title,
            "summary": summary,
            "body_markdown": body,
            "symptoms": None,
            "category": "How To",
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": ["Cloud"],
            "components": [],
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": None,
            "source_index": "kb-articles-source-index",
        }
    )


class FakeClusterService:
    """Read + write fake for the cluster service used by the reviewer and supervisor.

    Records every ``update_cluster_review_state`` call so tests can assert the supervisor's
    persistence policy.
    """

    def __init__(self, cluster: ClusterDetailResponse | None) -> None:
        self._cluster = cluster
        self.review_updates: list[dict[str, str]] = []

    def get_cluster(self, cluster_id: str) -> ClusterDetailResponse | None:
        if self._cluster is not None and cluster_id == self._cluster.cluster_id:
            return self._cluster
        return None

    def list_clusters(self, *, size: int = 20, page: int = 1, review_state: str | None = None):
        raise NotImplementedError

    def update_cluster_review_state(
        self, *, cluster_id: str, request: ClusterReviewUpdateRequest
    ) -> ClusterDetailResponse | None:
        self.review_updates.append({"cluster_id": cluster_id, "review_state": request.review_state})
        return self._cluster


class RecordingDraftRepository:
    def __init__(self) -> None:
        self.saved: list[AuthoringDraft] = []

    def save(self, draft: AuthoringDraft) -> None:
        self.saved.append(draft)

    def get(self, draft_id: str) -> AuthoringDraft | None:
        return next((draft for draft in self.saved if draft.draft_id == draft_id), None)


class RecordingEpisodeRepository:
    def __init__(self) -> None:
        self.logged: list[AgentEpisode] = []

    def log(self, episode: AgentEpisode) -> None:
        self.logged.append(episode)
