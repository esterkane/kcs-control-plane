"""Agent tools: thin accessors over the EXISTING cluster service / MCP tools.

Agents MUST obtain cluster data through these tools — they never fabricate members,
edges, or evidence. ``fetch_cluster`` reuses ``get_cluster_impl`` from the read-only MCP
layer (which itself wraps ``DuplicateClusterService.get_cluster``), so there is exactly
one path to cluster data and the structured error contract is preserved.

The edge/evidence accessors operate on the already-fetched ``ClusterDetailResponse`` —
they do not issue new queries; they just surface the strongest edges and evidence refs
the reasoning provider and episode logger need.
"""

from __future__ import annotations

from typing import Any

from app.agents.models import EdgeRef
from app.clustering.service import ClusterDetailResponse, DuplicateEdgeDocument
from app.mcp.tools import ClusterServiceLike, get_cluster_impl


class AgentToolError(RuntimeError):
    """Raised when a tool cannot return real cluster data (e.g. unknown cluster)."""


def fetch_cluster(cluster_id: str, *, service: ClusterServiceLike) -> ClusterDetailResponse:
    """Fetch a persisted cluster via the existing read-only ``get_cluster`` MCP tool.

    Returns the typed ``ClusterDetailResponse`` (members, edges, evidence). Surfaces the
    MCP business/validation/transient error as an ``AgentToolError`` rather than a raw
    dict, so agents fail loudly instead of fabricating data.
    """
    payload = get_cluster_impl(cluster_id, service=service)
    if isinstance(payload, dict) and payload.get("isError"):
        raise AgentToolError(payload.get("message", f"Could not fetch cluster {cluster_id}"))
    return ClusterDetailResponse.model_validate(payload)


def strongest_edges(cluster: ClusterDetailResponse, *, limit: int = 5) -> list[DuplicateEdgeDocument]:
    """Return the cluster's supporting edges, strongest first (by total score)."""
    return sorted(
        cluster.edges,
        key=lambda edge: (edge.total_score, edge.label, edge.edge_id),
        reverse=True,
    )[:limit]


def edge_refs(edges: list[DuplicateEdgeDocument]) -> list[EdgeRef]:
    """Compact citation refs for the strongest edges (for proposals/episodes)."""
    return [
        EdgeRef(
            edgeId=edge.edge_id,
            leftArticleId=edge.left_article_id,
            rightArticleId=edge.right_article_id,
            label=edge.label,
            totalScore=edge.total_score,
        )
        for edge in edges
    ]


def evidence_refs(cluster: ClusterDetailResponse) -> list[str]:
    """Stable references to the evidence backing the cluster (chunk-pair + reason refs).

    These are pointers into the existing edge evidence — never new evidence — so an
    episode can be audited back to the deterministic signals it was built from.
    """
    refs: list[str] = []
    for edge in cluster.edges:
        for reason in edge.evidence.reasons:
            ref = f"{edge.edge_id}:reason:{reason}"
            if ref not in refs:
                refs.append(ref)
        for chunk in edge.evidence.most_similar_chunks:
            ref = f"{edge.edge_id}:chunk:{chunk.query_chunk_id}->{chunk.candidate_chunk_id}"
            if ref not in refs:
                refs.append(ref)
    return refs


def cluster_signals(cluster: ClusterDetailResponse) -> dict[str, Any]:
    """Derive the deterministic structural signals the routing function consumes.

    Pure aggregation over the already-fetched cluster — no new logic, no new queries.
    """
    edges = cluster.edges
    scores = [edge.total_score for edge in edges]
    exact_count = sum(1 for edge in edges if edge.label == "exact_duplicate")
    return {
        "member_count": cluster.member_count,
        "edge_count": len(edges),
        "review_state": cluster.review_state,
        "max_edge_score": max(scores) if scores else 0.0,
        "min_edge_score": min(scores) if scores else 0.0,
        "mean_edge_score": (sum(scores) / len(scores)) if scores else 0.0,
        "exact_edge_count": exact_count,
    }
