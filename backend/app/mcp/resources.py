"""Lazily-constructed service singletons for the MCP layer.

The MCP server is a sibling front-end to the FastAPI app: both adapt the same
duplicate-detection / cluster-review core to a transport. These accessors reuse
the existing dependency wiring (``build_similarity_service`` /
``build_duplicate_cluster_service``) rather than re-constructing Elasticsearch
clients, embedding providers, or rerankers here — so the MCP layer never drifts
from the HTTP API's construction logic.

Each service is cached for the process lifetime and built on first use.
"""

from functools import lru_cache

from app.clustering.service import DuplicateClusterService, build_duplicate_cluster_service
from app.similarity.service import SimilarArticleService, build_similarity_service


@lru_cache
def get_similarity_service() -> SimilarArticleService:
    return build_similarity_service()


@lru_cache
def get_cluster_service() -> DuplicateClusterService:
    return build_duplicate_cluster_service()
