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
  - block remote publish when the local workspace is stale
  - take a remote publish lease so only one shared publish proceeds at a time
  - recover an interrupted remote publish automatically after backend restart
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

Implemented as a DRAFT-only milestone (behind `AGENTS_ENABLED`, default off):

- drafting a canonical merged article from a cluster's member articles
  (title + merged body + member-id provenance) via the `AuthoringAgent` — persisted to a
  dedicated drafts store (`kcs-kb-agent-drafts-v1`), **never** written back to the source KB

Not implemented yet:

- pushing accepted editorial outcomes back to the remote/source KB content index
- reviewer notes, audit trail, and assignment workflow
- bulk review actions and richer cross-page filtering for the full cluster corpus in the UI
- a full live side-by-side merge workspace for persisted clusters

Why those parts are not implemented yet:

- source-content write-back needs stronger business rules and source-of-truth ownership
- cluster quality and reviewer workflow needed to be stabilized first

## Editorial supervisor (multi-agent)

An optional multi-agent editorial layer **wraps** the deterministic duplicate-cluster
pipeline as tools — it never replaces or re-implements clustering/dedup logic. It is
gated behind the `AGENTS_ENABLED` feature flag (**default off**); when off, no agent
behaviour is active and existing API/UI behaviour is unchanged.

Three agents:

- **ReviewerAgent** — fetches a persisted cluster via the read-only agent tools (which
  reuse the existing `get_cluster` MCP tool / cluster service) and proposes a decision in
  the same four review states the deterministic pipeline uses
  (`approved_family` / `pending_review` / `rejected_family` / `split_required`), with a
  justification that cites the specific edges/scores it used.
- **AuthoringAgent** — for an approved family, drafts a canonical merged article
  (title + merged body + member-id provenance). **DRAFT only**: persisted to
  `kcs-kb-agent-drafts-v1`; it never writes the source KB index.
- **SupervisorAgent** — applies a pure routing function over `(proposal, cluster signals)`:
  - `auto_approve` — high edge-confidence **and** an `approved_family` proposal →
    persist `approved_family` and attach an AuthoringAgent draft.
  - `split` — an `split_required` proposal → persist `split_required`.
  - `reject` — a confident `rejected_family` proposal → persist `rejected_family`.
  - `send_to_human` — the ambiguous middle (`pending_review`, disagreement, low
    confidence) → **do not** change review state; leave it for a human.

  Only review state + the draft are ever persisted; humans stay in the loop on the
  ambiguous middle.

**Swappable provider interface.** Reasoning is behind one `AgentReasoningProvider`
Protocol with two implementations: a default, offline, fully-deterministic
`DeterministicReasoningProvider` (derives the decision from edge confidence/structure —
no API key, no network), and a `LlmReasoningProvider` (Gemini, selected only via
`AGENT_REASONING_PROVIDER=gemini`; never required for tests or the default path).

**Episode logging (learning loop).** Every agent decision is logged as an episode
(`{episode_id, cluster_id, ts, agent, inputs, proposal, routing_decision, draft_id?,
human_outcome, provider, model, prompt_version}`) to `kcs-kb-agent-episodes-v1`.
`human_outcome` is null at write time and is filled later when a human acts.

**Agreement eval.** A held-out, committed labeled fixture
(`backend/app/agents/fixtures/agreement_clusters.json`) lets you measure the deterministic
ReviewerAgent's agreement vs. recorded human decisions — overall accuracy plus a per-class
confusion over the four labels — fully offline:

```bash
cd backend && .venv/bin/python -m app.agents.eval \
    --output-json reports/agreement.json --output-md reports/agreement.md
```

On the committed fixture the deterministic provider scores **0.75 overall (6/8)**
(per-class: approved_family 2/3, pending_review 1/2, rejected_family 1/1,
split_required 2/2).

The live path (running the supervisor against a real Elasticsearch) is integration /
run-locally and is not exercised by the offline test gate.

## How it learns

The editorial layer adds a memory + learning loop on top of the existing episode log —
**no new vector store, no parallel clustering logic**. Two halves:

**(A) Episodic memory — recall as precedent.** Each episode now carries a stable
`inputs_summary` of the cluster it reasoned over and an `embedding` of that summary,
stored **on the episode document** in `kcs-kb-agent-episodes-v1` (a `dense_vector`
field). Before the ReviewerAgent proposes, the SupervisorAgent **recalls** the *k* most
similar past episodes via an Elasticsearch `script_score` cosine over that same index and
passes their outcomes (agent decision + human outcome) into the provider as **precedent**.
The ids + similarities of the recalled episodes are written back onto the new episode
(`recalled_episode_ids`) for auditability. Recall is gated by `MEMORY_ENABLED`
(**default off**, independent of `AGENTS_ENABLED`): when off, no recall query is issued
and behaviour is byte-for-byte reproducible. The deterministic provider accepts precedent
for interface parity but never lets it change its rule-based decision, so the default path
stays reproducible whether memory is on or off. Embeddings use the existing embedding
provider contract; the offline default (`LocalDeterministicEmbedder`) needs no network, so
tests and the default path never call out.

**(B) Procedural learning — recalibrate the duplicate-edge threshold, gated.** From
accumulated human decisions (episodes whose `human_outcome` is set: `approved_family` →
the edges were true duplicates; `rejected_family`/`split_required` → the strong-duplicate
claim was wrong), the learner derives labeled edges and **proposes** a recalibrated
duplicate-edge *strong* threshold (`min_total_score`, the value
`clustering.service._is_strong_near_duplicate` reads). It is **proposed → evaluated on a
held-out labeled split → applied only if it improves**: `recalibrate` returns a proposal
plus a before/after precision/recall report and `should_apply` only when held-out overall
F1 strictly improves and neither precision nor recall regresses. It **never** mutates
`ClusterThresholds`; `apply_recalibration` is a separate explicit step that refuses unless
the gate passed.

Grouping (honest note): edges and articles carry **no genuine "topic" field**. The only
real per-edge grouping dimension is the edge `label` (`exact_duplicate` /
`near_duplicate`), and exact-duplicate edges bypass the score threshold entirely — so the
recalibration reports precision/recall **per `near_duplicate` and overall**, with no
invented topic dimension.

A committed fixture (`backend/app/agents/fixtures/labeled_edges_episodes.json`) makes the
recalibration + its test run fully offline:

```bash
cd backend && .venv/bin/python -m app.agents.learning \
    --output-json reports/recalibration.json --output-md reports/recalibration.md
```

On that fixture the current threshold `0.84` mislabels human-approved near-duplicates
scoring 0.80–0.83; the gate accepts lowering it to `0.80` (held-out recall 0.50 → 1.00,
precision held at 1.00). Recall against a live Elasticsearch is integration / run-locally.

For a fuller status breakdown, see [docs/status.md](docs/status.md).

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

If a published remote snapshot already exists, pull it first before you run a full local rebuild.
The Admin page now shows a first-install warning for that case.

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

- `https://kb.example.com/knowledge/view/<article-id>`

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
3. acquires a remote publish lease and blocks stale local snapshots
4. atomically switches the remote analysis aliases

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

- `kb-analysis-articles`
- `kb-analysis-article-chunks`
- `kb-analysis-duplicate-edges`
- `kb-analysis-duplicate-clusters`

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

- `GET /kb/clusters` (optional `?reviewState=` filter)
- `GET /kb/clusters/{cluster_id}`
- `GET /kb/articles/{article_id}/cluster`
- `PATCH /kb/clusters/{cluster_id}`
- `POST /kb/clusters/materialize`

## Agent Access (MCP)

A **read-only** [MCP](https://modelcontextprotocol.io) server exposes the
duplicate/review core as agent tools — thin adapters over the same services the
HTTP routes use, returning the same payload shapes:

- `find_similar(article_id, ...)` — wraps `GET /kb/articles/{id}/similar`
- `get_cluster(cluster_id)` — wraps `GET /kb/clusters/{id}`
- `list_review_queue(state, ...)` — wraps `GET /kb/clusters?reviewState={state}`

It exposes lookups only — no ingestion, admin, publish, or review-state
mutation. Run it with `cd backend && .venv/bin/python -m app.mcp.server` (stdio
by default; `MCP_TRANSPORT=http` for streamable-HTTP). See
[docs/mcp.md](docs/mcp.md) for the full tool list, error contract, examples, and
client-registration snippet.

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

## Duplicate-Retrieval Evaluation

Duplicate-retrieval quality (Precision@k / MRR@k / nDCG@k) is scored by the
shared, backend-agnostic [`relevance_eval`](https://github.com/esterkane/elastic-ai-search-decision-lab/tree/main/skills/relevance-eval)
skill, installed as an optional `eval` extra (a git dependency). A thin adapter
(`backend/app/eval/skill_adapter.py`) injects the existing similar-article
service into the skill's `search_fn(seed_article_id, strategy) -> [candidate_id]`
contract — the seed article id is the "query", the ranked candidate duplicate ids
are the "documents". No similarity logic lives in the adapter; strategies only
toggle flags the service already accepts:

- `embedding` — default article-level lexical + vector signals (`include_chunk_seed=False`)
- `chunk_seeded` — adds the chunk-seed signal (`include_chunk_seed=True`)

```bash
# Install the skill (optional extra)
pip install -e "backend/.[eval]"

# Run the eval (needs a live Elasticsearch backend — run-locally / integration)
cd backend && .venv/bin/python -m app.eval.run_eval \
    --judgments app/eval/judgments.example.json \
    --thresholds app/eval/thresholds.example.json \
    --output-dir reports
```

The runner writes `reports/duplicate_eval.{json,md}`, prints the Markdown, and
exits non-zero if the thresholds gate (`backend/app/eval/thresholds.example.json`,
keys `"<metric>@<k>"`) fails. Judgments map a seed article id to its known
duplicate ids (`backend/app/eval/judgments.example.json`). The offline unit tests
in `backend/tests/test_eval_skill_integration.py` exercise the adapter and the
skill with fakes, so they need no live Elasticsearch.

## Documentation Map

- [docs/architecture.md](docs/architecture.md)
  system architecture and pipeline flow
- [docs/status.md](docs/status.md)
  implemented scope, limitations, and next steps
- [docs/ui-qa.md](docs/ui-qa.md)
  manual UI verification checklist and known UI caveats
- [docs/tech-stack.md](docs/tech-stack.md)
  detailed stack, configuration, and design-choice reference
- [docs/mcp.md](docs/mcp.md)
  read-only MCP server: tools, error contract, run + client registration

## Notes

- The local embedding service uses `jinaai/jina-embeddings-v3-hf`.
- Duplicate embeddings can also be calculated via the Jina API by setting:
  - `DUPLICATE_EMBEDDING_PROVIDER=jina`
  - `JINA_API_KEY`
- First startup can take several minutes because model weights must be downloaded.
- The model is published under `CC BY-NC 4.0`; review the license before production or commercial use.
- The frontend still contains a mock/demo workflow fallback for a few older side-by-side compare screens, but the main cluster-review path is now live and API-backed.
- Admin jobs are still in-process jobs. They are much safer now with `BACKEND_RELOAD=false`, but arbitrary backend restarts can still interrupt an in-flight job.
