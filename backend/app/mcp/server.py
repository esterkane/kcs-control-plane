"""FastMCP server for kcs-control-plane.

Exposes the duplicate-detection / cluster-review core as three READ-ONLY MCP
tools that any MCP client (Claude Code, Cursor, an agent) can call:

- ``find_similar`` — likely duplicate / near-duplicate articles for an article.
- ``get_cluster`` — a persisted duplicate cluster with its supporting edges.
- ``list_review_queue`` — persisted clusters filtered by review state.

The tool *logic* lives in :mod:`app.mcp.tools` as plain functions; the wrappers
here supply the cached service singletons from :mod:`app.mcp.resources`.

This server is read-only by design: it deliberately does NOT expose ingestion,
admin pipeline control, remote publish, or any review-state mutation. A
mutation tool would only ever be added behind the ``MCP_ALLOW_MUTATIONS`` env
flag (default false); no such tool exists today.

Transport is selected by ``MCP_TRANSPORT``: ``stdio`` (default, for Claude Code)
or ``http`` (streamable-HTTP on ``MCP_HTTP_HOST`` / ``MCP_HTTP_PORT``).

Run it with::

    cd backend && .venv/bin/python -m app.mcp.server
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.resources import get_cluster_service, get_similarity_service
from app.mcp.tools import find_similar_impl, get_cluster_impl, list_review_queue_impl


def _mcp_transport() -> str:
    return os.getenv("MCP_TRANSPORT", "stdio").strip().casefold()


def _mcp_http_host() -> str:
    return os.getenv("MCP_HTTP_HOST", "127.0.0.1")


def _mcp_http_port() -> int:
    raw = os.getenv("MCP_HTTP_PORT", "8900").strip()
    try:
        return int(raw)
    except ValueError:
        return 8900


def mcp_allow_mutations() -> bool:
    """Whether mutation tools may be registered. Default false; no mutation tool
    exists today, but this flag documents the read-only invariant."""
    return os.getenv("MCP_ALLOW_MUTATIONS", "false").strip().casefold() in {"1", "true", "yes", "on"}


mcp = FastMCP(
    "kcs-control-plane",
    host=_mcp_http_host(),
    port=_mcp_http_port(),
)


@mcp.tool()
def find_similar(
    article_id: str,
    include_cve: bool = False,
    include_chunk_seed: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    """Find likely duplicate / near-duplicate KB articles for an existing article.

    WHAT IT DOES: Runs the hybrid duplicate-similarity search (lexical + dense
    embedding + chunk-seeded evidence, RRF-fused and optionally reranked) for the
    given article id and returns ranked candidate articles with their per-signal
    pair scores, a duplicate label, shared metadata, and chunk-level evidence —
    the same payload as ``GET /kb/articles/{article_id}/similar``.

    WHEN TO USE: To inspect what other articles look like duplicates of a known
    article before reviewing or clustering, or to gather evidence for a triage
    decision.

    WHEN NOT TO USE: To fetch an already-materialized cluster (use `get_cluster`)
    or to browse the review queue (use `list_review_queue`). This tool is
    read-only and does NOT create edges, clusters, or change any review state.

    INPUTS:
      - article_id (str, required): the local article id to search from. Must be a
        non-empty string.
      - include_cve (bool, default false): include CVE-style security articles as
        candidates.
      - include_chunk_seed (bool, default true): seed the search with chunk-level
        nearest neighbours (adds chunk evidence; slightly slower).
      - limit (int, default 10, 1..50): maximum candidates to return.

    OUTPUT: {queryArticleId, candidateCount, candidates: [{articleId, label,
    title, summary, pairScores: {...}, evidence: {sharedMetadata,
    mostSimilarChunks, reasons}}]}. `candidates` is ordered best-first and may be
    empty if nothing is similar.

    EDGE CASES & FAILURES: On failure a structured error is returned instead:
    errorCategory="validation" (empty article_id, limit out of range) is not
    retryable; "business" (article id does not exist) is not retryable;
    "transient" (search backend unreachable/erroring) is retryable. Stack traces
    are never returned.
    """
    return find_similar_impl(
        article_id,
        service=get_similarity_service(),
        include_cve=include_cve,
        include_chunk_seed=include_chunk_seed,
        limit=limit,
    )


@mcp.tool()
def get_cluster(cluster_id: str) -> dict[str, Any]:
    """Fetch a persisted duplicate cluster and its supporting edges by id.

    WHAT IT DOES: Loads a materialized duplicate cluster and returns its full
    detail — member article ids, per-member memberships (supporting edge ids,
    reasons, shared metadata), the representative article, the thresholds it was
    built with, its current review state, and the supporting duplicate edges
    (each with pair scores and evidence). Same payload as
    ``GET /kb/clusters/{cluster_id}``.

    WHEN TO USE: To inspect a specific cluster's evidence and membership when
    reviewing it, after discovering its id via `list_review_queue` or the UI.

    WHEN NOT TO USE: To search for similar articles from scratch (use
    `find_similar`) or to list many clusters (use `list_review_queue`). This tool
    is read-only and does NOT change the cluster's review state.

    INPUTS:
      - cluster_id (str, required): the persisted cluster id (e.g. "family-...").
        Must be a non-empty string.

    OUTPUT: {clusterId, articleIds, edgeIds, memberCount, reviewState,
    representativeArticleId, representativeTitle, memberships: [...], thresholds:
    {...}, materializedAt, edges: [{edgeId, leftArticleId, rightArticleId, label,
    totalScore, pairScores, evidence, ...}]}.

    EDGE CASES & FAILURES: On failure a structured error is returned:
    "validation" (empty cluster_id, not retryable), "business" (no cluster with
    that id, not retryable), or "transient" (backend unreachable/erroring,
    retryable). Stack traces are never returned.
    """
    return get_cluster_impl(cluster_id, service=get_cluster_service())


@mcp.tool()
def list_review_queue(state: str, size: int = 20, page: int = 1) -> dict[str, Any]:
    """List persisted duplicate clusters in a given review state (the review queue).

    WHAT IT DOES: Returns a paginated list of cluster summaries whose review state
    matches `state`, ordered by member count then cluster id — the backing query
    for the Review Queue UI. Same payload as
    ``GET /kb/clusters?reviewState={state}``.

    WHEN TO USE: To page through the editorial review queue for a given state
    (e.g. everything still "pending_review", or everything "split_required"), then
    open individual clusters with `get_cluster`.

    WHEN NOT TO USE: To fetch one cluster's full evidence (use `get_cluster`) or to
    find similar articles for an article (use `find_similar`). This tool is
    read-only and does NOT change any review state — it only lists.

    INPUTS:
      - state (str, required): one of "pending_review", "approved_family",
        "rejected_family", "split_required".
      - size (int, default 20, 1..100): page size.
      - page (int, default 1, 1..10000): 1-based page number; clamped to the last
        page when it exceeds the available pages.

    OUTPUT: {count, page, pageSize, totalPages, items: [{clusterId, articleIds,
    memberCount, reviewState, representativeArticleId, representativeTitle}]}. An
    empty queue is a normal result (count=0, items=[]), not an error.

    EDGE CASES & FAILURES: On failure a structured error is returned:
    "validation" (unknown state, size/page out of range — not retryable) or
    "transient" (backend unreachable/erroring — retryable). Stack traces are
    never returned.
    """
    return list_review_queue_impl(
        state,
        service=get_cluster_service(),
        size=size,
        page=page,
    )


def main() -> None:
    """Run the FastMCP server on the configured transport."""
    if _mcp_transport() == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
