from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from app.config import (
    ClusterReviewUpdateRequest,
    ClusterMaterializationRequest,
    get_target_duplicate_cluster_index,
    get_target_duplicate_edge_index,
    get_target_es_index,
    get_target_es_url,
)
from app.elasticsearch.client import ElasticsearchClient
from app.reranking.providers import StubRerankerProvider
from app.similarity.service import (
    PairScores,
    SimilarArticleCandidate,
    SimilarArticleService,
    SimilarEvidence,
    SimilarSearchRequest,
)

AcceptedPairLabel = Literal["exact_duplicate", "near_duplicate"]
ReviewState = Literal["pending_review", "approved_family", "rejected_family", "split_required"]

ACCEPTED_LABELS: set[str] = {"exact_duplicate", "near_duplicate"}


class ClusterThresholds(BaseModel):
    top_n: int = Field(alias="topN")
    include_cve: bool = Field(alias="includeCve")
    include_chunk_seed: bool = Field(alias="includeChunkSeed")
    max_component_size: int = Field(alias="maxComponentSize")
    weak_edge_threshold: float = Field(alias="weakEdgeThreshold")
    analysis_mode: str = Field(alias="analysisMode")

    model_config = {"populate_by_name": True}


class DuplicateEdgeDocument(BaseModel):
    edge_id: str = Field(alias="edgeId")
    left_article_id: str = Field(alias="leftArticleId")
    right_article_id: str = Field(alias="rightArticleId")
    label: AcceptedPairLabel
    accepted: bool
    total_score: float = Field(alias="totalScore")
    pair_scores: PairScores = Field(alias="pairScores")
    evidence: SimilarEvidence
    source_query_article_id: str = Field(alias="sourceQueryArticleId")
    source_candidate_article_id: str = Field(alias="sourceCandidateArticleId")
    materialized_at: str = Field(alias="materializedAt")
    assistant_explanation: dict[str, Any] | None = Field(default=None, alias="assistantExplanation")

    model_config = {"populate_by_name": True}


class ClusterMembership(BaseModel):
    article_id: str = Field(alias="articleId")
    title: str | None = None
    supporting_edge_ids: list[str] = Field(alias="supportingEdgeIds")
    reasons: list[str]
    shared_metadata: dict[str, list[str]] = Field(alias="sharedMetadata")

    model_config = {"populate_by_name": True}


class DuplicateClusterDocument(BaseModel):
    cluster_id: str = Field(alias="clusterId")
    article_ids: list[str] = Field(alias="articleIds")
    edge_ids: list[str] = Field(alias="edgeIds")
    member_count: int = Field(alias="memberCount")
    review_state: ReviewState = Field(alias="reviewState")
    representative_article_id: str = Field(alias="representativeArticleId")
    representative_title: str | None = Field(default=None, alias="representativeTitle")
    memberships: list[ClusterMembership]
    thresholds: ClusterThresholds
    materialized_at: str = Field(alias="materializedAt")
    assistant_explanation: dict[str, Any] | None = Field(default=None, alias="assistantExplanation")

    model_config = {"populate_by_name": True}


class ClusterSummaryItem(BaseModel):
    cluster_id: str = Field(alias="clusterId")
    article_ids: list[str] = Field(alias="articleIds")
    member_count: int = Field(alias="memberCount")
    review_state: ReviewState = Field(alias="reviewState")
    representative_article_id: str = Field(alias="representativeArticleId")
    representative_title: str | None = Field(default=None, alias="representativeTitle")

    model_config = {"populate_by_name": True}


class ClusterListResponse(BaseModel):
    count: int
    items: list[ClusterSummaryItem]


class ClusterDetailResponse(DuplicateClusterDocument):
    edges: list[DuplicateEdgeDocument]


class ClusterMaterializationSummary(BaseModel):
    analysis_mode: str = Field(alias="analysisMode")
    analysis_only: bool = Field(alias="analysisOnly")
    source_article_count: int = Field(alias="sourceArticleCount")
    accepted_edge_count: int = Field(alias="acceptedEdgeCount")
    cluster_count: int = Field(alias="clusterCount")
    review_state_counts: dict[str, int] = Field(alias="reviewStateCounts")

    model_config = {"populate_by_name": True}


EDGE_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "edge_id": {"type": "keyword"},
            "left_article_id": {"type": "keyword"},
            "right_article_id": {"type": "keyword"},
            "label": {"type": "keyword"},
            "accepted": {"type": "boolean"},
            "total_score": {"type": "float"},
            "pair_scores": {
                "properties": {
                    "rrf_score": {"type": "float"},
                    "article_embedding_similarity": {"type": "float"},
                    "best_chunk_similarity": {"type": "float"},
                    "title_similarity": {"type": "float"},
                    "summary_similarity": {"type": "float"},
                    "metadata_agreement": {"type": "float"},
                    "rerank_score": {"type": "float"},
                    "total_score": {"type": "float"},
                }
            },
            "evidence": {
                "properties": {
                    "shared_metadata": {
                        "properties": {
                            "products": {"type": "keyword"},
                            "components": {"type": "keyword"},
                            "product_versions": {"type": "keyword"},
                            "deployments": {"type": "keyword"},
                            "platforms": {"type": "keyword"},
                            "category": {"type": "keyword"},
                        }
                    },
                    "most_similar_chunks": {
                        "type": "nested",
                        "properties": {
                            "query_chunk_id": {"type": "keyword"},
                            "candidate_chunk_id": {"type": "keyword"},
                            "similarity": {"type": "float"},
                            "query_heading": {"type": "keyword"},
                            "candidate_heading": {"type": "keyword"},
                            "query_text": {"type": "text"},
                            "candidate_text": {"type": "text"},
                        },
                    },
                    "reasons": {"type": "keyword"},
                }
            },
            "source_query_article_id": {"type": "keyword"},
            "source_candidate_article_id": {"type": "keyword"},
            "materialized_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "assistant_explanation": {
                "properties": {
                    "summary": {"type": "text"},
                    "why_these_are_similar": {"type": "text"},
                    "what_differs": {"type": "text"},
                    "merge_recommendation_confidence": {"type": "float"},
                    "provider": {"type": "keyword"},
                    "model": {"type": "keyword"},
                    "prompt_version": {"type": "keyword"},
                    "generated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
                    "research_used": {"type": "boolean"},
                }
            },
        }
    },
}


CLUSTER_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "cluster_id": {"type": "keyword"},
            "article_ids": {"type": "keyword"},
            "edge_ids": {"type": "keyword"},
            "member_count": {"type": "integer"},
            "review_state": {"type": "keyword"},
            "representative_article_id": {"type": "keyword"},
            "representative_title": {"type": "text"},
            "memberships": {
                "type": "nested",
                "properties": {
                    "article_id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "supporting_edge_ids": {"type": "keyword"},
                    "reasons": {"type": "keyword"},
                    "shared_metadata": {
                        "properties": {
                            "products": {"type": "keyword"},
                            "components": {"type": "keyword"},
                            "product_versions": {"type": "keyword"},
                            "deployments": {"type": "keyword"},
                            "platforms": {"type": "keyword"},
                            "category": {"type": "keyword"},
                        }
                    },
                },
            },
            "thresholds": {
                "properties": {
                    "top_n": {"type": "integer"},
                    "include_cve": {"type": "boolean"},
                    "include_chunk_seed": {"type": "boolean"},
                    "max_component_size": {"type": "integer"},
                    "weak_edge_threshold": {"type": "float"},
                    "analysis_mode": {"type": "keyword"},
                }
            },
            "materialized_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "assistant_explanation": {
                "properties": {
                    "summary": {"type": "text"},
                    "why_these_are_similar": {"type": "text"},
                    "what_differs": {"type": "text"},
                    "merge_recommendation_confidence": {"type": "float"},
                    "provider": {"type": "keyword"},
                    "model": {"type": "keyword"},
                    "prompt_version": {"type": "keyword"},
                    "generated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
                    "research_used": {"type": "boolean"},
                }
            },
        }
    },
}


@dataclass(frozen=True)
class ResolvedComponent:
    article_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    review_state: ReviewState


@dataclass(frozen=True)
class QueryArticleSummary:
    article_id: str
    remote_document_id: str
    title: str | None
    summary: str | None
    category: str | None
    ai_tags: tuple[str, ...]


CLUSTER_SCAN_SOURCE_INCLUDES = [
    "article_id",
    "remote_document_id",
    "title",
    "summary",
    "category",
    "ai_tags",
]

CLUSTER_REVIEW_STATE_SOURCE_INCLUDES = [
    "cluster_id",
    "review_state",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _contains_cve_marker(text: str | None) -> bool:
    return bool(text and "cve-" in text.casefold())


def _edge_sort_key(edge: DuplicateEdgeDocument) -> tuple[float, str, str]:
    return (edge.total_score, edge.label, edge.edge_id)


def _pair_key(left_article_id: str, right_article_id: str) -> tuple[str, str]:
    return tuple(sorted((left_article_id, right_article_id)))


def _edge_id(left_article_id: str, right_article_id: str) -> str:
    left, right = _pair_key(left_article_id, right_article_id)
    digest = sha1(f"{left}|{right}".encode("utf-8")).hexdigest()[:16]
    return f"edge-{digest}"


def _cluster_id(article_ids: list[str]) -> str:
    digest = sha1(",".join(sorted(article_ids)).encode("utf-8")).hexdigest()[:16]
    return f"family-{digest}"


def _label_priority(label: str) -> int:
    if label == "exact_duplicate":
        return 0
    if label == "near_duplicate":
        return 1
    return 2


def _prefer_edge(existing: DuplicateEdgeDocument | None, candidate: DuplicateEdgeDocument) -> DuplicateEdgeDocument:
    if existing is None:
        return candidate
    if candidate.total_score != existing.total_score:
        return candidate if candidate.total_score > existing.total_score else existing
    if _label_priority(candidate.label) != _label_priority(existing.label):
        return candidate if _label_priority(candidate.label) < _label_priority(existing.label) else existing
    if candidate.source_query_article_id != existing.source_query_article_id:
        return candidate if candidate.source_query_article_id < existing.source_query_article_id else existing
    return candidate if candidate.source_candidate_article_id < existing.source_candidate_article_id else existing


def _edge_connects(edge: DuplicateEdgeDocument, article_id: str) -> bool:
    return article_id in {edge.left_article_id, edge.right_article_id}


def _is_strong_near_duplicate(edge: DuplicateEdgeDocument, *, min_total_score: float) -> bool:
    if edge.label != "near_duplicate":
        return False
    scores = edge.pair_scores
    if edge.total_score < min_total_score:
        return False
    if scores.article_embedding_similarity < max(0.78, min_total_score - 0.08):
        return False
    return (
        scores.best_chunk_similarity >= max(0.55, min_total_score - 0.22)
        or scores.title_similarity >= 0.58
        or scores.metadata_agreement >= 0.6
    )


def _strong_component_edges(
    edges: list[DuplicateEdgeDocument],
    *,
    min_total_score: float,
) -> list[DuplicateEdgeDocument]:
    return [
        edge
        for edge in edges
        if edge.label == "exact_duplicate" or _is_strong_near_duplicate(edge, min_total_score=min_total_score)
    ]


def _component_adjacency(
    article_ids: list[str],
    edges: list[DuplicateEdgeDocument],
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {article_id: set() for article_id in article_ids}
    for edge in edges:
        adjacency.setdefault(edge.left_article_id, set()).add(edge.right_article_id)
        adjacency.setdefault(edge.right_article_id, set()).add(edge.left_article_id)
    return adjacency


def _connected_components(
    article_ids: list[str],
    edges: list[DuplicateEdgeDocument],
) -> list[list[str]]:
    adjacency = _component_adjacency(article_ids, edges)
    seen: set[str] = set()
    components: list[list[str]] = []
    for article_id in sorted(article_ids):
        if article_id in seen:
            continue
        queue = deque([article_id])
        seen.add(article_id)
        component: list[str] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        components.append(sorted(component))
    return components


def _is_bridge(edge: DuplicateEdgeDocument, article_ids: list[str], edges: list[DuplicateEdgeDocument]) -> bool:
    component_count = len(_connected_components(article_ids, edges))
    remaining = [candidate for candidate in edges if candidate.edge_id != edge.edge_id]
    return len(_connected_components(article_ids, remaining)) > component_count


class DuplicateClusterService:
    def __init__(
        self,
        *,
        es_client: ElasticsearchClient,
        similarity_service: SimilarArticleService,
        article_index: str,
        edge_index: str,
        cluster_index: str,
    ) -> None:
        self.es_client = es_client
        self.similarity_service = similarity_service
        self.article_index = article_index
        self.edge_index = edge_index
        self.cluster_index = cluster_index

    def _ensure_index(self, *, index: str, mapping: dict[str, Any]) -> None:
        if not self.es_client.index_exists(index=index):
            self.es_client.create_index(index=index, mapping=mapping)

    def _eligible_articles(self, *, include_cve: bool) -> list[QueryArticleSummary]:
        return [article for article in self._iter_articles() if self._eligible_query_article(article, include_cve=include_cve)]

    def _iter_articles(self) -> list[QueryArticleSummary]:
        articles: list[QueryArticleSummary] = []
        pit_id = self.es_client.open_point_in_time(index=self.article_index, keep_alive="1m")
        search_after: list[Any] | None = None
        try:
            while True:
                page = self.es_client.search_with_pit(
                    pit_id=pit_id,
                    keep_alive="1m",
                    size=200,
                    source_includes=CLUSTER_SCAN_SOURCE_INCLUDES,
                    search_after=search_after,
                )
                pit_id = page.pit_id
                if not page.hits:
                    break
                for hit in page.hits:
                    source = hit.get("_source")
                    if not isinstance(source, dict):
                        continue
                    article_id = source.get("article_id")
                    remote_document_id = source.get("remote_document_id")
                    if not isinstance(article_id, str) or not isinstance(remote_document_id, str):
                        continue
                    raw_ai_tags = source.get("ai_tags")
                    ai_tags = tuple(tag for tag in raw_ai_tags if isinstance(tag, str)) if isinstance(raw_ai_tags, list) else ()
                    articles.append(
                        QueryArticleSummary(
                            article_id=article_id,
                            remote_document_id=remote_document_id,
                            title=source.get("title") if isinstance(source.get("title"), str) else None,
                            summary=source.get("summary") if isinstance(source.get("summary"), str) else None,
                            category=source.get("category") if isinstance(source.get("category"), str) else None,
                            ai_tags=ai_tags,
                        )
                    )
                search_sort = page.hits[-1].get("sort")
                search_after = search_sort if isinstance(search_sort, list) else None
                if search_after is None:
                    break
        finally:
            self.es_client.close_point_in_time(pit_id=pit_id)
        articles.sort(key=lambda article: article.article_id)
        return articles

    def _eligible_query_article(self, article: QueryArticleSummary, *, include_cve: bool) -> bool:
        if article.remote_document_id.casefold().endswith("-draft"):
            return False
        if not include_cve and (
            _contains_cve_marker(article.title)
            or _contains_cve_marker(article.summary)
            or _contains_cve_marker(article.category)
            or any(_contains_cve_marker(tag) for tag in article.ai_tags)
        ):
            return False
        return True

    def _accepted_edge_candidate(
        self,
        *,
        query_article_id: str,
        candidate: SimilarArticleCandidate,
        materialized_at: str,
    ) -> DuplicateEdgeDocument | None:
        if candidate.label not in ACCEPTED_LABELS:
            return None
        left_article_id, right_article_id = _pair_key(query_article_id, candidate.article_id)
        return DuplicateEdgeDocument(
            edgeId=_edge_id(left_article_id, right_article_id),
            leftArticleId=left_article_id,
            rightArticleId=right_article_id,
            label=candidate.label,
            accepted=True,
            totalScore=candidate.pair_scores.total_score,
            pairScores=candidate.pair_scores,
            evidence=candidate.evidence,
            sourceQueryArticleId=query_article_id,
            sourceCandidateArticleId=candidate.article_id,
            materializedAt=materialized_at,
        )

    def materialize_edges(
        self,
        request: ClusterMaterializationRequest,
        *,
        progress_callback: Callable[[str], None] | None = None,
        checkpoint_edges: bool = False,
        articles: list[QueryArticleSummary] | None = None,
    ) -> tuple[list[QueryArticleSummary], list[DuplicateEdgeDocument]]:
        articles = articles or self._eligible_articles(include_cve=request.include_cve)
        if progress_callback is not None:
            progress_callback(
                "Cluster materialization candidate scan started: "
                f"eligible_articles={len(articles)}."
            )
        materialized_at = _now_iso()
        edges_by_id: dict[str, DuplicateEdgeDocument] = {}
        dirty_edges: dict[str, DuplicateEdgeDocument] = {}

        if checkpoint_edges:
            self._prepare_edge_index()

        def flush_dirty_edges() -> None:
            if not checkpoint_edges or not dirty_edges:
                return
            self._upsert_edges(list(dirty_edges.values()))
            dirty_edges.clear()

        for index, article in enumerate(articles, start=1):
            response = self.similarity_service.search(
                SimilarSearchRequest(
                    articleId=article.article_id,
                    includeCve=request.include_cve,
                    includeChunkSeed=request.include_chunk_seed,
                    limit=request.top_n,
                )
            )
            for candidate in response.candidates:
                edge = self._accepted_edge_candidate(
                    query_article_id=article.article_id,
                    candidate=candidate,
                    materialized_at=materialized_at,
                )
                if edge is None:
                    continue
                existing = edges_by_id.get(edge.edge_id)
                preferred = _prefer_edge(existing, edge)
                if existing is preferred:
                    continue
                edges_by_id[edge.edge_id] = preferred
                dirty_edges[preferred.edge_id] = preferred
            if progress_callback is not None and (index == len(articles) or index % 250 == 0):
                flush_dirty_edges()
                progress_callback(
                    "Cluster materialization progress: "
                    f"scanned_articles={index}/{len(articles)}, "
                    f"accepted_edges={len(edges_by_id)}."
                )
        flush_dirty_edges()
        edges = sorted(edges_by_id.values(), key=lambda edge: (edge.left_article_id, edge.right_article_id))
        return articles, edges

    def _load_persisted_edges(self) -> list[DuplicateEdgeDocument]:
        if not self.es_client.index_exists(index=self.edge_index):
            return []
        pit_id = self.es_client.open_point_in_time(index=self.edge_index, keep_alive="1m")
        search_after: list[Any] | None = None
        edges: list[DuplicateEdgeDocument] = []
        try:
            while True:
                page = self.es_client.search_with_pit(
                    pit_id=pit_id,
                    keep_alive="1m",
                    size=500,
                    search_after=search_after,
                )
                pit_id = page.pit_id
                if not page.hits:
                    break
                for hit in page.hits:
                    source = hit.get("_source")
                    if isinstance(source, dict):
                        edges.append(DuplicateEdgeDocument.model_validate(source))
                last_sort = page.hits[-1].get("sort")
                search_after = last_sort if isinstance(last_sort, list) else None
                if search_after is None:
                    break
        finally:
            self.es_client.close_point_in_time(pit_id=pit_id)
        edges.sort(key=lambda edge: (edge.left_article_id, edge.right_article_id))
        return edges

    def _removable_bridge(
        self,
        article_ids: list[str],
        edges: list[DuplicateEdgeDocument],
        *,
        allow_strong_split: bool,
        weak_edge_threshold: float,
    ) -> DuplicateEdgeDocument | None:
        bridge_candidates: list[DuplicateEdgeDocument] = []
        for edge in sorted(edges, key=_edge_sort_key):
            if not _is_bridge(edge, article_ids, edges):
                continue
            if allow_strong_split or edge.total_score < weak_edge_threshold:
                bridge_candidates.append(edge)
        return bridge_candidates[0] if bridge_candidates else None

    def _resolve_component(
        self,
        article_ids: list[str],
        edges: list[DuplicateEdgeDocument],
        *,
        max_component_size: int,
        weak_edge_threshold: float,
    ) -> list[ResolvedComponent]:
        if len(article_ids) < 2:
            return []

        working_article_ids = sorted(article_ids)
        working_edges = sorted(edges, key=lambda edge: (edge.left_article_id, edge.right_article_id))

        while True:
            split_components = _connected_components(working_article_ids, working_edges)
            if len(split_components) > 1:
                resolved: list[ResolvedComponent] = []
                for component_ids in split_components:
                    component_edges = [
                        edge
                        for edge in working_edges
                        if edge.left_article_id in component_ids and edge.right_article_id in component_ids
                    ]
                    resolved.extend(
                        self._resolve_component(
                            component_ids,
                            component_edges,
                            max_component_size=max_component_size,
                            weak_edge_threshold=weak_edge_threshold,
                        )
                    )
                return resolved

            if len(working_article_ids) <= max_component_size:
                weak_bridge = self._removable_bridge(
                    working_article_ids,
                    working_edges,
                    allow_strong_split=False,
                    weak_edge_threshold=weak_edge_threshold,
                )
                if weak_bridge is None:
                    return [
                        ResolvedComponent(
                            article_ids=tuple(working_article_ids),
                            edge_ids=tuple(sorted(edge.edge_id for edge in working_edges)),
                            review_state="pending_review",
                        )
                    ]
                working_edges = [edge for edge in working_edges if edge.edge_id != weak_bridge.edge_id]
                continue

            for threshold in (
                max(weak_edge_threshold, 0.8),
                max(weak_edge_threshold, 0.84),
                max(weak_edge_threshold, 0.9),
            ):
                strengthened_edges = _strong_component_edges(
                    working_edges,
                    min_total_score=threshold,
                )
                if not strengthened_edges or len(strengthened_edges) == len(working_edges):
                    continue
                strengthened_components = _connected_components(working_article_ids, strengthened_edges)
                if len(strengthened_components) <= 1:
                    continue
                resolved: list[ResolvedComponent] = []
                for component_ids in strengthened_components:
                    component_edges = [
                        edge
                        for edge in strengthened_edges
                        if edge.left_article_id in component_ids and edge.right_article_id in component_ids
                    ]
                    resolved.extend(
                        self._resolve_component(
                            component_ids,
                            component_edges,
                            max_component_size=max_component_size,
                            weak_edge_threshold=max(weak_edge_threshold, threshold),
                        )
                    )
                return resolved

            size_bridge = self._removable_bridge(
                working_article_ids,
                working_edges,
                allow_strong_split=True,
                weak_edge_threshold=weak_edge_threshold,
            )
            if size_bridge is None:
                return [
                    ResolvedComponent(
                        article_ids=tuple(working_article_ids),
                        edge_ids=tuple(sorted(edge.edge_id for edge in working_edges)),
                        review_state="split_required",
                    )
                ]
            working_edges = [edge for edge in working_edges if edge.edge_id != size_bridge.edge_id]

    def _representative_article_id(
        self,
        article_ids: list[str],
        edges_by_id: dict[str, DuplicateEdgeDocument],
    ) -> str:
        weighted_degree: dict[str, float] = {article_id: 0.0 for article_id in article_ids}
        for edge_id in (edge_id for edge_id in edges_by_id if edges_by_id[edge_id].left_article_id in article_ids):
            edge = edges_by_id[edge_id]
            if edge.left_article_id in weighted_degree:
                weighted_degree[edge.left_article_id] += edge.total_score
            if edge.right_article_id in weighted_degree:
                weighted_degree[edge.right_article_id] += edge.total_score
        return sorted(article_ids, key=lambda article_id: (-weighted_degree[article_id], article_id))[0]

    def _membership(
        self,
        *,
        article_id: str,
        title: str | None,
        supporting_edges: list[DuplicateEdgeDocument],
    ) -> ClusterMembership:
        reasons = sorted({reason for edge in supporting_edges for reason in edge.evidence.reasons})
        shared_metadata: dict[str, list[str]] = defaultdict(list)
        for edge in supporting_edges:
            for field_name, values in edge.evidence.shared_metadata.items():
                for value in values:
                    if value not in shared_metadata[field_name]:
                        shared_metadata[field_name].append(value)
        return ClusterMembership(
            articleId=article_id,
            title=title,
            supportingEdgeIds=sorted(edge.edge_id for edge in supporting_edges),
            reasons=reasons,
            sharedMetadata={key: values for key, values in sorted(shared_metadata.items())},
        )

    def _existing_review_states(self, cluster_ids: list[str]) -> dict[str, ReviewState]:
        if not cluster_ids or not self.es_client.index_exists(index=self.cluster_index):
            return {}
        hits = self.es_client.search(
            index=self.cluster_index,
            body={
                "size": len(cluster_ids),
                "query": {"terms": {"cluster_id": cluster_ids}},
            },
        )
        review_states: dict[str, ReviewState] = {}
        for hit in hits:
            source = hit.get("_source")
            if not isinstance(source, dict):
                continue
            cluster_id = source.get("cluster_id")
            review_state = source.get("review_state")
            if isinstance(cluster_id, str) and isinstance(review_state, str):
                review_states[cluster_id] = review_state  # type: ignore[assignment]
        return review_states

    def build_clusters(
        self,
        *,
        article_titles: dict[str, str | None],
        edges: list[DuplicateEdgeDocument],
        request: ClusterMaterializationRequest,
        preserved_review_states: dict[str, ReviewState] | None = None,
    ) -> list[DuplicateClusterDocument]:
        article_ids = sorted({edge.left_article_id for edge in edges} | {edge.right_article_id for edge in edges})
        connected = _connected_components(article_ids, edges)
        edge_lookup = {edge.edge_id: edge for edge in edges}
        thresholds = ClusterThresholds(
            topN=request.top_n,
            includeCve=request.include_cve,
            includeChunkSeed=request.include_chunk_seed,
            maxComponentSize=request.max_component_size,
            weakEdgeThreshold=request.weak_edge_threshold,
            analysisMode=request.analysis_mode,
        )

        resolved_components: list[ResolvedComponent] = []
        for component_ids in connected:
            component_edges = [
                edge for edge in edges if edge.left_article_id in component_ids and edge.right_article_id in component_ids
            ]
            resolved_components.extend(
                self._resolve_component(
                    component_ids,
                    component_edges,
                    max_component_size=request.max_component_size,
                    weak_edge_threshold=request.weak_edge_threshold,
                )
            )

        cluster_ids = [_cluster_id(list(component.article_ids)) for component in resolved_components]
        if preserved_review_states is None:
            active_review_states = self._existing_review_states(cluster_ids)
        else:
            active_review_states = {
                cluster_id: review_state
                for cluster_id, review_state in preserved_review_states.items()
                if cluster_id in cluster_ids
            }
        materialized_at = _now_iso()
        clusters: list[DuplicateClusterDocument] = []
        for component in sorted(resolved_components, key=lambda item: item.article_ids):
            member_ids = list(component.article_ids)
            representative_article_id = self._representative_article_id(member_ids, edge_lookup)
            supporting_edges = [edge_lookup[edge_id] for edge_id in component.edge_ids]
            memberships: list[ClusterMembership] = []
            for article_id in member_ids:
                title = article_titles.get(article_id)
                article_edges = [edge for edge in supporting_edges if _edge_connects(edge, article_id)]
                memberships.append(
                    self._membership(
                        article_id=article_id,
                        title=title,
                        supporting_edges=article_edges,
                    )
                )
            cluster_id = _cluster_id(member_ids)
            review_state = active_review_states.get(cluster_id, component.review_state)
            representative_title = article_titles.get(representative_article_id)
            clusters.append(
                DuplicateClusterDocument(
                    clusterId=cluster_id,
                    articleIds=member_ids,
                    edgeIds=list(component.edge_ids),
                    memberCount=len(member_ids),
                    reviewState=review_state,
                    representativeArticleId=representative_article_id,
                    representativeTitle=representative_title,
                    memberships=memberships,
                    thresholds=thresholds,
                    materializedAt=materialized_at,
                )
            )
        clusters.sort(key=lambda cluster: (-cluster.member_count, cluster.cluster_id))
        return clusters

    def _prepare_edge_index(self) -> None:
        self._ensure_index(index=self.edge_index, mapping=EDGE_INDEX_MAPPING)
        self.es_client.delete_by_query(index=self.edge_index, query={"match_all": {}})

    def _upsert_edges(self, edges: list[DuplicateEdgeDocument]) -> None:
        if not edges:
            return
        self.es_client.bulk_index(
            index=self.edge_index,
            documents=[(edge.edge_id, edge.model_dump(by_alias=False)) for edge in edges],
        )

    def _persist_edges(self, edges: list[DuplicateEdgeDocument]) -> None:
        self._prepare_edge_index()
        self._upsert_edges(edges)

    def _prepare_cluster_index(self) -> None:
        self._ensure_index(index=self.cluster_index, mapping=CLUSTER_INDEX_MAPPING)
        self.es_client.delete_by_query(index=self.cluster_index, query={"match_all": {}})

    def _upsert_clusters(self, clusters: list[DuplicateClusterDocument]) -> None:
        if not clusters:
            return
        self.es_client.bulk_index(
            index=self.cluster_index,
            documents=[(cluster.cluster_id, cluster.model_dump(by_alias=False)) for cluster in clusters],
        )

    def _persist_clusters(self, clusters: list[DuplicateClusterDocument]) -> None:
        self._prepare_cluster_index()
        self._upsert_clusters(clusters)

    def _all_existing_review_states(self) -> dict[str, ReviewState]:
        if not self.es_client.index_exists(index=self.cluster_index):
            return {}
        pit_id = self.es_client.open_point_in_time(index=self.cluster_index, keep_alive="1m")
        search_after: list[Any] | None = None
        review_states: dict[str, ReviewState] = {}
        try:
            while True:
                page = self.es_client.search_with_pit(
                    pit_id=pit_id,
                    keep_alive="1m",
                    size=500,
                    source_includes=CLUSTER_REVIEW_STATE_SOURCE_INCLUDES,
                    search_after=search_after,
                )
                pit_id = page.pit_id
                if not page.hits:
                    break
                for hit in page.hits:
                    source = hit.get("_source")
                    if not isinstance(source, dict):
                        continue
                    cluster_id = source.get("cluster_id")
                    review_state = source.get("review_state")
                    if isinstance(cluster_id, str) and isinstance(review_state, str):
                        review_states[cluster_id] = review_state  # type: ignore[assignment]
                last_sort = page.hits[-1].get("sort")
                search_after = last_sort if isinstance(last_sort, list) else None
                if search_after is None:
                    break
        finally:
            self.es_client.close_point_in_time(pit_id=pit_id)
        return review_states

    def _build_and_persist_clusters_incrementally(
        self,
        *,
        article_titles: dict[str, str | None],
        edges: list[DuplicateEdgeDocument],
        request: ClusterMaterializationRequest,
        progress_callback: Callable[[str], None] | None = None,
        persist_clusters: bool,
    ) -> tuple[int, dict[str, int]]:
        article_ids = sorted({edge.left_article_id for edge in edges} | {edge.right_article_id for edge in edges})
        connected = sorted(
            _connected_components(article_ids, edges),
            key=lambda component_ids: (len(component_ids), component_ids),
        )
        article_to_component: dict[str, int] = {}
        for component_index, component_ids in enumerate(connected):
            for article_id in component_ids:
                article_to_component[article_id] = component_index

        component_edges: dict[int, list[DuplicateEdgeDocument]] = defaultdict(list)
        for edge in edges:
            component_index = article_to_component.get(edge.left_article_id)
            if component_index is None:
                continue
            component_edges[component_index].append(edge)

        preserved_review_states = self._all_existing_review_states() if persist_clusters else {}
        if persist_clusters:
            self._prepare_cluster_index()

        component_total = len(connected)
        if progress_callback is not None:
            largest_component_size = max((len(component_ids) for component_ids in connected), default=0)
            progress_callback(
                "Cluster materialization graph partitioned: "
                f"connected_components={component_total}, "
                f"largest_component_size={largest_component_size}."
            )

        review_state_counts: Counter[str] = Counter()
        persisted_cluster_count = 0
        buffered_clusters: list[DuplicateClusterDocument] = []
        for component_number, component_ids in enumerate(connected, start=1):
            component_edge_documents = component_edges.get(component_number - 1, [])
            if progress_callback is not None and (
                component_number == 1
                or component_number == component_total
                or component_number % 10 == 0
            ):
                progress_callback(
                    "Cluster materialization component started: "
                    f"component={component_number}/{component_total}, "
                    f"articles={len(component_ids)}, "
                    f"edges={len(component_edge_documents)}."
                )
            built_clusters = self.build_clusters(
                article_titles=article_titles,
                edges=component_edge_documents,
                request=request,
                preserved_review_states=preserved_review_states,
            )
            buffered_clusters.extend(built_clusters)
            review_state_counts.update(cluster.review_state for cluster in built_clusters)

            should_flush = (
                component_number == component_total
                or len(buffered_clusters) >= 200
                or component_number % 10 == 0
            )
            if not should_flush:
                continue

            if persist_clusters:
                self._upsert_clusters(buffered_clusters)
            persisted_cluster_count += len(buffered_clusters)
            if progress_callback is not None:
                progress_callback(
                    "Cluster materialization graph build progress: "
                    f"resolved_components={component_number}/{component_total}, "
                    f"clusters={persisted_cluster_count}."
                )
            buffered_clusters = []

        return persisted_cluster_count, dict(sorted(review_state_counts.items()))

    def materialize(
        self,
        request: ClusterMaterializationRequest,
        *,
        progress_callback: Callable[[str], None] | None = None,
        resume_from_persisted_edges: bool = False,
    ) -> ClusterMaterializationSummary:
        analysis_only = request.analysis_mode.casefold() == "hdbscan"
        articles = self._eligible_articles(include_cve=request.include_cve)
        edges: list[DuplicateEdgeDocument]
        reused_persisted_edges = False
        if resume_from_persisted_edges and not analysis_only and self.es_client.index_exists(index=self.edge_index):
            persisted_edge_count = self.es_client.count_documents(index=self.edge_index, query={"match_all": {}})
            if persisted_edge_count > 0:
                edges = self._load_persisted_edges()
                reused_persisted_edges = bool(edges)
                if reused_persisted_edges and progress_callback is not None:
                    progress_callback(
                        "Resuming cluster materialization from persisted edge checkpoint: "
                        f"edge_documents={len(edges)}, eligible_articles={len(articles)}."
                    )
            else:
                reused_persisted_edges = False
        if not reused_persisted_edges:
            articles, edges = self.materialize_edges(
                request,
                progress_callback=progress_callback,
                checkpoint_edges=not analysis_only,
                articles=articles,
            )
        article_titles = {article.article_id: article.title for article in articles}
        if progress_callback is not None:
            progress_callback(
                "Cluster materialization graph build started: "
                f"accepted_edges={len(edges)}."
            )
        cluster_count, review_state_counts = self._build_and_persist_clusters_incrementally(
            article_titles=article_titles,
            edges=edges,
            request=request,
            progress_callback=progress_callback,
            persist_clusters=not analysis_only,
        )
        if progress_callback is not None:
            progress_callback(
                "Cluster materialization graph build complete: "
                f"clusters={cluster_count}."
            )
        if not analysis_only:
            if progress_callback is not None:
                progress_callback(
                    "Cluster materialization persistence started: "
                    f"edge_documents={len(edges)}, cluster_documents={cluster_count}."
                )
            if progress_callback is not None:
                progress_callback("Cluster materialization persistence complete.")
        return ClusterMaterializationSummary(
            analysisMode=request.analysis_mode,
            analysisOnly=analysis_only,
            sourceArticleCount=len(articles),
            acceptedEdgeCount=len(edges),
            clusterCount=cluster_count,
            reviewStateCounts=review_state_counts,
        )

    def list_clusters(self, *, size: int = 20) -> ClusterListResponse:
        hits = self.es_client.search(
            index=self.cluster_index,
            body={
                "size": size,
                "sort": [{"member_count": "desc"}, {"cluster_id": "asc"}],
                "query": {"match_all": {}},
            },
        )
        items = [
            ClusterSummaryItem.model_validate(hit.get("_source"))
            for hit in hits
            if isinstance(hit.get("_source"), dict)
        ]
        return ClusterListResponse(
            count=self.es_client.count_documents(
                index=self.cluster_index,
                query={"match_all": {}},
            ),
            items=items,
        )

    def get_cluster(self, cluster_id: str) -> ClusterDetailResponse | None:
        hits = self.es_client.search(
            index=self.cluster_index,
            body={
                "size": 1,
                "query": {"term": {"cluster_id": cluster_id}},
            },
        )
        if not hits:
            return None
        source = hits[0].get("_source")
        if not isinstance(source, dict):
            return None
        cluster = DuplicateClusterDocument.model_validate(source)
        edge_hits = self.es_client.search(
            index=self.edge_index,
            body={
                "size": max(len(cluster.edge_ids), 1),
                "query": {"terms": {"edge_id": cluster.edge_ids}},
                "sort": [{"total_score": "desc"}, {"edge_id": "asc"}],
            },
        )
        edges = [
            DuplicateEdgeDocument.model_validate(hit.get("_source"))
            for hit in edge_hits
            if isinstance(hit.get("_source"), dict)
        ]
        return ClusterDetailResponse(
            **cluster.model_dump(by_alias=False),
            edges=edges,
        )

    def get_cluster_for_article(self, article_id: str) -> ClusterSummaryItem | None:
        hits = self.es_client.search(
            index=self.cluster_index,
            body={
                "size": 1,
                "query": {"term": {"article_ids": article_id}},
                "sort": [{"member_count": "desc"}, {"cluster_id": "asc"}],
            },
        )
        if not hits:
            return None
        source = hits[0].get("_source")
        if not isinstance(source, dict):
            return None
        return ClusterSummaryItem.model_validate(source)

    def update_cluster_review_state(
        self,
        *,
        cluster_id: str,
        request: ClusterReviewUpdateRequest,
    ) -> ClusterDetailResponse | None:
        if request.review_state not in {"pending_review", "approved_family", "rejected_family", "split_required"}:
            raise ValueError(f"Unsupported review state: {request.review_state}")

        hits = self.es_client.search(
            index=self.cluster_index,
            body={
                "size": 1,
                "query": {"term": {"cluster_id": cluster_id}},
            },
        )
        if not hits:
            return None
        source = hits[0].get("_source")
        if not isinstance(source, dict):
            return None

        updated_source = dict(source)
        updated_source["review_state"] = request.review_state
        self.es_client.bulk_index(
            index=self.cluster_index,
            documents=[(cluster_id, updated_source)],
        )
        cluster = DuplicateClusterDocument.model_validate(updated_source)
        edge_hits = self.es_client.search(
            index=self.edge_index,
            body={
                "size": max(len(cluster.edge_ids), 1),
                "query": {"terms": {"edge_id": cluster.edge_ids}},
                "sort": [{"total_score": "desc"}, {"edge_id": "asc"}],
            },
        )
        edges = [
            DuplicateEdgeDocument.model_validate(hit.get("_source"))
            for hit in edge_hits
            if isinstance(hit.get("_source"), dict)
        ]
        return ClusterDetailResponse(
            **cluster.model_dump(by_alias=False),
            edges=edges,
        )


def build_duplicate_cluster_service() -> DuplicateClusterService:
    es_client = ElasticsearchClient(base_url=get_target_es_url())
    return DuplicateClusterService(
        es_client=es_client,
        similarity_service=SimilarArticleService(
            es_client=es_client,
            # Cluster materialization should remain local and deterministic. Reusing the
            # persisted duplicate embeddings is enough here, and avoiding network reranking
            # keeps step 4 resumable even when external providers are slow or unavailable.
            reranker=StubRerankerProvider(),
            article_index=get_target_es_index(),
            enable_lexical_search=False,
        ),
        article_index=get_target_es_index(),
        edge_index=get_target_duplicate_edge_index(),
        cluster_index=get_target_duplicate_cluster_index(),
    )
