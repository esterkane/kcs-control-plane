from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.clustering.service import DuplicateClusterDocument, DuplicateEdgeDocument
from app.config import (
    ExplanationRequest,
    get_target_duplicate_cluster_index,
    get_target_duplicate_edge_index,
    get_target_es_index,
    get_target_es_url,
)
from app.elasticsearch.client import ElasticsearchClient
from app.explanations.providers import (
    ExplanationOutput,
    ExplanationPromptContext,
    PROMPT_VERSION,
    create_explanation_provider,
)
from app.explanations.research import create_research_helper
from app.ingestion.kb import NormalizedKbDocument


class PersistedExplanation(BaseModel):
    summary: str
    why_these_are_similar: list[str] = Field(alias="whyTheseAreSimilar")
    what_differs: list[str] = Field(alias="whatDiffers")
    merge_recommendation_confidence: float = Field(alias="mergeRecommendationConfidence")
    provider: str
    model: str
    prompt_version: str = Field(alias="promptVersion")
    generated_at: str = Field(alias="generatedAt")
    research_used: bool = Field(default=False, alias="researchUsed")

    model_config = {"populate_by_name": True}


class PairExplanationResponse(PersistedExplanation):
    pair_id: str = Field(alias="pairId")


class ClusterSummaryResponse(PersistedExplanation):
    cluster_id: str = Field(alias="clusterId")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ExplanationService:
    def __init__(
        self,
        *,
        es_client: ElasticsearchClient,
        explanation_provider: Any,
        research_helper: Any,
        article_index: str,
        edge_index: str,
        cluster_index: str,
    ) -> None:
        self.es_client = es_client
        self.explanation_provider = explanation_provider
        self.research_helper = research_helper
        self.article_index = article_index
        self.edge_index = edge_index
        self.cluster_index = cluster_index

    def _article_by_id(self, article_id: str) -> NormalizedKbDocument:
        hits = self.es_client.search(
            index=self.article_index,
            body={"size": 1, "query": {"term": {"article_id": article_id}}},
        )
        if not hits:
            raise ValueError(f"Article not found: {article_id}")
        source = hits[0].get("_source")
        if not isinstance(source, dict):
            raise ValueError(f"Article source missing for {article_id}")
        return NormalizedKbDocument.model_validate(source)

    def _edge_hit_by_id(self, pair_id: str) -> dict[str, Any]:
        hits = self.es_client.search(
            index=self.edge_index,
            body={"size": 1, "query": {"term": {"edge_id": pair_id}}},
        )
        if not hits:
            raise ValueError(f"Pair not found: {pair_id}")
        return hits[0]

    def _cluster_hit_by_id(self, cluster_id: str) -> dict[str, Any]:
        hits = self.es_client.search(
            index=self.cluster_index,
            body={"size": 1, "query": {"term": {"cluster_id": cluster_id}}},
        )
        if not hits:
            raise ValueError(f"Cluster not found: {cluster_id}")
        return hits[0]

    def _persist_document(
        self,
        *,
        index: str,
        hit: dict[str, Any],
        explanation_field: str,
        explanation: PersistedExplanation,
    ) -> None:
        source = hit.get("_source")
        document_id = hit.get("_id")
        if not isinstance(source, dict) or not isinstance(document_id, str):
            raise ValueError("Cannot persist explanation without source and document id")
        updated_source = dict(source)
        updated_source[explanation_field] = explanation.model_dump(by_alias=False)
        self.es_client.bulk_index(index=index, documents=[(document_id, updated_source)])

    def _research_context(self, *, include_research: bool, query: str) -> tuple[str | None, bool]:
        if not include_research:
            return None, False
        research_text = self.research_helper.research(query)
        return research_text, research_text is not None

    def _pair_prompt(
        self,
        *,
        pair_id: str,
        edge: DuplicateEdgeDocument,
        left_article: NormalizedKbDocument,
        right_article: NormalizedKbDocument,
        research_text: str | None,
    ) -> str:
        research_section = f"\nResearch context:\n{research_text}\n" if research_text else ""
        return (
            "You are a secondary explainer for deterministic KB duplicate review.\n"
            "Return JSON only with keys: summary, whyTheseAreSimilar, whatDiffers, mergeRecommendationConfidence, generatedAt, researchUsed.\n"
            "Never change deterministic scoring and do not claim certainty beyond the evidence.\n"
            f"Prompt version: {PROMPT_VERSION}\n"
            f"Pair id: {pair_id}\n"
            f"Left article: {left_article.article_id} | {left_article.title}\n"
            f"Left summary: {left_article.summary}\n"
            f"Right article: {right_article.article_id} | {right_article.title}\n"
            f"Right summary: {right_article.summary}\n"
            f"Deterministic label: {edge.label}\n"
            f"Deterministic total score: {edge.total_score}\n"
            f"Shared metadata: {edge.evidence.shared_metadata}\n"
            f"Why similar evidence: {edge.evidence.reasons}\n"
            f"Chunk evidence: {[chunk.model_dump(by_alias=False) for chunk in edge.evidence.most_similar_chunks]}\n"
            f"{research_section}"
            f"Set generatedAt to {_now_iso()} and researchUsed to {str(bool(research_text)).lower()}."
        )

    def _cluster_prompt(
        self,
        *,
        cluster_id: str,
        cluster: DuplicateClusterDocument,
        member_articles: list[NormalizedKbDocument],
        edge_documents: list[DuplicateEdgeDocument],
        research_text: str | None,
    ) -> str:
        research_section = f"\nResearch context:\n{research_text}\n" if research_text else ""
        return (
            "You are a secondary explainer for deterministic KB family review.\n"
            "Return JSON only with keys: summary, whyTheseAreSimilar, whatDiffers, mergeRecommendationConfidence, generatedAt, researchUsed.\n"
            "Explain the cluster as assistive text only and never replace deterministic cluster membership.\n"
            f"Prompt version: {PROMPT_VERSION}\n"
            f"Cluster id: {cluster_id}\n"
            f"Review state: {cluster.review_state}\n"
            f"Member article ids: {cluster.article_ids}\n"
            f"Representative article: {cluster.representative_article_id}\n"
            f"Member titles: {[article.title for article in member_articles]}\n"
            f"Cluster memberships: {[membership.model_dump(by_alias=False) for membership in cluster.memberships]}\n"
            f"Supporting edges: {[edge.model_dump(by_alias=False) for edge in edge_documents]}\n"
            f"{research_section}"
            f"Set generatedAt to {_now_iso()} and researchUsed to {str(bool(research_text)).lower()}."
        )

    def explain_pair(self, pair_id: str, request: ExplanationRequest) -> PairExplanationResponse:
        edge_hit = self._edge_hit_by_id(pair_id)
        source = edge_hit.get("_source")
        if not isinstance(source, dict):
            raise ValueError(f"Pair source missing: {pair_id}")
        edge = DuplicateEdgeDocument.model_validate(source)
        left_article = self._article_by_id(edge.left_article_id)
        right_article = self._article_by_id(edge.right_article_id)
        research_text, research_used = self._research_context(
            include_research=request.include_research,
            query=f"{left_article.title} {right_article.title}",
        )
        explanation = self.explanation_provider.explain(
            ExplanationPromptContext(
                subjectId=pair_id,
                subjectType="pair",
                prompt=self._pair_prompt(
                    pair_id=pair_id,
                    edge=edge,
                    left_article=left_article,
                    right_article=right_article,
                    research_text=research_text,
                ),
            )
        )
        persisted = PersistedExplanation.model_validate(
            {
                **explanation.model_dump(by_alias=True),
                "researchUsed": research_used,
                "generatedAt": explanation.generated_at or _now_iso(),
            }
        )
        self._persist_document(
            index=self.edge_index,
            hit=edge_hit,
            explanation_field="assistant_explanation",
            explanation=persisted,
        )
        return PairExplanationResponse(pairId=pair_id, **persisted.model_dump(by_alias=True))

    def summarize_cluster(self, cluster_id: str, request: ExplanationRequest) -> ClusterSummaryResponse:
        cluster_hit = self._cluster_hit_by_id(cluster_id)
        source = cluster_hit.get("_source")
        if not isinstance(source, dict):
            raise ValueError(f"Cluster source missing: {cluster_id}")
        cluster = DuplicateClusterDocument.model_validate(source)
        member_articles = [self._article_by_id(article_id) for article_id in cluster.article_ids]
        edge_hits = self.es_client.search(
            index=self.edge_index,
            body={
                "size": max(len(cluster.edge_ids), 1),
                "query": {"terms": {"edge_id": cluster.edge_ids}},
                "sort": [{"total_score": "desc"}, {"edge_id": "asc"}],
            },
        )
        edge_documents = [
            DuplicateEdgeDocument.model_validate(hit.get("_source"))
            for hit in edge_hits
            if isinstance(hit.get("_source"), dict)
        ]
        research_text, research_used = self._research_context(
            include_research=request.include_research,
            query=f"Cluster {cluster_id} {' '.join(article.title or article.article_id for article in member_articles)}",
        )
        explanation = self.explanation_provider.explain(
            ExplanationPromptContext(
                subjectId=cluster_id,
                subjectType="cluster",
                prompt=self._cluster_prompt(
                    cluster_id=cluster_id,
                    cluster=cluster,
                    member_articles=member_articles,
                    edge_documents=edge_documents,
                    research_text=research_text,
                ),
            )
        )
        persisted = PersistedExplanation.model_validate(
            {
                **explanation.model_dump(by_alias=True),
                "researchUsed": research_used,
                "generatedAt": explanation.generated_at or _now_iso(),
            }
        )
        self._persist_document(
            index=self.cluster_index,
            hit=cluster_hit,
            explanation_field="assistant_explanation",
            explanation=persisted,
        )
        return ClusterSummaryResponse(clusterId=cluster_id, **persisted.model_dump(by_alias=True))


def build_explanation_service() -> ExplanationService:
    es_client = ElasticsearchClient(base_url=get_target_es_url())
    return ExplanationService(
        es_client=es_client,
        explanation_provider=create_explanation_provider(),
        research_helper=create_research_helper(),
        article_index=get_target_es_index(),
        edge_index=get_target_duplicate_edge_index(),
        cluster_index=get_target_duplicate_cluster_index(),
    )
