# Tech Stack And Configuration Reference

## Goal

This document explains:

- the technology choices in `kcs-control-plane`
- the key configuration surfaces
- why the current defaults look the way they do

It is meant to complement:

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/status.md](status.md)

## Stack Overview

### Backend

Technology:

- Python 3.12
- FastAPI
- Pydantic
- `httpx`
- pytest

Why:

- FastAPI gives a simple API surface for the local UI and admin workflows.
- Pydantic keeps request/response and document-shape handling explicit.
- Python is a good fit for text normalization, similarity orchestration, and Elasticsearch-heavy data workflows.
- The current backend is mostly I/O and pipeline orchestration, not a latency-critical microservice.

### Frontend

Technology:

- React
- TypeScript
- Vite
- Vitest

Why:

- React is enough for a review-heavy multi-page local application.
- TypeScript helps keep the growing API-backed UI aligned with backend response models.
- Vite keeps local iteration fast.
- Vitest fits the Vite-based frontend well and keeps test setup simple.

### Data Store

Technology:

- Elasticsearch

Why:

- the source data already lives in Elasticsearch
- dense-vector storage is required for duplicate-comparison embeddings
- hybrid retrieval, aggregations, and document-level inspection are all natural here
- the local duplicate-analysis pipeline is easier to reason about when the review artifacts live in the same search-oriented store

### Local Embeddings

Technology:

- local containerized embedding service using `jinaai/jina-embeddings-v3-hf`

Why:

- keeps local development self-contained
- avoids API dependency for every run
- useful for full local rebuilds and offline-ish iteration

Tradeoff:

- slower startup due to model download
- heavier local resource use
- model license must be reviewed for production/commercial use

### Optional Hosted Embeddings

Technology:

- Jina embedding API

Why:

- gives an optional hosted path for new/changed article calculations
- avoids requiring every environment to host the embedding model
- helpful when the local model runtime is too heavy or too slow

Tradeoff:

- adds external dependency and network latency
- cost and API key management become part of operations

## Main Configuration Groups

### Local App Runtime

Important variables:

- `APP_ENV`
- `BACKEND_RELOAD`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `ELASTICSEARCH_LOCAL_URL`

Why:

- these keep the local control plane self-contained and easy to run in Docker Compose

Default:

- `BACKEND_RELOAD=false`

Why that default matters:

- long-running background jobs such as full refresh and remote publish currently run in-process inside the backend container
- `uvicorn --reload` restarts the process when watched files change
- that restart interrupts in-flight jobs before they can finish remote alias promotion or record a terminal status

Tradeoff:

- `BACKEND_RELOAD=true` is still available for active backend development
- but it should be avoided while running admin workflows that copy or publish large datasets

### Remote Source KB

Important variables:

- `SOURCE_ES_URL`
- `SOURCE_ES_API_KEY`
- `SOURCE_ES_INDEX`

Role:

- read-only source of KB content

Important rule:

- this source index must not be treated as a writable duplicate-analysis target

Why:

- the source KB is the content system of record
- duplicate-review artifacts are not source content
- writing analysis data into the source index would blur ownership and create operational risk

### Remote Published Analysis

Important variables:

- `REMOTE_ANALYSIS_ES_URL`
- `REMOTE_ANALYSIS_ES_API_KEY`
- `REMOTE_ANALYSIS_NORMALIZED_ALIAS`
- `REMOTE_ANALYSIS_CHUNK_ALIAS`
- `REMOTE_ANALYSIS_DUPLICATE_EDGE_ALIAS`
- `REMOTE_ANALYSIS_DUPLICATE_CLUSTER_ALIAS`
- `REMOTE_ANALYSIS_METADATA_INDEX`

Role:

- shared published duplicate-analysis snapshot for multiple users

Fallback behavior:

- if `REMOTE_ANALYSIS_ES_URL` is not set, the app falls back to `SOURCE_ES_URL`
- if `REMOTE_ANALYSIS_ES_API_KEY` is not set, the app falls back to `SOURCE_ES_API_KEY`

This is useful when:

- the source KB and published analysis live in the same physical remote Elasticsearch cluster

It does **not** mean analysis writes go into the source KB index. They still go only to the separate remote analysis aliases.

Why separate aliases exist:

- so users can share embeddings, edges, and clusters
- so a new local environment can pull the latest published analysis instead of rebuilding from zero
- so local work can publish via staged indices plus alias promotion

Why aliases instead of fixed indices:

- alias promotion is safer than writing directly into the live shared target
- it avoids exposing partially built results
- it supports versioned remote staging indices per publish run

Failure behavior:

- publish writes into versioned staged remote indices first
- only after copy and validation succeed are the stable aliases promoted
- if publish fails during staging, the service now deletes the staged indices it created during that failed run

Current limitation:

- if the backend process is terminated externally, in-memory job state is still lost
- the default non-reload backend mode reduces that risk for normal local use

### Local Sync Metadata

Important variable:

- `LOCAL_ANALYSIS_METADATA_INDEX`

Role:

- records which published remote analysis run the local workspace has pulled or published

Why:

- lets the Admin page warn when the local workspace is behind the latest remote published snapshot
- better than comparing only document counts

### Embedding Provider Selection

Important variables:

- `DUPLICATE_EMBEDDING_PROVIDER`
- `DUPLICATE_EMBEDDING_TASK`
- `LOCAL_EMBEDDING_URL`
- `LOCAL_EMBEDDING_MODEL`
- `LOCAL_EMBEDDING_FALLBACK_URLS`
- `JINA_EMBEDDING_URL`
- `JINA_API_KEY`
- `JINA_EMBEDDING_MODEL`
- `DUPLICATE_EMBEDDING_DIMS`

Supported modes:

- `local`
- `jina`

Why both are kept:

- local mode is best for self-contained rebuilds
- Jina mode is useful for lighter clients or centrally managed API-based computation
- both modes should produce the same kind of duplicate-analysis artifacts for downstream review

### Reranking And Explanation Providers

Important variables:

- `RERANKER_PROVIDER`
- `JINA_RERANKER_URL`
- `JINA_RERANKER_MODEL`
- `LLM_EXPLANATION_PROVIDER`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `DEEPSEARCH_ENABLED`

Current practical status:

- duplicate clustering is intentionally kept deterministic/local where possible
- some provider paths exist for future enrichment or explanation work
- not all of these are part of the critical reviewer workflow today

## Why The Current Default Architecture Is Local-First

The current defaults intentionally favor:

- local writable indices
- local step-by-step resumability
- explicit remote publish

instead of:

- direct shared remote writes during the pipeline

Why:

- materialization steps checkpoint often
- users should not see half-built shared clusters
- local iteration and debugging are much safer this way
- shared publication should be deliberate and validated

## Safe Shared Workflow

The intended shared workflow is:

1. pull published remote analysis into local
2. ingest new/changed KB content from the remote source index
3. calculate deltas locally
4. materialize updated edges/clusters locally
5. publish a staged remote snapshot and promote aliases

This keeps:

- source KB read-only
- local work safe
- shared published state stable

The current shared publish path also includes two coordination guards:

- a remote publish lease stored in the remote analysis metadata index
- a stale-snapshot check that blocks publish when the local workspace is behind the latest published remote run
- startup recovery that reconstructs an interrupted remote publish from the active lease after a backend restart

## What Is Still Intentionally Missing

Not yet part of the design:

- source-content write-back
- reviewer assignment/identity model
- staged-index retention policy
- full incremental remote edge/cluster diff publication

Why:

- the current milestone is safe local review plus safe shared snapshot publication
- source-content authoring needs stronger business rules
- multi-user coordination can be added after operational patterns are clearer
