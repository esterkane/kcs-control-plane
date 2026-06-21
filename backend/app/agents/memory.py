"""Episodic memory: embed episodes and recall the most-similar past ones.

This is the "recall-before-acting" half of the learning layer. It REUSES the existing
vector infrastructure — there is NO new vector store:

- The embedding is computed by an ``EmbeddingProvider`` (the same ``embed_batch(texts,
  task)`` protocol as ``app.embeddings.providers``). In production this is the real
  Jina/local provider; in tests and the offline default it is the deterministic
  ``LocalDeterministicEmbedder`` below, which needs no network.
- The embedding is stored ON the episode document in ``kcs-kb-agent-episodes-v1`` (see
  ``EPISODE_INDEX_MAPPING``), and recall is a kNN / ``script_score`` cosine query over
  that same index via the existing ``ElasticsearchClient.search``.

``recall`` returns the ``RecalledEpisode``s (past decisions + their human outcomes) in
descending similarity order so the reviewer can use them as precedent.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.models import AgentEpisode
from app.config import (
    get_agent_episode_index,
    get_duplicate_embedding_dims,
    get_duplicate_embedding_task,
    get_memory_recall_k,
)


class EmbeddingProviderLike(Protocol):
    def embed_batch(self, texts: list[str], task: str) -> list[list[float]]: ...


class EpisodeSearchClientLike(Protocol):
    def search(self, *, index: str, body: dict[str, Any]) -> list[dict[str, Any]]: ...


class LocalDeterministicEmbedder:
    """Offline, dependency-free embedder used by default and in tests.

    Hashes whitespace tokens into a fixed-dimension bag-of-features vector and L2
    normalises it, so cosine similarity is meaningful and identical inputs always map to
    identical vectors. Same ``embed_batch(texts, task)`` contract as the real providers,
    so the memory service is agnostic to which embedder it was given.
    """

    def __init__(self, *, dims: int | None = None) -> None:
        self.dims = dims or get_duplicate_embedding_dims()

    def embed_batch(self, texts: list[str], task: str) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        tokens = text.lower().split()
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Stable non-zero vector for empty/degenerate input so cosine is defined.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


@dataclass(frozen=True)
class RecalledEpisode:
    """A past episode surfaced as precedent, with its similarity to the query inputs."""

    episode_id: str
    cluster_id: str
    similarity: float
    decision: str
    routing_action: str
    human_outcome: str | None


class EpisodicMemory:
    """Embeds an episode's inputs summary and recalls similar past episodes.

    ``embedder`` defaults to the offline deterministic embedder so the default path and
    the test gate never touch the network; production wiring passes the real duplicate
    embedding provider. ``es_client`` only needs ``search``; in tests it is faked with a
    canned vector store.
    """

    def __init__(
        self,
        *,
        es_client: EpisodeSearchClientLike,
        embedder: EmbeddingProviderLike | None = None,
        episode_index: str | None = None,
        task: str | None = None,
    ) -> None:
        self.es_client = es_client
        self.embedder: EmbeddingProviderLike = embedder or LocalDeterministicEmbedder()
        self.episode_index = episode_index or get_agent_episode_index()
        self.task = task or get_duplicate_embedding_task()

    def embed_inputs(self, inputs_summary: str) -> list[float]:
        """Embed one episode's inputs summary (the recall key)."""
        return self.embedder.embed_batch([inputs_summary], self.task)[0]

    def recall(
        self,
        query_inputs: str,
        *,
        k: int | None = None,
        exclude_episode_ids: list[str] | None = None,
    ) -> list[RecalledEpisode]:
        """Return the ``k`` most-similar past episodes (descending similarity).

        Embeds ``query_inputs``, then runs a ``script_score`` cosine query over the
        episode index. Only episodes that already carry an embedding are scored. The
        current episode (and any explicitly excluded ids) are filtered out so an episode
        never recalls itself.
        """
        top_k = k or get_memory_recall_k()
        query_vector = self.embed_inputs(query_inputs)
        excluded = list(exclude_episode_ids or [])

        must_not: list[dict[str, Any]] = []
        if excluded:
            must_not.append({"terms": {"episode_id": excluded}})

        body: dict[str, Any] = {
            "size": top_k,
            "query": {
                "script_score": {
                    "query": {
                        "bool": {
                            "filter": [{"exists": {"field": "embedding"}}],
                            "must_not": must_not,
                        }
                    },
                    "script": {
                        # +1.0 keeps the score positive (ES script_score requires >= 0).
                        "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                        "params": {"query_vector": query_vector},
                    },
                }
            },
        }
        hits = self.es_client.search(index=self.episode_index, body=body)
        recalled: list[RecalledEpisode] = []
        for hit in hits:
            source = hit.get("_source")
            if not isinstance(source, dict):
                continue
            raw_score = hit.get("_score")
            similarity = (float(raw_score) - 1.0) if isinstance(raw_score, int | float) else 0.0
            proposal = source.get("proposal") or {}
            routing = source.get("routing_decision") or {}
            recalled.append(
                RecalledEpisode(
                    episode_id=str(source.get("episode_id", "")),
                    cluster_id=str(source.get("cluster_id", "")),
                    similarity=round(similarity, 6),
                    decision=str(proposal.get("decision", "")),
                    routing_action=str(routing.get("action", "")),
                    human_outcome=source.get("human_outcome"),
                )
            )
        return recalled


def format_precedent(recalled: list[RecalledEpisode]) -> str:
    """Render recalled episodes as a compact precedent block for provider context.

    Prefers the human outcome (ground truth) when present, else the agent decision.
    """
    if not recalled:
        return ""
    lines = ["Precedent from similar past episodes (most similar first):"]
    for item in recalled:
        outcome = item.human_outcome or f"{item.decision} (agent, no human outcome yet)"
        lines.append(
            f"- sim={item.similarity:.3f} cluster={item.cluster_id} "
            f"-> outcome={outcome} (routed {item.routing_action})"
        )
    return "\n".join(lines)


def embed_episode(episode: AgentEpisode, memory: EpisodicMemory) -> AgentEpisode:
    """Return a copy of ``episode`` with its ``inputs_summary`` embedding attached."""
    embedding = memory.embed_inputs(episode.inputs_summary)
    return episode.model_copy(update={"embedding": embedding})
