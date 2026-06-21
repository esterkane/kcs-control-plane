"""SupervisorAgent: orchestrates reviewer -> routing -> (state + draft) -> episode.

Gated behind ``AGENTS_ENABLED`` (default false). When disabled, ``supervise`` is a no-op
that returns ``None`` and changes nothing — proving off-by-default isolation.

Persistence policy (humans stay in the loop on the ambiguous middle):
- ``auto_approve`` -> persist ``approved_family`` via ``update_cluster_review_state`` AND
  attach an AuthoringAgent draft.
- ``split``        -> persist ``split_required``.
- ``reject``       -> persist ``rejected_family``.
- ``send_to_human``-> DO NOT change review state; no draft.

Only review state + the draft are persisted; every decision is logged as an episode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1

from app.agents.authoring import AuthoringAgent
from app.agents.episodes import EpisodeRepositoryProtocol
from app.agents.memory import EpisodicMemory, RecalledEpisode, format_precedent
from app.agents.models import (
    PROMPT_VERSION,
    AgentEpisode,
    AgentProposal,
    AuthoringDraft,
    RoutingDecision,
    build_inputs_summary,
)
from app.agents.reviewer import ReviewerAgent
from app.agents.routing import route_proposal
from app.agents.tools import cluster_signals, edge_refs, evidence_refs, strongest_edges
from app.clustering.service import ClusterDetailResponse
from app.config import (
    ClusterReviewUpdateRequest,
    are_agents_enabled,
    is_memory_enabled,
)

AGENT_NAME = "supervisor"

# Routing action -> review state to persist (None means "do not change state").
_ACTION_TO_STATE: dict[str, str | None] = {
    "auto_approve": "approved_family",
    "split": "split_required",
    "reject": "rejected_family",
    "send_to_human": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _episode_id(cluster_id: str, ts: str) -> str:
    digest = sha1(f"{cluster_id}|{ts}".encode("utf-8")).hexdigest()[:16]
    return f"episode-{digest}"


@dataclass
class SupervisorOutcome:
    cluster_id: str
    proposal: AgentProposal
    routing_decision: RoutingDecision
    review_state_persisted: str | None
    draft: AuthoringDraft | None
    episode: AgentEpisode


class SupervisorAgent:
    def __init__(
        self,
        *,
        cluster_service: object,
        reviewer: ReviewerAgent,
        authoring_agent: AuthoringAgent,
        episode_repository: EpisodeRepositoryProtocol,
        memory: EpisodicMemory | None = None,
    ) -> None:
        # ``cluster_service`` is used both for the reviewer's read path and for the
        # supervisor's review-state write (``update_cluster_review_state``).
        self.cluster_service = cluster_service
        self.reviewer = reviewer
        self.authoring_agent = authoring_agent
        self.episode_repository = episode_repository
        # ``memory`` enables recall-before-acting. It is only consulted when
        # ``MEMORY_ENABLED`` is true AND a memory was injected; otherwise the path is the
        # original (no recall, reproducible).
        self.memory = memory

    def supervise(self, cluster_id: str) -> SupervisorOutcome | None:
        """Run the editorial pipeline for one cluster.

        Returns ``None`` when ``AGENTS_ENABLED`` is false (no-op, nothing persisted).
        """
        if not are_agents_enabled():
            return None
        return self._supervise(cluster_id)

    def _supervise(self, cluster_id: str) -> SupervisorOutcome:
        # Fetch the cluster once, then (optionally) recall precedent BEFORE the reviewer
        # proposes, then review with that precedent in context.
        cluster = self.reviewer.fetch(cluster_id)
        inputs_summary = self._inputs_summary(cluster)
        recalled = self._recall(inputs_summary, current_episode_cluster=cluster.cluster_id)
        precedent = format_precedent(recalled)
        proposal = self.reviewer.review(cluster, precedent=precedent)
        signals = cluster_signals(cluster)
        routing_decision = route_proposal(proposal, signals)

        review_state_to_persist = _ACTION_TO_STATE[routing_decision.action]
        draft: AuthoringDraft | None = None

        if review_state_to_persist is not None:
            self.cluster_service.update_cluster_review_state(
                cluster_id=cluster_id,
                request=ClusterReviewUpdateRequest(reviewState=review_state_to_persist),
            )
        if routing_decision.action == "auto_approve":
            draft = self.authoring_agent.draft_for_cluster(cluster)

        episode = self._build_episode(
            cluster=cluster,
            proposal=proposal,
            routing_decision=routing_decision,
            draft=draft,
            inputs_summary=inputs_summary,
            recalled=recalled,
        )
        self.episode_repository.log(episode)

        return SupervisorOutcome(
            cluster_id=cluster_id,
            proposal=proposal,
            routing_decision=routing_decision,
            review_state_persisted=review_state_to_persist,
            draft=draft,
            episode=episode,
        )

    def _inputs_summary(self, cluster: ClusterDetailResponse) -> str:
        return build_inputs_summary(
            cluster_id=cluster.cluster_id,
            member_article_ids=list(cluster.article_ids),
            edges=edge_refs(cluster.edges),
            review_state=cluster.review_state,
        )

    def _recall(
        self, inputs_summary: str, *, current_episode_cluster: str
    ) -> list[RecalledEpisode]:
        """Recall similar past episodes as precedent. No-op unless memory is enabled.

        Returns an empty list (and queries nothing) when ``MEMORY_ENABLED`` is false or no
        memory was injected, so the default path is reproducible and unchanged.
        """
        if self.memory is None or not is_memory_enabled():
            return []
        return self.memory.recall(inputs_summary)

    def _build_episode(
        self,
        *,
        cluster: ClusterDetailResponse,
        proposal: AgentProposal,
        routing_decision: RoutingDecision,
        draft: AuthoringDraft | None,
        inputs_summary: str,
        recalled: list[RecalledEpisode],
    ) -> AgentEpisode:
        ts = _now_iso()
        top_edges = strongest_edges(cluster)
        # Embed the inputs summary so the episode is itself recallable later. When memory
        # is wired, this reuses the same embedder recall uses; with no memory the field is
        # left empty (recall is off anyway).
        embedding = self.memory.embed_inputs(inputs_summary) if self.memory is not None else []
        return AgentEpisode(
            episodeId=_episode_id(cluster.cluster_id, ts),
            clusterId=cluster.cluster_id,
            ts=ts,
            agent=AGENT_NAME,
            memberArticleIds=list(cluster.article_ids),
            strongestEdges=edge_refs(top_edges),
            evidenceRefs=evidence_refs(cluster),
            inputsSummary=inputs_summary,
            proposal=proposal,
            routingDecision=routing_decision,
            draftId=draft.draft_id if draft else None,
            humanOutcome=None,
            embedding=embedding,
            recalledEpisodeIds=[item.episode_id for item in recalled],
            provider=proposal.provider,
            model=proposal.model,
            promptVersion=PROMPT_VERSION,
        )
