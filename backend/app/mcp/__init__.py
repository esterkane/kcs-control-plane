"""Read-only MCP layer for kcs-control-plane.

Exposes the existing duplicate-detection / cluster-review core as MCP tools.
The tools are thin adapters over the existing services in ``app.similarity`` and
``app.clustering`` — no business logic lives here. All tools are read-only: no
ingestion, admin, publish, or review-state mutation is exposed.
"""
