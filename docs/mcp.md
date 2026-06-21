# Agent Access — MCP server

`kcs-control-plane` ships a **read-only** [Model Context Protocol](https://modelcontextprotocol.io)
server that exposes the duplicate-detection / cluster-review core as agent tools.
Any MCP client (Claude Code, Cursor, a custom agent) can call these tools to
inspect similarity results and the review queue.

The server is a **thin adapter**: every tool is a small wrapper over the same
service methods the FastAPI routes use (`SimilarArticleService.search`,
`DuplicateClusterService.get_cluster`, `DuplicateClusterService.list_clusters`).
No similarity/cluster business logic lives in the MCP layer, and every tool
returns the **same payload shape** as the corresponding HTTP endpoint.

## Read-only by design

The server exposes **lookup tools only**. It deliberately does **not** expose:

- ingestion / normalization,
- admin pipeline control or remote publish/pull,
- any review-state mutation (`PATCH /kb/clusters/{id}`).

A mutation tool would only ever be registered behind the `MCP_ALLOW_MUTATIONS`
env flag (default `false`); no such tool exists today.

## Tools

| Tool | Signature | Wraps | HTTP analogue |
|---|---|---|---|
| `find_similar` | `find_similar(article_id: str, include_cve=False, include_chunk_seed=True, limit=10) -> dict` | `SimilarArticleService.search` | `GET /kb/articles/{article_id}/similar` |
| `get_cluster` | `get_cluster(cluster_id: str) -> dict` | `DuplicateClusterService.get_cluster` | `GET /kb/clusters/{cluster_id}` |
| `list_review_queue` | `list_review_queue(state: str, size=20, page=1) -> dict` | `DuplicateClusterService.list_clusters(review_state=...)` | `GET /kb/clusters?reviewState={state}` |

`state` must be one of `pending_review`, `approved_family`, `rejected_family`,
`split_required`.

## Error contract

On failure a tool returns a structured payload instead of raising. Stack traces
and raw Elasticsearch errors are never returned.

```json
{
  "isError": true,
  "errorCategory": "validation | transient | permission | business",
  "isRetryable": true,
  "message": "<safe, human-readable summary>",
  "details": { }
}
```

| Category | When | Retryable |
|---|---|---|
| `validation` | empty/blank id, unknown review state, out-of-range `limit`/`size`/`page` | no |
| `business` | valid request that cannot be satisfied — unknown article id, unknown cluster id | no |
| `transient` | Elasticsearch / httpx transport error, backend unreachable | yes |
| `permission` | reserved (not currently raised by these read-only tools) | no |

An **empty review queue** (`count: 0`, `items: []`) is a normal result, **not** an error.

## Running the server

```bash
cd backend
# stdio transport (default — for Claude Code / Cursor):
.venv/bin/python -m app.mcp.server

# streamable-HTTP transport:
MCP_TRANSPORT=http MCP_HTTP_HOST=127.0.0.1 MCP_HTTP_PORT=8900 .venv/bin/python -m app.mcp.server
```

Configuration (env vars):

| Var | Default | Meaning |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` (streamable-HTTP) |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP bind host (http transport only) |
| `MCP_HTTP_PORT` | `8900` | HTTP bind port (http transport only) |
| `MCP_ALLOW_MUTATIONS` | `false` | Reserved gate for any future mutation tool; no effect today |

The server reuses the backend's existing service wiring, so the same
Elasticsearch / embedding / reranker env vars from `.env` apply (see `.env.example`).

## Example calls and outputs

### `find_similar`

Request:

```json
{ "article_id": "kb-12345", "limit": 5 }
```

Response (same shape as `GET /kb/articles/{id}/similar`):

```json
{
  "queryArticleId": "kb-12345",
  "candidateCount": 1,
  "candidates": [
    {
      "articleId": "kb-67890",
      "label": "near_duplicate",
      "title": "Resolving VPN login loop",
      "summary": "...",
      "pairScores": {
        "rrfScore": 0.1, "articleEmbeddingSimilarity": 0.82,
        "bestChunkSimilarity": 0.61, "titleSimilarity": 0.7,
        "summarySimilarity": 0.55, "metadataAgreement": 0.5,
        "rerankScore": 0.0, "totalScore": 0.79
      },
      "evidence": {
        "sharedMetadata": { "products": ["Cloud"] },
        "mostSimilarChunks": [],
        "reasons": ["high_article_embedding_similarity", "shared_metadata"]
      }
    }
  ]
}
```

Unknown id → business error:

```json
{ "isError": true, "errorCategory": "business", "isRetryable": false,
  "message": "Article not found: ghost", "details": { "articleId": "ghost" } }
```

### `get_cluster`

Request: `{ "cluster_id": "family-abc123" }` → same shape as
`GET /kb/clusters/{id}` (`clusterId`, `articleIds`, `memberships`, `thresholds`,
`reviewState`, and `edges[]` with `pairScores` + `evidence`).

### `list_review_queue`

Request: `{ "state": "pending_review", "size": 20, "page": 1 }` → same shape as
`GET /kb/clusters?reviewState=pending_review`:

```json
{
  "count": 12, "page": 1, "pageSize": 20, "totalPages": 1,
  "items": [
    { "clusterId": "family-abc123", "articleIds": ["kb-1", "kb-2"],
      "memberCount": 2, "reviewState": "pending_review",
      "representativeArticleId": "kb-1", "representativeTitle": "..." }
  ]
}
```

## Client registration (Claude Code / Cursor)

Add to your MCP client config (e.g. `~/.cursor/mcp.json` or a Claude Code
`mcpServers` block). Adjust the path to your checkout:

```json
{
  "mcpServers": {
    "kcs-control-plane": {
      "command": "/abs/path/to/kcs-control-plane/backend/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/abs/path/to/kcs-control-plane/backend",
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

The tools then appear as `find_similar`, `get_cluster`, and `list_review_queue`.
```
