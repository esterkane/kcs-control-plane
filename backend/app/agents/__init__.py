"""Multi-agent editorial supervisor over the deterministic duplicate-cluster pipeline.

This package WRAPS the existing deterministic clustering/similarity services as agent
tools — it never re-implements clustering or dedup logic, and it never writes back to
the read-only source KB index (``kcs-kb-articles-v1``). Everything is gated behind the
``AGENTS_ENABLED`` feature flag (default false) and runs offline by default via the
deterministic reasoning provider.

Agents:
- ``ReviewerAgent``    proposes a review decision (one of the 4 ReviewState labels) with
                       a justification citing specific edges/evidence.
- ``AuthoringAgent``   drafts a canonical merged article (DRAFT-only) for an approved family.
- ``SupervisorAgent``  routes (auto_approve / send_to_human / split / reject) via a pure
                       routing function and persists only review state + the draft.
"""

from __future__ import annotations

from app.agents.models import (
    AgentEpisode,
    AgentProposal,
    AuthoringDraft,
    RoutingDecision,
)
from app.agents.providers import (
    AgentReasoningProvider,
    DeterministicReasoningProvider,
    LlmReasoningProvider,
    create_reasoning_provider,
)
from app.agents.routing import route_proposal
from app.agents.reviewer import ReviewerAgent
from app.agents.authoring import AuthoringAgent, SOURCE_KB_INDEX
from app.agents.supervisor import SupervisorAgent, SupervisorOutcome
from app.agents.memory import (
    EpisodicMemory,
    LocalDeterministicEmbedder,
    RecalledEpisode,
    format_precedent,
)
from app.agents.learning import (
    LabeledEdge,
    RecalibrationRejected,
    ThresholdProposal,
    apply_recalibration,
    labeled_edges_from_episodes,
    recalibrate,
)

__all__ = [
    "AgentEpisode",
    "AgentProposal",
    "AgentReasoningProvider",
    "AuthoringAgent",
    "AuthoringDraft",
    "DeterministicReasoningProvider",
    "EpisodicMemory",
    "LabeledEdge",
    "LlmReasoningProvider",
    "LocalDeterministicEmbedder",
    "RecalibrationRejected",
    "RecalledEpisode",
    "ReviewerAgent",
    "RoutingDecision",
    "SOURCE_KB_INDEX",
    "SupervisorAgent",
    "SupervisorOutcome",
    "ThresholdProposal",
    "apply_recalibration",
    "create_reasoning_provider",
    "format_precedent",
    "labeled_edges_from_episodes",
    "recalibrate",
    "route_proposal",
]
