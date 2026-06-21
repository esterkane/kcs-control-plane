"""Swappable reasoning providers for the ReviewerAgent.

Mirrors ``app/explanations/providers.py``: a ``Protocol`` plus a transport abstraction,
a Gemini HTTP impl, and structured pydantic output. The DEFAULT is the offline,
fully-deterministic ``DeterministicReasoningProvider`` so every test and the default code
path need no API key and never touch the network.

Both providers return an ``AgentProposal`` whose ``decision`` is one of the 4
``ReviewState`` labels, whose ``justification`` cites the specific edges/scores used, and
whose ``confidence`` is a float in [0, 1].
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.models import PROMPT_VERSION, AgentProposal
from app.clustering.service import (
    ClusterDetailResponse,
    DuplicateEdgeDocument,
    _connected_components,
    _is_bridge,
    _is_strong_near_duplicate,
)
from app.config import (
    get_gemini_api_key,
    get_gemini_api_url,
    get_gemini_model,
)

# Score bands used by the deterministic provider. Aligned with the clustering service's
# default weak-edge threshold (0.78) so the agent reasons over the same structure the
# deterministic pipeline used to build the cluster.
STRONG_SCORE = 0.84
WEAK_SCORE = 0.78


class AgentReasoningProvider(Protocol):
    provider_name: str

    def propose(
        self, cluster: ClusterDetailResponse, *, precedent: str = ""
    ) -> AgentProposal: ...


def _strong_edges(edges: list[DuplicateEdgeDocument]) -> list[DuplicateEdgeDocument]:
    return [
        edge
        for edge in edges
        if edge.label == "exact_duplicate"
        or _is_strong_near_duplicate(edge, min_total_score=STRONG_SCORE)
    ]


def _is_fully_connected_strong(cluster: ClusterDetailResponse) -> bool:
    """True when the strong-edge subgraph keeps every member in one component."""
    strong = _strong_edges(cluster.edges)
    if not strong:
        return False
    components = _connected_components(cluster.article_ids, strong)
    return len(components) == 1


def _has_removable_bridge(cluster: ClusterDetailResponse) -> bool:
    """True when some edge is a *meaningful* bridge: removing it separates the cluster
    into two genuine subgroups (each with >= 2 members), not merely shaving off a
    singleton. Splitting a 2-node family into two singletons is not a real split — that
    mirrors the clustering service, which only splits multi-node components.
    """
    edges = cluster.edges
    for edge in edges:
        if not _is_bridge(edge, cluster.article_ids, edges):
            continue
        remaining = [candidate for candidate in edges if candidate.edge_id != edge.edge_id]
        components = _connected_components(cluster.article_ids, remaining)
        # Count components that lost a member to this split and still hold >= 2 members.
        substantive = [component for component in components if len(component) >= 2]
        if len(substantive) >= 2:
            return True
    return False


class DeterministicReasoningProvider:
    """Rule-based, offline reasoning derived from edge confidence/structure.

    Decision rules (in order):
    - ``approved_family``  — strong, fully-connected component (every member linked by an
      exact/strong-near edge), no removable bridge.
    - ``split_required``   — multiple components, OR a removable bridge in an
      otherwise-connected graph (the deterministic pipeline's split signal).
    - ``rejected_family``  — contradictory: members exist but the strong-edge subgraph
      leaves the cluster disconnected with no single dominant component and weak overall
      scores (evidence does not support a family).
    - ``pending_review``   — weak / sparse / ambiguous: anything else.

    The justification always cites the specific edges/scores used.
    """

    provider_name = "deterministic"

    def propose(self, cluster: ClusterDetailResponse, *, precedent: str = "") -> AgentProposal:
        # ``precedent`` (recalled similar past episodes) is accepted for interface parity
        # with the LLM provider, but the deterministic decision is derived ONLY from the
        # cluster's edge structure: recall must never change the deterministic outcome, so
        # the default code path stays reproducible whether or not memory is enabled.
        edges = cluster.edges
        scores = [edge.total_score for edge in edges]
        max_score = max(scores) if scores else 0.0
        mean_score = (sum(scores) / len(scores)) if scores else 0.0
        components = _connected_components(cluster.article_ids, edges)
        strong = _strong_edges(edges)
        cited = sorted(
            (edge.edge_id for edge in (strong or edges)),
        )[:5]

        if len(components) > 1:
            decision = "split_required"
            confidence = min(0.9, 0.6 + 0.1 * (len(components) - 1))
            justification = (
                f"The cluster splits into {len(components)} connected components over its "
                f"{len(edges)} supporting edge(s); membership is not a single family. "
                f"Strongest edge score={max_score:.3f}."
            )
        elif _is_fully_connected_strong(cluster) and not _has_removable_bridge(cluster):
            decision = "approved_family"
            confidence = min(0.97, 0.7 + (max_score - STRONG_SCORE))
            justification = (
                f"All {cluster.member_count} members form one fully-connected component over "
                f"{len(strong)} strong/exact edge(s) (max score={max_score:.3f}, "
                f"mean={mean_score:.3f}); no removable bridge. Strong evidence of one family."
            )
        elif _has_removable_bridge(cluster):
            decision = "split_required"
            confidence = 0.62
            justification = (
                "A removable bridge edge connects otherwise-separable subgroups; removing it "
                f"would split the cluster. Edges={len(edges)}, max score={max_score:.3f}."
            )
        elif not strong and max_score < WEAK_SCORE:
            decision = "rejected_family"
            confidence = 0.58
            justification = (
                "No strong/exact edges and all supporting scores are below the weak-edge "
                f"threshold ({WEAK_SCORE}); evidence contradicts a merge. "
                f"Max score={max_score:.3f}, mean={mean_score:.3f}."
            )
        else:
            decision = "pending_review"
            confidence = 0.5
            justification = (
                "Evidence is mixed: the cluster is connected but not strongly fully-connected. "
                f"Strong edges={len(strong)}, edges={len(edges)}, max score={max_score:.3f}, "
                f"mean={mean_score:.3f}. A human should review."
            )

        return AgentProposal(
            decision=decision,
            justification=justification,
            confidence=round(confidence, 4),
            citedEdgeIds=cited,
            provider=self.provider_name,
            model=self.provider_name,
            promptVersion=PROMPT_VERSION,
        )


# --- LLM provider (mirrors explanations/providers.py Gemini transport pattern) --------


@dataclass(frozen=True)
class ReasoningResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class ReasoningTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ReasoningResponse: ...


class ReasoningProviderError(RuntimeError):
    pass


class HttpxReasoningTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ReasoningResponse:
        import httpx

        response = httpx.request(method=method, url=url, headers=headers, json=json_body, timeout=30.0)
        try:
            parsed = response.json()
        except json.JSONDecodeError:
            parsed = None
        return ReasoningResponse(
            status_code=response.status_code,
            json_body=parsed if isinstance(parsed, dict) else None,
            text=response.text,
        )


def _reviewer_prompt(cluster: ClusterDetailResponse, *, precedent: str = "") -> str:
    precedent_block = (
        f"Precedent (similar past decisions; consider but do not blindly copy):\n{precedent}\n"
        if precedent
        else ""
    )
    return (
        "You are an editorial reviewer for deterministic KB duplicate clusters.\n"
        "Decide whether the cluster is a single duplicate family.\n"
        'Return JSON only with keys: decision, justification, confidence, citedEdgeIds.\n'
        "decision MUST be one of: approved_family, pending_review, rejected_family, split_required.\n"
        "Cite the specific edge ids/scores you used in citedEdgeIds and justification.\n"
        "Never invent members or edges beyond those provided.\n"
        f"Prompt version: {PROMPT_VERSION}\n"
        f"{precedent_block}"
        f"Cluster id: {cluster.cluster_id}\n"
        f"Member article ids: {cluster.article_ids}\n"
        f"Representative: {cluster.representative_article_id}\n"
        f"Current review state: {cluster.review_state}\n"
        f"Supporting edges: "
        f"{[{'edgeId': e.edge_id, 'label': e.label, 'totalScore': e.total_score, 'reasons': e.evidence.reasons} for e in cluster.edges]}\n"
    )


class LlmReasoningProvider:
    """Gemini-backed reasoning provider. Selected only via env; never used in tests or
    the default path. Same structured ``AgentProposal`` output as the deterministic one."""

    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_url: str,
        model: str,
        api_key: str,
        transport: ReasoningTransport | None = None,
    ) -> None:
        self.api_url = api_url
        self.model = model
        self.api_key = api_key
        self.transport = transport or HttpxReasoningTransport()

    def propose(self, cluster: ClusterDetailResponse, *, precedent: str = "") -> AgentProposal:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        response = self.transport.request(
            "POST",
            self.api_url,
            headers=headers,
            json_body={
                "contents": [{"parts": [{"text": _reviewer_prompt(cluster, precedent=precedent)}]}],
                "generationConfig": {"temperature": 0.1},
            },
        )
        if response.status_code != 200:
            raise ReasoningProviderError(
                f"Unexpected Gemini response {response.status_code}: {response.text}"
            )
        candidate_text = (
            response.json_body.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text")
            if response.json_body
            else None
        )
        if not isinstance(candidate_text, str):
            raise ReasoningProviderError(f"Gemini response missing text candidate: {response.json_body}")
        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            raise ReasoningProviderError(f"Gemini response was not valid JSON: {candidate_text}") from exc
        if not isinstance(parsed, dict):
            raise ReasoningProviderError(f"Gemini response JSON was not an object: {parsed}")
        return AgentProposal.model_validate(
            {
                **parsed,
                "provider": self.provider_name,
                "model": self.model,
                "promptVersion": PROMPT_VERSION,
            }
        )


def create_reasoning_provider(
    *,
    provider_name: str | None = None,
    transport: ReasoningTransport | None = None,
) -> AgentReasoningProvider:
    """Factory selecting the reasoning provider by env (default deterministic)."""
    from app.config import get_agent_reasoning_provider

    name = (provider_name or get_agent_reasoning_provider()).casefold()
    if name in {"gemini", "llm"}:
        return LlmReasoningProvider(
            api_url=get_gemini_api_url(),
            model=get_gemini_model(),
            api_key=get_gemini_api_key(),
            transport=transport,
        )
    return DeterministicReasoningProvider()
