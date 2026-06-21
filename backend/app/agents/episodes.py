"""Episode logging: persist every agent decision to a dedicated ES index.

Uses the existing ``_ensure_index`` pattern (create-if-missing) behind a small repository
class so it can be faked in tests. ``human_outcome`` is null at write time and filled
later when a human acts (the learning loop).
"""

from __future__ import annotations

from typing import Any, Protocol

from app.agents.models import AgentEpisode, episode_to_document
from app.config import get_agent_episode_index
from app.elasticsearch.client import ElasticsearchClient

EPISODE_INDEX_MAPPING: dict[str, Any] = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "episode_id": {"type": "keyword"},
            "cluster_id": {"type": "keyword"},
            "ts": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "agent": {"type": "keyword"},
            "member_article_ids": {"type": "keyword"},
            "strongest_edges": {
                "type": "nested",
                "properties": {
                    "edge_id": {"type": "keyword"},
                    "left_article_id": {"type": "keyword"},
                    "right_article_id": {"type": "keyword"},
                    "label": {"type": "keyword"},
                    "total_score": {"type": "float"},
                },
            },
            "evidence_refs": {"type": "keyword"},
            "proposal": {
                "properties": {
                    "decision": {"type": "keyword"},
                    "justification": {"type": "text"},
                    "confidence": {"type": "float"},
                    "cited_edge_ids": {"type": "keyword"},
                    "provider": {"type": "keyword"},
                    "model": {"type": "keyword"},
                    "prompt_version": {"type": "keyword"},
                }
            },
            "routing_decision": {
                "properties": {
                    "action": {"type": "keyword"},
                    "rationale": {"type": "text"},
                }
            },
            "draft_id": {"type": "keyword"},
            "human_outcome": {"type": "keyword"},
            "provider": {"type": "keyword"},
            "model": {"type": "keyword"},
            "prompt_version": {"type": "keyword"},
        },
    },
}


class EpisodeRepositoryProtocol(Protocol):
    def log(self, episode: AgentEpisode) -> None: ...


class EpisodeRepository:
    def __init__(self, *, es_client: ElasticsearchClient, episode_index: str | None = None) -> None:
        self.es_client = es_client
        self.episode_index = episode_index or get_agent_episode_index()

    def _ensure_index(self) -> None:
        if not self.es_client.index_exists(index=self.episode_index):
            self.es_client.create_index(index=self.episode_index, mapping=EPISODE_INDEX_MAPPING)

    def log(self, episode: AgentEpisode) -> None:
        self._ensure_index()
        self.es_client.bulk_index(
            index=self.episode_index,
            documents=[(episode.episode_id, episode_to_document(episode))],
        )
