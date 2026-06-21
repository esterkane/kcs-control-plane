"""Adapter wiring the existing similar-article service into the reusable
``relevance_eval`` skill's injected-search contract.

The skill (``relevance_eval.run_evaluation``) is backend-agnostic: it takes a
``search_fn(query, strategy) -> list[doc_id]`` and computes Precision@k / MRR@k /
nDCG@k against a judgments file. For duplicate detection the natural "query" is a
*seed article id* and the "documents" are its candidate duplicate article ids.

This module is a THIN adapter — it holds no similarity business logic. It maps a
strategy name to the signal flags the existing :meth:`SimilarArticleService.search`
already accepts (``include_chunk_seed`` / ``include_cve``), calls that unchanged
service, and extracts the ranked candidate ``article_id`` list. All ranking,
scoring, and evidence stays inside the real service.
"""

from __future__ import annotations

from typing import Protocol

from app.similarity.service import SimilarSearchRequest, SimilarSearchResponse

# Each strategy is a named bundle of the signal flags the similar-article service
# already supports. Adding a strategy here does NOT change retrieval logic — it
# only toggles existing flags, so the eval compares signal variants of the same
# service.
STRATEGY_FLAGS: dict[str, dict[str, bool]] = {
    # Default duplicate retrieval: article-level lexical + vector signals only.
    "embedding": {"include_chunk_seed": False, "include_cve": False},
    # Adds the chunk-seed signal (chunk-level kNN seeding) on top of the default.
    "chunk_seeded": {"include_chunk_seed": True, "include_cve": False},
}

# How many candidates to request per seed. Wide enough to cover the metric ks the
# runner uses (1, 3, 5, 10) with headroom.
DEFAULT_LIMIT = 10


class SimilarityServiceLike(Protocol):
    def search(self, request: SimilarSearchRequest) -> SimilarSearchResponse: ...


def make_search_fn(
    service: SimilarityServiceLike,
    *,
    limit: int = DEFAULT_LIMIT,
    strategy_flags: dict[str, dict[str, bool]] | None = None,
):
    """Return a ``search(article_id, strategy) -> list[str]`` for the skill.

    ``article_id`` is the seed (the skill's "query"); the return value is the
    ranked list of candidate duplicate article ids, best first — exactly the
    order the service already produces.
    """
    flags_table = strategy_flags or STRATEGY_FLAGS

    def search(article_id: str, strategy: str) -> list[str]:
        try:
            flags = flags_table[strategy]
        except KeyError:
            raise ValueError(
                f"Unknown strategy {strategy!r}. Known: {sorted(flags_table)}"
            ) from None

        response = service.search(
            SimilarSearchRequest(
                articleId=article_id,
                includeChunkSeed=flags["include_chunk_seed"],
                includeCve=flags["include_cve"],
                limit=limit,
            )
        )
        return [candidate.article_id for candidate in response.candidates]

    return search
