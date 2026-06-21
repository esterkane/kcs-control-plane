# kcs-control-plane — Claude Code Instructions

Local control plane for ingesting Elastic KB articles, computing duplicate signals,
materializing duplicate edges/clusters, and reviewing those clusters in a browser UI.
Runs entirely locally via Docker Compose. It is a duplicate-detection + cluster-review
system, **not** a KB-authoring or KB-publishing system (no canonical-article generation,
no merge authoring, no write-back to the source KB).

## Run / test commands

Prereqs: Python `>=3.12,<3.13` (backend venv at `backend/.venv`), Node (frontend), Docker.

```bash
# Full local stack (frontend 5173, backend 8000, embeddings 7997, ES 9200, Kibana 5601)
make up            # docker compose up --build
make down          # docker compose down --remove-orphans

# Backend setup (one-time)
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Frontend setup (one-time)
cd frontend && npm install

# Tests
make backend-test   # cd backend && .venv/bin/pytest
make frontend-test  # cd frontend && npm run test -- --run   (vitest run)

# Lint / type-checks (this repo's actual gate — NOT ruff/mypy)
make lint           # backend: python -m compileall app tests ; frontend: tsc --noEmit
docker compose config   # validate compose file

# Frontend extras
cd frontend && npm run typecheck   # tsc --noEmit
cd frontend && npm run build       # tsc -b && vite build

# Read-only MCP server (find_similar, get_cluster, list_review_queue)
cd backend && .venv/bin/python -m app.mcp.server          # stdio (default)
cd backend && MCP_TRANSPORT=http MCP_HTTP_PORT=8900 .venv/bin/python -m app.mcp.server
```

CI quality gate: the only GitHub Actions workflow is `.github/workflows/secret-scan.yml`
(gitleaks on every push/PR). There is **no** CI job running pytest, vitest, ruff, or mypy —
those run locally via `make`. Local pre-commit hooks (`.pre-commit-config.yaml`): gitleaks,
trailing-whitespace, end-of-file-fixer, check-yaml. Install with `make precommit-install`.

Note: `ruff` and `mypy` are **not configured** in this repo despite any generic mention
elsewhere. Backend "lint" is `compileall`; backend deps are minimal (fastapi, httpx,
uvicorn, pytest). Do not invent ruff/mypy steps.

## Architecture in 5 lines

1. FastAPI backend (`backend/app`) ingests/normalizes remote KB articles into local Elasticsearch index `kcs-kb-articles-v1`.
2. Pipeline computes article + chunk duplicate embeddings (`kcs-kb-article-chunks-v1`), then materializes duplicate edges (`kcs-kb-duplicate-edges-v1`) and clusters (`kcs-kb-duplicate-clusters-v1`).
3. Full-refresh pipeline is orchestrated by in-process admin jobs (`admin_jobs.py`) and is **resumable** — ingestion/embeddings/chunks are reused when unchanged; edges and clusters are checkpoint-written incrementally.
4. React + Vite + TS frontend (`frontend/src`) reviews persisted clusters: Lookup, Review Queue, Cluster Explorer, Cluster Detail, Admin.
5. Optional remote-analysis sync publishes/pulls the four datasets as shared aliases (`kb-analysis-*`) with a publish lease and stale-local guard; the source KB index stays read-only.
6. A **read-only** MCP server (`backend/app/mcp`) exposes the duplicate/review core as agent tools (`find_similar`, `get_cluster`, `list_review_queue`) — thin adapters over the existing similarity/cluster services returning the same shapes as the HTTP routes.

## Invariants I must never break

1. **Pipeline determinism / resumability.** The duplicate-analysis pipeline (ingest → article embeddings → chunks → edge/cluster materialization) must stay resumable and idempotent: unchanged articles/chunks keep their enrichment, embeddings are only recomputed when comparison content changes (`compare_text_hash`), and edges/clusters are checkpoint-written so an interrupted run resumes from persisted state rather than rescanning from zero. See `backend/tests/test_backfill_idempotency.py` and `test_cluster_materialization.py`.
2. **Quality gates pass.** `make backend-test`, `make frontend-test`, and `make lint` must pass, and gitleaks (secret-scan CI + pre-commit) must be clean.
3. **Provenance / evidence on every result.** Similarity results, duplicate edges, and clusters must carry their supporting evidence — per-signal scores, reasons, chunk evidence, supporting edge IDs, representative article. Do not return clusters/edges without their evidence and reasons. (This is the repo's analogue of "provenance on every chunk".) See `test_similarity_evidence.py`.
4. **No secrets in git.** API keys/tokens go in `.env` (gitignored); `.env.example` uses `<set-me>` placeholders. Secrets reach the backend via Docker Compose `environment:` from the host `.env`, never hardcoded. Never commit `SOURCE_ES_API_KEY`, `JINA_API_KEY`, `GEMINI_API_KEY`, `DEEPSEARCH_API_KEY`.

Repo-specific invariants:
- **Source KB index is read-only.** The pipeline writes only local `kcs-kb-*` indices and remote `kb-analysis-*` aliases. Review-state changes (`pending_review`, `approved_family`, `rejected_family`, `split_required`) persist editorial state only — they must not create/merge KB articles or write back to the source cluster.
- **Remote publish safety.** Publishing must stage versioned indices, validate document counts, take the publish lease, block stale local snapshots, and only then atomically switch aliases; clean up staged indices on failure. Source and analysis roles must never share index/alias names.
- **Pydantic response models, not raw dicts.** API responses use the typed models in `backend/app/config.py` (camelCase aliases via `populate_by_name`).
- **MCP tools are thin + read-only.** Tools in `backend/app/mcp` must stay thin adapters over the existing services (no similarity/cluster business logic in the MCP layer) and return the same shapes as the HTTP routes. They must use the structured error contract (`{isError, errorCategory, isRetryable, message, details}`, categories `validation|transient|business|permission`) and never leak stack traces or raw ES errors. No mutation tool (review-state change, ingestion, admin, publish) may be exposed without an `MCP_ALLOW_MUTATIONS` flag (default false); none exists today.

## Definition of done

- `make backend-test` passes (pytest); add a test under `backend/tests/` for any new backend module/behavior.
- `make frontend-test` passes (vitest) for touched frontend code.
- `make lint` passes (backend `compileall`, frontend `tsc --noEmit`); `docker compose config` valid.
- gitleaks clean (pre-commit + secret-scan CI); no new secrets, only `<set-me>` placeholders in `.env.example`.
- Provenance/evidence intact: any new similarity/edge/cluster output still carries scores, reasons, and supporting evidence.
- Pipeline resumability preserved; no write-back to the read-only source KB index.
- README/`docs/` (`architecture.md`, `status.md`, `ui-qa.md`, `tech-stack.md`) updated if behavior, scope, or commands changed.
- Type checks: mypy is N/A (not configured); frontend TypeScript `tsc --noEmit` must pass.
- MCP tools stay thin + read-only: any new MCP tool is a thin adapter over an existing service, returns the same shape as its HTTP analogue, uses the structured error contract, has mock-backed unit tests under `backend/tests/`, and exposes no mutation without the `MCP_ALLOW_MUTATIONS` gate.

## External services & config

- **Elasticsearch 9.x** (local, single-node, security disabled) — local working indices; **Kibana** at 5601.
- **Remote source Elasticsearch** (`SOURCE_ES_URL` / `SOURCE_ES_API_KEY` / `SOURCE_ES_INDEX`) — read-only KB source.
- **Remote analysis Elasticsearch** (`REMOTE_ANALYSIS_ES_*`) — shared published `kb-analysis-*` aliases; if URL/key empty, reuses the source connection.
- **Local embeddings service** (`infra/local-embeddings`, port 7997) — `jinaai/jina-embeddings-v3-hf` (CC BY-NC 4.0; first start downloads weights). Provider switches: `DUPLICATE_EMBEDDING_PROVIDER=local|jina`, `EMBEDDINGS_PROVIDER`, `RERANKER_PROVIDER` (default `stub`).
- **Jina API** (optional) — `JINA_API_KEY` for embeddings/reranker when provider=`jina`.
- **Gemini** (optional) — `LLM_EXPLANATION_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL` for explanations.
- **DeepSearch** (optional) — `DEEPSEARCH_ENABLED`, `DEEPSEARCH_API_KEY`.

Config loads from host `.env` via `python-dotenv` (`backend/app/config.py`); `.env.example`
is the documented template. Inspect effective config at `GET /config/effective` (gated by
`ENABLE_DEBUG_CONFIG_ENDPOINT`); admin routes gated by `ENABLE_ADMIN_ROUTES`. Backend defaults
to no auto-reload (`BACKEND_RELOAD=false`) so long admin jobs aren't interrupted.

## Caveats

- Admin pipeline jobs are **in-process**; a backend restart can still interrupt an in-flight job (mitigated by `BACKEND_RELOAD=false`, checkpointing).
- Some older mock/demo side-by-side compare flows remain in the frontend as fallback; the main cluster-review path is live and API-backed.
- Not implemented (deliberate): canonical-article generation, article merge authoring, source write-back, reviewer notes/audit trail, user/permission model, bulk review actions.
