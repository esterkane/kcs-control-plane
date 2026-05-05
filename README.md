# kcs-control-plane

Local control plane for ingesting Elastic KB articles, computing duplicate signals, materializing duplicate clusters, and reviewing those clusters in a browser-based UI.

This project is no longer just a bootstrap. It now contains a working local duplicate-detection pipeline, a live review UI for persisted clusters, and a resumable materialization flow that writes progress back into Elasticsearch.

## What This Project Does

`kcs-control-plane` pulls KB articles from a remote Elasticsearch source, normalizes them into a local article index, computes duplicate-oriented embeddings, creates chunk-level evidence, materializes duplicate edges and clusters, and exposes the result through a local UI.

Today it is focused on these jobs:

- building a local duplicate-analysis corpus
- finding likely duplicate or near-duplicate KB articles
- grouping accepted duplicate pairs into persisted clusters
- letting reviewers inspect clusters and persist editorial review state

It is not yet a KB-authoring or KB-publishing system.

## Current State

Implemented today:

- remote KB ingestion into `kcs-kb-articles-v1`
- article-level duplicate embeddings:
  - `duplicate_title_embedding`
  - `duplicate_summary_embedding`
  - `duplicate_body_embedding`
  - `duplicate_comparison_embedding`
- chunk generation and chunk embeddings in `kcs-kb-article-chunks-v1`
- duplicate edge materialization in `kcs-kb-duplicate-edges-v1`
- duplicate cluster materialization in `kcs-kb-duplicate-clusters-v1`
- resumable full refresh pipeline with checkpointed progress
- live UI for:
  - admin pipeline control
  - lookup search
  - cluster explorer
  - review queue
  - persisted cluster detail
- persisted cluster review-state updates:
  - `pending_review`
  - `approved_family`
  - `rejected_family`
  - `split_required`

Not implemented yet:

- creating a new canonical KB article from a cluster
- merging source KB articles into a new draft article
- pushing accepted editorial outcomes back to the remote/source cluster
- reviewer notes, audit trail, and assignment workflow
- pagination/bulk review for the full cluster corpus in the UI
- a full live side-by-side merge workspace for persisted clusters

Why those parts are not implemented yet:

- the current milestone is duplicate detection and review-state persistence
- article authoring and remote write-back need stronger business rules and source-of-truth ownership
- cluster quality and reviewer workflow needed to be stabilized first

For a fuller status breakdown, see [docs/status.md](/Users/saru/support-projects/support/ai-tools/kcs-control-plane/docs/status.md).

## Repository Layout

- `backend/`
  FastAPI backend, ingestion, similarity, clustering, and admin job orchestration.
- `frontend/`
  React + Vite + TypeScript review UI.
- `docs/`
  Architecture, status, and UI QA documentation.
- `infra/`
  Local infrastructure assets, including Elasticsearch notes and the local embedding service.
- `scripts/`
  Helper documentation and future small automation scripts.

## Local Stack

Services started by `docker compose`:

- frontend: `http://localhost:5173`
- backend: `http://localhost:8000`
- local embeddings: `http://localhost:7997`
- Elasticsearch: `http://localhost:9200`
- Kibana: `http://localhost:5601`

## Quick Start

1. Copy local config:

```bash
cp .env.example .env
```

2. Install backend dependencies:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cd ..
```

3. Install frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

4. Start the local stack:

```bash
make up
```

5. Open:

- UI: `http://localhost:5173`
- backend health: `http://localhost:8000/health`
- config dump: `http://localhost:8000/config/effective`
- local embeddings health: `http://localhost:7997/health`

6. Stop the stack:

```bash
make down
```

## How To Use The Product

### 1. Run the full pipeline

Open the `Admin` page and use `Run full pipeline`.

That pipeline performs:

1. ingestion from the remote source index
2. article embedding backfill
3. chunk generation and chunk embedding backfill
4. duplicate edge and cluster materialization

The pipeline is resumable:

- completed ingestion is reused
- unchanged article embeddings are reused
- unchanged chunk work is reused
- duplicate edges are checkpointed and can be resumed
- cluster materialization writes progress incrementally

### 2. Search for related articles

Open the `Lookup` page.

Lookup now supports:

- article ID search
- keyword search
- ad hoc hybrid semantic search

The page can show:

- scored candidate articles
- chunk-level evidence when available
- whether the article already belongs to a persisted duplicate cluster
- a direct jump into that cluster

Article links open in the support preview format:

- `https://support.elastic.dev/knowledge/view/<article-id>`

### 3. Review persisted clusters

Use:

- `Cluster Explorer` for browsing live persisted clusters
- `Review Queue` for filtering by review state
- `Cluster Detail` for article membership, strongest edges, and editorial decisions

The live editorial decisions currently persist review state only:

- `Merge candidate` -> `approved_family`
- `Related only` -> `pending_review`
- `Keep separate` -> `rejected_family`
- `Split family` -> `split_required`

They do not create or publish a new KB article yet.

## Core Indices

The backend currently works with these local indices:

- `kcs-kb-articles-v1`
  normalized article documents
- `kcs-kb-article-chunks-v1`
  chunk documents and chunk embeddings
- `kcs-kb-duplicate-edges-v1`
  accepted duplicate/near-duplicate edges
- `kcs-kb-duplicate-clusters-v1`
  persisted duplicate cluster documents

## Main API Endpoints

Admin and pipeline:

- `POST /admin/workflows/full-refresh`
- `GET /admin/jobs`
- `GET /admin/jobs/{job_id}`
- `GET /admin/jobs/{job_id}/stream`
- `GET /admin/index-status`

Similarity and lookup:

- `GET /kb/articles/{article_id}/similar`
- `POST /kb/similar/search`

Clusters:

- `GET /kb/clusters`
- `GET /kb/clusters/{cluster_id}`
- `GET /kb/articles/{article_id}/cluster`
- `PATCH /kb/clusters/{cluster_id}`
- `POST /kb/clusters/materialize`

## Testing And Checks

Backend:

```bash
make backend-test
```

Frontend:

```bash
make frontend-test
```

Basic lint/type checks:

```bash
make lint
docker compose config
```

## Documentation Map

- [docs/architecture.md](/Users/saru/support-projects/support/ai-tools/kcs-control-plane/docs/architecture.md)
  system architecture and pipeline flow
- [docs/status.md](/Users/saru/support-projects/support/ai-tools/kcs-control-plane/docs/status.md)
  implemented scope, limitations, and next steps
- [docs/ui-qa.md](/Users/saru/support-projects/support/ai-tools/kcs-control-plane/docs/ui-qa.md)
  manual UI verification checklist and known UI caveats

## Notes

- The local embedding service uses `jinaai/jina-embeddings-v3-hf`.
- First startup can take several minutes because model weights must be downloaded.
- The model is published under `CC BY-NC 4.0`; review the license before production or commercial use.
- The frontend still contains a mock/demo workflow fallback for a few older side-by-side compare screens, but the main cluster-review path is now live and API-backed.
