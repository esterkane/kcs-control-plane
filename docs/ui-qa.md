# UI QA And Known Issues

## Goal

This checklist is for verifying the local UI after backend, search, or clustering changes.

Use it before pushing to a shared remote.

## Core Smoke Checks

### Admin

- Open `Admin`.
- Confirm `Content and dedupe backfill completeness` loads.
- Confirm the article/chunk counts render.
- Confirm the latest full refresh job and live logs can load.

### Cluster Explorer

- Open `Cluster Explorer`.
- Confirm real cluster records load from the backend.
- Confirm the displayed total count matches the backend cluster API count.
- Open one cluster detail from the list.

### Review Queue

- Open `Review Queue`.
- Confirm persisted clusters render.
- Change the filter between:
  - `pending review`
  - `approved family`
  - `rejected family`
  - `split required`

### Cluster Detail

- Open a live cluster.
- Confirm member articles render.
- Confirm strongest edges render.
- Confirm article links open using:
  - `https://support.elastic.dev/knowledge/view/<article-id>`
- Change the review decision and confirm the visible review state updates immediately.

### Lookup

- Search by article ID.
- Search by a plain keyword like `systemd`.
- Confirm live candidate results render.
- Confirm empty evidence areas show explanatory fallback text instead of blank panels.
- Confirm a result that belongs to a persisted cluster shows:
  - cluster membership
  - `Open cluster`
- Confirm `Open article` uses the support preview URL format.

## Known UI Caveats

### Mixed live + legacy compare flows

The main cluster review path is live, but the older side-by-side compare workflow still exists as fallback code for parts of the original demo flow.

Impact:

- not every compare interaction comes from the same persisted backend model
- cluster detail is the source of truth for live cluster review

### Cluster list size is bounded

The cluster list UI currently loads a bounded number of clusters from the API rather than a full paginated explorer.

Impact:

- large corpora may have more clusters in Elasticsearch than are visible in one UI load

### Ad hoc lookup latency

Free-text lookup generates query embeddings and temporary query chunks on demand.

Impact:

- keyword and semantic search quality are much better now
- first response time can be slower than article-ID lookup

## Bugs To Watch For

- cluster list loads but count is zero while Elasticsearch shows non-zero cluster docs
  - usually indicates a cluster API failure
- lookup returns results with no reasons/chunks/metadata and a very low score
  - may indicate lexical-only fallback is dominating the query
- review decision appears to save but the visible state does not change
  - usually indicates a backend PATCH issue or stale frontend state
- cluster explorer shows old mock data instead of persisted cluster data
  - indicates the live API path regressed

## Recommended Manual Test Set

Run these checks after major duplicate-pipeline or UI changes:

1. Run a full refresh.
2. Verify the cluster count in Elasticsearch is non-zero.
3. Open Cluster Explorer and confirm live cluster titles appear.
4. Open one cluster and change its review state.
5. Search for:
   - a known article ID
   - a keyword query
6. Confirm search results can jump into cluster detail.
7. Reload the page and confirm cluster review-state still reflects the saved backend value.
