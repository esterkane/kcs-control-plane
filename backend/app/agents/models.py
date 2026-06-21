"""Pydantic models for the editorial supervisor: proposals, drafts, routing, episodes.

These mirror the conventions used elsewhere in the backend (camelCase aliases with
``populate_by_name``). ``ReviewState`` is reused verbatim from the clustering service so
the agents' decision space is EXACTLY the deterministic pipeline's review states.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.clustering.service import ReviewState

# The four routing actions the SupervisorAgent can take. ``auto_approve`` and ``split``
# persist review state; ``send_to_human`` and ``reject`` keep humans in the loop /
# do not author a draft.
RoutingAction = Literal["auto_approve", "send_to_human", "split", "reject"]

PROMPT_VERSION = "editorial-supervisor-v1"


class EdgeRef(BaseModel):
    """A compact reference to a supporting edge the agent cited."""

    edge_id: str = Field(alias="edgeId")
    left_article_id: str = Field(alias="leftArticleId")
    right_article_id: str = Field(alias="rightArticleId")
    label: str
    total_score: float = Field(alias="totalScore")

    model_config = {"populate_by_name": True}


class AgentProposal(BaseModel):
    """Structured output of the reasoning provider / ReviewerAgent.

    ``decision`` is one of the 4 ReviewState labels; ``justification`` cites the specific
    edges/scores used; ``confidence`` is a float in [0, 1].
    """

    decision: ReviewState
    justification: str
    confidence: float = Field(ge=0.0, le=1.0)
    cited_edge_ids: list[str] = Field(default_factory=list, alias="citedEdgeIds")
    provider: str
    model: str
    prompt_version: str = Field(default=PROMPT_VERSION, alias="promptVersion")

    model_config = {"populate_by_name": True}


class RoutingDecision(BaseModel):
    """Pure routing output: an action plus a human-readable rationale."""

    action: RoutingAction
    rationale: str

    model_config = {"populate_by_name": True}


class AuthoringDraft(BaseModel):
    """A DRAFT canonical merged article. Persisted to the drafts store ONLY.

    Never written to the source KB index. ``member_article_ids`` is the provenance trail.
    """

    draft_id: str = Field(alias="draftId")
    cluster_id: str = Field(alias="clusterId")
    title: str
    body_markdown: str = Field(alias="bodyMarkdown")
    member_article_ids: list[str] = Field(alias="memberArticleIds")
    representative_article_id: str = Field(alias="representativeArticleId")
    provider: str
    model: str
    prompt_version: str = Field(default=PROMPT_VERSION, alias="promptVersion")
    generated_at: str = Field(alias="generatedAt")
    status: Literal["draft"] = "draft"

    model_config = {"populate_by_name": True}


class AgentEpisode(BaseModel):
    """One logged agent decision (the learning-loop record).

    ``human_outcome`` is null now and filled later when a human acts; everything else
    captures the inputs, the proposal, the routing decision, and provenance.

    Memory layer additions:
    - ``inputs_summary`` is a stable, deterministic text rendering of the cluster inputs
      the reviewer reasoned over; it is what gets embedded for recall.
    - ``embedding`` is that summary's vector, stored ON the episode doc (no new vector
      store) so recall is a kNN/script_score over ``kcs-kb-agent-episodes-v1``.
    - ``recalled_episode_ids`` records which past episodes were recalled as precedent
      when this episode was created (ids in similarity order), for auditability.
    """

    episode_id: str = Field(alias="episodeId")
    cluster_id: str = Field(alias="clusterId")
    ts: str
    agent: str
    member_article_ids: list[str] = Field(alias="memberArticleIds")
    strongest_edges: list[EdgeRef] = Field(alias="strongestEdges")
    evidence_refs: list[str] = Field(alias="evidenceRefs")
    inputs_summary: str = Field(default="", alias="inputsSummary")
    proposal: AgentProposal
    routing_decision: RoutingDecision = Field(alias="routingDecision")
    draft_id: str | None = Field(default=None, alias="draftId")
    human_outcome: str | None = Field(default=None, alias="humanOutcome")
    embedding: list[float] = Field(default_factory=list)
    recalled_episode_ids: list[str] = Field(default_factory=list, alias="recalledEpisodeIds")
    provider: str
    model: str
    prompt_version: str = Field(default=PROMPT_VERSION, alias="promptVersion")

    model_config = {"populate_by_name": True}


def build_inputs_summary(
    *,
    cluster_id: str,
    member_article_ids: list[str],
    edges: list[EdgeRef],
    review_state: str,
) -> str:
    """Render the cluster inputs into a stable text summary for embedding/recall.

    Deterministic (sorted, fixed format) so the same cluster shape always embeds to the
    same vector. This is the episode's ``inputs_summary`` — the recall key.
    """
    edge_parts = sorted(
        f"{edge.label}:{edge.left_article_id}-{edge.right_article_id}@{edge.total_score:.3f}"
        for edge in edges
    )
    members = " ".join(sorted(member_article_ids))
    labels = " ".join(sorted({edge.label for edge in edges}))
    return (
        f"members={len(member_article_ids)} state={review_state} "
        f"labels=[{labels}] articles=[{members}] edges=[{' '.join(edge_parts)}]"
    )


def episode_to_document(episode: AgentEpisode) -> dict[str, Any]:
    """Serialise an episode to the snake_case shape persisted in Elasticsearch."""
    return episode.model_dump(by_alias=False)
