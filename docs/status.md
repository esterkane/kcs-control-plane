# Project Status

## Summary

The project is currently in a strong local-review state:

- ingestion works
- duplicate embeddings work
- chunking and chunk embeddings work
- duplicate edge materialization works
- duplicate cluster materialization works
- cluster review-state persistence works
- the main review UI is live against backend APIs
- remote analysis pull/publish workflows exist for sharing published analysis snapshots

The system is not yet an authoring or publishing tool.

## Implemented So Far

### Data pipeline

- remote source ingestion into the local article index
- article-level duplicate vectors for:
  - title
  - summary
  - body
  - fused comparison text
- chunk generation for:
  - title
  - summary
  - symptoms
  - body sections
- chunk embeddings

### Duplicate analysis

- accepted duplicate edge persistence
- cluster persistence
- checkpointed/resumable step 4 materialization
- large-component handling improvements
- preserved review-state across reruns

### UI

- live admin pipeline controls
- live admin controls for:
  - full refresh
  - pull published remote analysis
  - publish local analysis to remote
- live remote analysis status panel with:
  - alias visibility
  - latest published run visibility
  - local sync visibility
  - stale local snapshot warning
- live index completeness view
- live cluster list
- live cluster detail
- live cluster review-state updates
- live lookup search with:
  - article ID search
  - keyword search
  - ad hoc hybrid semantic search
  - article-to-cluster membership lookup

## Not Implemented Yet

### Authoring workflow

Not implemented:

- generate a new canonical KB draft from an approved cluster
- merge source articles into one editable article
- push the result back into the remote/source KB content index

Why:

- this needs stronger business rules
- it changes source-of-truth ownership
- the current milestone is review and triage, not publishing

### Multi-user coordination

Not implemented:

- publish lease / lock for the remote analysis cluster
- cleanup/retention policy for old staged remote indices
- remote diff-aware incremental edge/cluster publish

Why:

- phase 1 focuses on safe snapshot pull/publish
- alias promotion is enough to share stable results now
- conflict management can follow once multi-user operational patterns are clearer

### Full reviewer workflow

Not implemented:

- reviewer notes
- reviewer identity / attribution
- audit log
- assignment and claiming
- bulk actions

Why:

- the cluster-review model itself needed to be made stable first

### Complete live replacement of legacy mock flows

Still mixed:

- the main cluster-review path is live
- parts of the older side-by-side compare demo still remain in the frontend as fallback code

Why:

- the project evolved from a workflow prototype into a live local review tool
- replacing every mock-oriented view was not required to ship the live cluster workflow

## Known Product Limitations

### Cluster browsing scale

- cluster list endpoints currently return a bounded page size
- the UI currently focuses on the largest visible subset instead of full pagination/search over all clusters

### Lookup query cost

- free-text lookup now creates ad hoc embeddings and temporary chunk embeddings on request
- this improves hybrid search quality
- it can be slower than article-ID search because the query has to be embedded at request time

### Shared remote publication is snapshot-based

- remote publication currently promotes full staged analysis snapshots
- it is not yet a fine-grained multi-writer incremental publish model

Impact:

- safer shared visibility
- simpler reasoning
- more remote index churn than a future incremental model

### Review-state semantics

- persisted review states affect the duplicate cluster only
- they do not create or update any KB article yet

## What “Done” Means Right Now

At the current milestone, “done” means:

- a full refresh can ingest, enrich, cluster, and persist results locally
- reviewers can inspect live clusters
- reviewers can persist a cluster outcome
- later refreshes preserve prior review-state when the same cluster survives materialization

It does not yet mean:

- reviewers can publish a canonical article
- the system will automatically merge articles
- the source KB content changes as a result of review decisions

## Recommended Next Steps

1. Add reviewer notes and audit trail on cluster decisions.
2. Add cluster pagination/filtering/search beyond the first result page.
3. Add a live side-by-side evidence view for persisted clusters.
4. Add approved-cluster draft generation for canonical article authoring.
5. Add remote publish locking and staged-index retention for the shared analysis cluster.
6. Add explicit source-content write-back workflows once authoring rules are agreed.
