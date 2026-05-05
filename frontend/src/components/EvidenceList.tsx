import { Badge } from "./Badge";
import type { ChunkEvidence, SharedMetadata } from "../types";

type EvidenceListProps = {
  reasons: string[];
  sharedMetadata: SharedMetadata;
  chunks: ChunkEvidence[];
};

const sharedMetadataLabels: Array<keyof SharedMetadata> = [
  "products",
  "components",
  "productVersions",
  "deployments",
  "platforms",
  "category",
];

export function EvidenceList({
  reasons,
  sharedMetadata,
  chunks,
}: EvidenceListProps) {
  return (
    <section className="evidence-panel" aria-label="Evidence">
      <div className="panel-header">
        <div>
          <p className="section-kicker">Evidence</p>
          <h3>Why this pair was surfaced</h3>
        </div>
      </div>
      <div className="evidence-grid">
        <div className="panel-card">
          <h4>Machine-readable reasons</h4>
          {reasons.length > 0 ? (
            <div className="badge-row">
              {reasons.map((reason) => (
                <Badge key={reason} tone="neutral">
                  {reason.replaceAll("_", " ")}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="supporting-copy">
              No deterministic reason codes were emitted for this candidate.
            </p>
          )}
        </div>
        <div className="panel-card">
          <h4>Shared metadata</h4>
          {sharedMetadataLabels.some((fieldName) => sharedMetadata[fieldName].length > 0) ? (
            <dl className="definition-list">
              {sharedMetadataLabels.map((fieldName) => {
                const values = sharedMetadata[fieldName];
                if (values.length === 0) {
                  return null;
                }
                return (
                  <div key={fieldName}>
                    <dt>{fieldName}</dt>
                    <dd>{values.join(", ")}</dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <p className="supporting-copy">No shared metadata overlap was detected.</p>
          )}
        </div>
      </div>
      <div className="chunk-stack" aria-label="Best matching chunks">
        {chunks.length > 0 ? (
          chunks.map((chunk, index) => (
            <article key={`${chunk.queryHeading}-${index}`} className="chunk-card">
              <div className="chunk-card-header">
                <Badge tone="accent">{Math.round(chunk.similarity * 100)}% match</Badge>
                <span>
                  {chunk.queryHeading} <strong>vs.</strong> {chunk.candidateHeading}
                </span>
              </div>
              <div className="chunk-columns">
                <div>
                  <h4>Query article</h4>
                  <p>{chunk.queryText}</p>
                </div>
                <div>
                  <h4>Candidate article</h4>
                  <p>{chunk.candidateText}</p>
                </div>
              </div>
            </article>
          ))
        ) : (
          <div className="panel-card">
            <p className="supporting-copy">
              No chunk-level evidence was returned for this candidate.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
