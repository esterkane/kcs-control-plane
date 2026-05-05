import { Badge } from "../components/Badge";
import type {
  AdminIndexStatus,
  AdminPipelineRun,
  JobKind,
  JobLogRecord,
  RemoteAnalysisStatus,
} from "../types";

type AdminPageProps = {
  apiBaseUrl: string;
  activeRun: AdminPipelineRun | null;
  indexStatus: AdminIndexStatus | null;
  indexStatusError: string | null;
  remoteAnalysisStatus: RemoteAnalysisStatus | null;
  remoteAnalysisStatusError: string | null;
  isStartingPipeline: boolean;
  jobLogs: JobLogRecord[];
  pipelineError: string | null;
  onRunFullPipeline: () => void;
  onRunJob: (jobKind: JobKind) => void;
  onPullRemoteAnalysis: () => void;
  onPublishRemoteAnalysis: () => void;
};

const adminActions: Array<{
  kind: JobKind;
  label: string;
  description: string;
}> = [
  {
    kind: "ingest",
    label: "Run ingestion",
    description: "Refresh normalized KB articles from the remote source index.",
  },
  {
    kind: "embedding_backfill",
    label: "Backfill embeddings",
    description: "Update compare-text and chunk embeddings for duplicate review.",
  },
  {
    kind: "cluster_materialization",
    label: "Materialize clusters",
    description: "Build duplicate edges and deterministic families for reviewer intake.",
  },
];

export function AdminPage({
  apiBaseUrl,
  activeRun,
  indexStatus,
  indexStatusError,
  remoteAnalysisStatus,
  remoteAnalysisStatusError,
  isStartingPipeline,
  jobLogs,
  pipelineError,
  onRunFullPipeline,
  onRunJob,
  onPullRemoteAnalysis,
  onPublishRemoteAnalysis,
}: AdminPageProps) {
  const shouldWarnFirstPull = Boolean(
    remoteAnalysisStatus?.enabled
      && remoteAnalysisStatus.latestPublishedRun !== null
      && remoteAnalysisStatus.localSync === null,
  );
  const publishBlocked = Boolean(remoteAnalysisStatus?.publishBlockedReason);
  const compareTextCoverage = indexStatus?.articleIndex.coverage.find(
    (item) => item.fieldName === "compare_text",
  );
  const embeddingCoverage = indexStatus?.articleIndex.coverage.find(
    (item) => item.fieldName === "duplicate_comparison_embedding",
  );
  const titleEmbeddingCoverage = indexStatus?.articleIndex.coverage.find(
    (item) => item.fieldName === "duplicate_title_embedding",
  );
  const summaryEmbeddingCoverage = indexStatus?.articleIndex.coverage.find(
    (item) => item.fieldName === "duplicate_summary_embedding",
  );
  const bodyEmbeddingCoverage = indexStatus?.articleIndex.coverage.find(
    (item) => item.fieldName === "duplicate_body_embedding",
  );

  return (
    <div className="page-stack">
      <header className="hero-panel">
        <div className="hero-copy">
          <p className="page-eyebrow">Admin</p>
          <h2>Run operational jobs without hijacking the workflow</h2>
          <p className="page-copy">
            Operational controls stay available here, while the primary navigation
            remains focused on editorial review.
          </p>
        </div>
      </header>

      <section className="panel-card" aria-label="Admin actions">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Jobs</p>
            <h3>Operational controls</h3>
          </div>
          <Badge tone="neutral">{apiBaseUrl}</Badge>
        </div>
        {shouldWarnFirstPull ? (
          <div className="full-pipeline-card" role="alert" aria-live="polite">
            <div>
              <h4>Pull shared data first</h4>
              <p className="error-copy">
                A published remote analysis snapshot already exists, but this local workspace has not
                pulled it yet. On first install, use <strong>Pull published remote analysis</strong> before
                running the full pipeline. Do not start a full local rebuild unless you intentionally want
                to recalculate from scratch.
              </p>
            </div>
            <div className="panel-actions">
              <Badge tone="accent">First-time setup warning</Badge>
            </div>
          </div>
        ) : null}
        <div className="full-pipeline-card">
          <div>
            <h4>Run full KB pipeline</h4>
            <p className="supporting-copy">
              Starts ingestion, article embedding backfill, chunk embedding backfill,
              and duplicate-family materialization inside the backend container.
            </p>
          </div>
          <div className="panel-actions">
            <button
              type="button"
              className="primary-button"
              onClick={onRunFullPipeline}
              disabled={isStartingPipeline || activeRun?.status === "running" || activeRun?.status === "queued"}
            >
              {isStartingPipeline ? "Starting pipeline..." : "Run full pipeline"}
            </button>
            {activeRun ? <Badge tone="accent">{activeRun.status}</Badge> : null}
          </div>
          {pipelineError ? <p className="error-copy">{pipelineError}</p> : null}
        </div>
        <div className="admin-actions-grid">
          {adminActions.map((action) => (
            <button
              key={action.kind}
              type="button"
              className="action-button"
              onClick={() => onRunJob(action.kind)}
            >
              <strong>{action.label}</strong>
              <span>{action.description}</span>
            </button>
          ))}
        </div>
        <div className="full-pipeline-card">
          <div>
            <h4>Remote analysis sync</h4>
            <p className="supporting-copy">
              Pull the published shared analysis snapshot into local working indices, or
              publish a newly calculated local snapshot back to the remote analysis aliases.
              The remote source KB index stays read-only.
            </p>
          </div>
          <div className="panel-actions">
            <button
              type="button"
              className="action-button"
              onClick={onPullRemoteAnalysis}
              disabled={isStartingPipeline || activeRun?.status === "running" || activeRun?.status === "queued"}
            >
              Pull published remote analysis
            </button>
            <button
              type="button"
              className="primary-button"
              onClick={onPublishRemoteAnalysis}
              disabled={
                isStartingPipeline
                || activeRun?.status === "running"
                || activeRun?.status === "queued"
                || publishBlocked
              }
            >
              Publish local analysis to remote
            </button>
          </div>
          {remoteAnalysisStatus?.publishBlockedReason ? (
            <p className="error-copy">{remoteAnalysisStatus.publishBlockedReason}</p>
          ) : null}
        </div>
      </section>

      <section className="panel-card" aria-label="Remote analysis status">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Remote analysis</p>
            <h3>Shared snapshot status</h3>
          </div>
          {remoteAnalysisStatus ? (
            <Badge tone={remoteAnalysisStatus.enabled ? "success" : "accent"}>
              {remoteAnalysisStatus.enabled ? "configured" : "not configured"}
            </Badge>
          ) : null}
        </div>
        {remoteAnalysisStatus ? (
          <div className="status-stack">
            {remoteAnalysisStatus.localSnapshotStale ? (
              <p className="error-copy">
                Local working indices are older than the latest published remote analysis snapshot.
                Pull the published remote analysis before reviewing or calculating new deltas.
              </p>
            ) : null}
            {remoteAnalysisStatus.publishLock ? (
              <p className="error-copy">
                A remote publish lock is active for <strong>{remoteAnalysisStatus.publishLock.runId}</strong>.
                {remoteAnalysisStatus.publishLock.expiresAt
                  ? ` Expected expiry: ${remoteAnalysisStatus.publishLock.expiresAt}.`
                  : ""}
              </p>
            ) : null}
            <div className="status-summary-grid">
              <article className="status-summary-card">
                <span className="status-label">Source index</span>
                <strong>{remoteAnalysisStatus.sourceIndex}</strong>
                <p>
                  {remoteAnalysisStatus.sourceIndexProtected
                    ? "Protected from analysis publish aliases."
                    : "Warning: analysis alias overlaps the source index."}
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Metadata index</span>
                <strong>{remoteAnalysisStatus.metadataIndex}</strong>
                <p>Stores latest published analysis snapshot metadata.</p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Latest published run</span>
                <strong>{remoteAnalysisStatus.latestPublishedRun?.runId ?? "none"}</strong>
                <p>
                  {remoteAnalysisStatus.latestPublishedRun
                    ? `${remoteAnalysisStatus.latestPublishedRun.embeddingProvider} at ${remoteAnalysisStatus.latestPublishedRun.publishedAt}`
                    : "No published remote analysis snapshot recorded yet."}
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Local sync</span>
                <strong>{remoteAnalysisStatus.localSync?.remoteRunId ?? "none"}</strong>
                <p>
                  {remoteAnalysisStatus.localSync
                    ? `${remoteAnalysisStatus.localSync.embeddingProvider} synced at ${remoteAnalysisStatus.localSync.syncedAt}`
                    : "No local remote-analysis sync recorded yet."}
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Publish lock</span>
                <strong>{remoteAnalysisStatus.publishLock?.runId ?? "none"}</strong>
                <p>
                  {remoteAnalysisStatus.publishLock
                    ? `Held until ${remoteAnalysisStatus.publishLock.expiresAt ?? "unknown expiry"}.`
                    : "No active remote publish lock."}
                </p>
              </article>
            </div>
            <div className="status-detail-grid">
              {Object.entries(remoteAnalysisStatus.aliases).map(([key, aliasStatus]) => (
                <article key={key} className="status-detail-card">
                  <div className="status-detail-header">
                    <strong>{key}</strong>
                    <Badge tone="neutral">{aliasStatus.documentCount} docs</Badge>
                  </div>
                  <p>{aliasStatus.alias}</p>
                  <p>
                    backing indices:{" "}
                    {aliasStatus.backingIndices.length > 0
                      ? aliasStatus.backingIndices.join(", ")
                      : "none"}
                  </p>
                  <p>
                    local docs: {remoteAnalysisStatus.localDocumentCounts[key] ?? 0} / remote docs:{" "}
                    {aliasStatus.documentCount}
                  </p>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <p className="supporting-copy">
            {remoteAnalysisStatusError ?? "Loading remote analysis status..."}
          </p>
        )}
      </section>

      <section className="panel-card" aria-label="Index status">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Index status</p>
            <h3>Content and dedupe backfill completeness</h3>
          </div>
          {indexStatus ? <Badge tone="neutral">{indexStatus.articleIndex.indexName}</Badge> : null}
        </div>
        {indexStatus ? (
          <div className="status-stack">
            <div className="status-summary-grid">
              <article className="status-summary-card">
                <span className="status-label">Articles</span>
                <strong>{indexStatus.articleIndex.totalDocuments}</strong>
                <p>Normalized KB documents in the local article index.</p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Compare text</span>
                <strong>{compareTextCoverage?.presentCount ?? 0}</strong>
                <p>
                  {compareTextCoverage?.percentage ?? 0}% ready for duplicate comparison text.
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Article embeddings</span>
                <strong>{embeddingCoverage?.presentCount ?? 0}</strong>
                <p>
                  {embeddingCoverage?.percentage ?? 0}% with duplicate-comparison vectors.
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Chunk embeddings</span>
                <strong>{indexStatus.chunkIndex.embeddedDocuments}</strong>
                <p>
                  {indexStatus.chunkIndex.embeddingPercentage}% of chunk docs are embedded across{" "}
                  {indexStatus.chunkIndex.chunkedArticles} chunked articles.
                </p>
              </article>
            </div>
            <div className="status-summary-grid">
              <article className="status-summary-card">
                <span className="status-label">Title vectors</span>
                <strong>{titleEmbeddingCoverage?.presentCount ?? 0}</strong>
                <p>
                  {titleEmbeddingCoverage?.percentage ?? 0}% with dedicated title duplicate vectors.
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Summary vectors</span>
                <strong>{summaryEmbeddingCoverage?.presentCount ?? 0}</strong>
                <p>
                  {summaryEmbeddingCoverage?.percentage ?? 0}% with dedicated summary duplicate vectors.
                </p>
              </article>
              <article className="status-summary-card">
                <span className="status-label">Body vectors</span>
                <strong>{bodyEmbeddingCoverage?.presentCount ?? 0}</strong>
                <p>
                  {bodyEmbeddingCoverage?.percentage ?? 0}% with dedicated body duplicate vectors.
                </p>
              </article>
            </div>
            <div className="status-detail-grid">
              {indexStatus.articleIndex.coverage.map((item) => (
                <article key={item.fieldName} className="status-detail-card">
                  <div className="status-detail-header">
                    <strong>{item.fieldName}</strong>
                    <Badge tone={item.missingCount === 0 ? "success" : "accent"}>
                      {item.percentage}%
                    </Badge>
                  </div>
                  <p>
                    present {item.presentCount} / missing {item.missingCount}
                  </p>
                </article>
              ))}
              <article className="status-detail-card">
                <div className="status-detail-header">
                  <strong>{indexStatus.chunkIndex.indexName}</strong>
                  <Badge
                    tone={indexStatus.chunkIndex.missingEmbeddings === 0 ? "success" : "accent"}
                  >
                    {indexStatus.chunkIndex.embeddingPercentage}%
                  </Badge>
                </div>
                <p>
                  chunks {indexStatus.chunkIndex.embeddedDocuments} embedded /{" "}
                  {indexStatus.chunkIndex.totalDocuments} total
                </p>
                <p>
                  chunked articles {indexStatus.chunkIndex.chunkedArticles} / missing{" "}
                  {indexStatus.chunkIndex.missingArticles}
                </p>
              </article>
            </div>
          </div>
        ) : (
          <p className="supporting-copy">
            {indexStatusError ?? "Loading local index completeness..."}
          </p>
        )}
      </section>

      <section className="panel-card" aria-label="Live pipeline logs">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Live logs</p>
            <h3>Streaming pipeline output</h3>
          </div>
          {activeRun ? <Badge tone="neutral">{activeRun.jobId}</Badge> : null}
        </div>
        <div className="log-stream">
          {activeRun ? (
            activeRun.logs.map((entry) => (
              <div key={entry.sequence} className="log-line">
                <strong>{entry.timestamp}</strong>
                <span>[{entry.level}]</span>
                <span>{entry.message}</span>
              </div>
            ))
          ) : (
            <p className="supporting-copy">
              No live pipeline is connected yet. Start the full pipeline to stream logs here.
            </p>
          )}
        </div>
      </section>

      <section className="panel-card" aria-label="Job logs">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Job logs</p>
            <h3>Recent execution history</h3>
          </div>
        </div>
        <div className="log-stack">
          {jobLogs.map((log) => (
            <article key={log.id} className="log-card">
              <div className="log-card-header">
                <strong>{log.startedAt}</strong>
                <Badge tone="success">{log.kind.replaceAll("_", " ")}</Badge>
              </div>
              <p>{log.summary}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
