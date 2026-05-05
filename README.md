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
- remote analysis sync workflows:
  - pull published analysis indices into local working indices
  - publish local analysis indices to a remote staged snapshot plus alias promotion
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
- pushing accepted editorial outcomes back to the remote/source KB content index
- reviewer notes, audit trail, and assignment workflow
- pagination/bulk review for the full cluster corpus in the UI
- a full live side-by-side merge workspace for persisted clusters

Why those parts are not implemented yet:

- the current milestone is duplicate detection and review-state persistence
- article authoring and source-content write-back need stronger business rules and source-of-truth ownership
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

The backend now defaults to a non-reloading process so long-running admin jobs are less likely to be interrupted mid-run.
If you explicitly want backend auto-reload while editing code, set:

- `BACKEND_RELOAD=true`

Remote Elasticsearch roles can now be separated:

- `SOURCE_ES_*`
  read-only source KB index
- `REMOTE_ANALYSIS_*`
  shared published duplicate-analysis indices

If `REMOTE_ANALYSIS_ES_URL` and `REMOTE_ANALYSIS_ES_API_KEY` are left empty, the app reuses the source-cluster connection and publishes the analysis aliases into that same remote Elasticsearch cluster.

## Quick Start

1. Copy local config:

```bash
cp .env.example .env
```

The default `.env` is intentionally safer for long-running jobs:

- `BACKEND_RELOAD=false`

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

If you are actively changing backend code and want auto-reload in development:

```bash
BACKEND_RELOAD=true make up
```

5. Open:

- UI: `http://localhost:5173`
- backend health: `http://localhost:8000/health`
- config dump: `http://localhost:8000/config/effective`
- local embeddings health: `http://localhost:7997/health`

6. Optional remote analysis configuration:

- keep `SOURCE_ES_INDEX` pointed at the existing source KB index
- keep `REMOTE_ANALYSIS_*` pointed at a separate analysis namespace
- do not reuse the source index name for the remote analysis aliases
- if the source KB and analysis aliases live in the same remote Elasticsearch cluster, you can leave `REMOTE_ANALYSIS_ES_URL` and `REMOTE_ANALYSIS_ES_API_KEY` empty

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

### 1b. Pull a published shared analysis snapshot

Open `Admin` and use:

- `Pull published remote analysis`

This copies the remote published analysis aliases into the local working indices:

- `kcs-kb-articles-v1`
- `kcs-kb-article-chunks-v1`
- `kcs-kb-duplicate-edges-v1`
- `kcs-kb-duplicate-clusters-v1`

Use this when a new user wants to start from the latest published embeddings, edges, and clusters instead of computing everything from zero.

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

### 4. Publish a completed local analysis snapshot

Open `Admin` and use:

- `Publish local analysis to remote`

This does **not** write into the remote source KB index.

Instead it:

1. copies the local working indices into versioned remote staging indices
2. validates document counts
3. atomically switches the remote analysis aliases

This lets multiple users consume a shared published duplicate-analysis result without exposing half-finished local work.

If publish fails after staging begins, the backend now deletes the staged remote indices it created during that failed run.

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

If remote analysis publishing is configured, those same logical datasets are also published under separate remote aliases such as:

- `kcs-kb-analysis-articles-v1`
- `kcs-kb-analysis-article-chunks-v1`
- `kcs-kb-analysis-duplicate-edges-v1`
- `kcs-kb-analysis-duplicate-clusters-v1`

## Main API Endpoints

Admin and pipeline:

- `POST /admin/workflows/full-refresh`
- `POST /admin/workflows/pull-remote-analysis`
- `POST /admin/workflows/publish-remote-analysis`
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
- [docs/tech-stack.md](/Users/saru/support-projects/support/ai-tools/kcs-control-plane/docs/tech-stack.md)
  detailed stack, configuration, and design-choice reference

## Notes

- The local embedding service uses `jinaai/jina-embeddings-v3-hf`.
- Duplicate embeddings can also be calculated via the Jina API by setting:
  - `DUPLICATE_EMBEDDING_PROVIDER=jina`
  - `JINA_API_KEY`
- First startup can take several minutes because model weights must be downloaded.
- The model is published under `CC BY-NC 4.0`; review the license before production or commercial use.
- The frontend still contains a mock/demo workflow fallback for a few older side-by-side compare screens, but the main cluster-review path is now live and API-backed.
- Admin jobs are still in-process jobs. They are much safer now with `BACKEND_RELOAD=false`, but arbitrary backend restarts can still interrupt an in-flight job.
