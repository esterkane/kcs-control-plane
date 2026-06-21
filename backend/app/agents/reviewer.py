"""ReviewerAgent: proposes a review decision for a persisted cluster.

Input is a cluster fetched via the agent tools (which reuse the read-only ``get_cluster``
MCP tool / cluster service). Output is an ``AgentProposal`` whose decision is one of the 4
``ReviewState`` labels, with a justification citing specific edges/evidence. The actual
reasoning is delegated to the swappable ``AgentReasoningProvider`` (deterministic default).
"""

from __future__ import annotations

from app.agents.models import AgentProposal
from app.agents.providers import AgentReasoningProvider, DeterministicReasoningProvider
from app.agents.tools import fetch_cluster
from app.clustering.service import ClusterDetailResponse
from app.mcp.tools import ClusterServiceLike

AGENT_NAME = "reviewer"


class ReviewerAgent:
    def __init__(
        self,
        *,
        cluster_service: ClusterServiceLike,
        reasoning_provider: AgentReasoningProvider | None = None,
    ) -> None:
        self.cluster_service = cluster_service
        self.reasoning_provider: AgentReasoningProvider = (
            reasoning_provider or DeterministicReasoningProvider()
        )

    def review_cluster(
        self, cluster_id: str, *, precedent: str = ""
    ) -> tuple[ClusterDetailResponse, AgentProposal]:
        """Fetch the cluster via tools and return (cluster, proposal).

        The cluster is returned alongside the proposal so the supervisor can route on the
        same data the reviewer reasoned over, without a second fetch. ``precedent`` is the
        recalled-episode context (empty when memory is disabled).
        """
        cluster = self.fetch(cluster_id)
        proposal = self.review(cluster, precedent=precedent)
        return cluster, proposal

    def fetch(self, cluster_id: str) -> ClusterDetailResponse:
        """Fetch a persisted cluster via the read-only tools (no reasoning).

        Lets a caller (the supervisor) obtain the cluster before proposing, e.g. to recall
        precedent from similar past episodes, without a second fetch at review time.
        """
        return fetch_cluster(cluster_id, service=self.cluster_service)

    def review(self, cluster: ClusterDetailResponse, *, precedent: str = "") -> AgentProposal:
        """Propose a decision for an already-fetched cluster."""
        return self.reasoning_provider.propose(cluster, precedent=precedent)
