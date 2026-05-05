import { Badge } from "./Badge";
import { EvidenceList } from "./EvidenceList";
import type { ArticleRecord, CompareDecision, ComparisonRecord, FamilyRecord } from "../types";

type ArticleComparePanelProps = {
  comparison: ComparisonRecord;
  family: FamilyRecord;
  leftArticle: ArticleRecord;
  rightArticle: ArticleRecord;
  onDecision: (decision: CompareDecision) => void;
};

function ScoreMeter({ label, value }: { label: string; value: number }) {
  return (
    <div className="score-meter">
      <div className="score-meter-row">
        <span>{label}</span>
        <strong>{Math.round(value * 100)}%</strong>
      </div>
      <div className="score-track" aria-hidden="true">
        <span className="score-fill" style={{ width: `${value * 100}%` }} />
      </div>
    </div>
  );
}

export function ArticleComparePanel({
  comparison,
  family,
  leftArticle,
  rightArticle,
  onDecision,
}: ArticleComparePanelProps) {
  const decisionButtons: Array<{
    decision: CompareDecision;
    label: string;
    tone: "success" | "neutral" | "warning" | "default";
  }> = [
    { decision: "merge_candidate", label: "Merge candidate", tone: "success" },
    { decision: "related_only", label: "Related only", tone: "neutral" },
    { decision: "keep_separate", label: "Keep separate", tone: "default" },
    { decision: "split_family", label: "Split family", tone: "warning" },
  ];

  return (
    <div className="compare-layout">
      <section className="hero-panel">
        <div className="hero-copy">
          <p className="page-eyebrow">Article Compare</p>
          <h2>Cluster Detail</h2>
          <p className="page-copy">
            Review the evidence for this family and record an editorial decision that
            keeps the consolidation path explainable.
          </p>
        </div>
        <div className="hero-actions">
          <Badge tone="accent">{comparison.label.replaceAll("_", " ")}</Badge>
          <Badge tone="neutral">{family.reviewState.replaceAll("_", " ")}</Badge>
        </div>
      </section>

      <section className="panel-card compare-family-summary" aria-label="Family summary">
        <div>
          <p className="section-kicker">Family</p>
          <h3>{family.rationale}</h3>
        </div>
        <div className="badge-row">
          <Badge>{family.product}</Badge>
          <Badge tone="neutral">{family.category}</Badge>
        </div>
      </section>

      <section className="compare-columns" aria-label="Side-by-side article comparison">
        {[leftArticle, rightArticle].map((article) => (
          <article key={article.id} className="article-card">
            <div className="article-card-header">
              <div>
                <p className="section-kicker">Article</p>
                <h3>{article.title}</h3>
                <p className="article-id">{article.id}</p>
              </div>
              <div className="badge-row">
                {article.visibility.map((badge) => (
                  <Badge key={badge} tone="accent">
                    {badge}
                  </Badge>
                ))}
                <Badge tone="neutral">{article.category}</Badge>
              </div>
            </div>
            <p className="article-summary">{article.summary}</p>
            <dl className="definition-list">
              <div>
                <dt>Products</dt>
                <dd>{article.products.join(", ")}</dd>
              </div>
              <div>
                <dt>Components</dt>
                <dd>{article.components.join(", ")}</dd>
              </div>
              <div>
                <dt>Versions</dt>
                <dd>{article.productVersions.join(", ")}</dd>
              </div>
              <div>
                <dt>Platforms</dt>
                <dd>{article.platforms.join(", ")}</dd>
              </div>
            </dl>
            <div className="section-stack">
              {article.keySections.map((section) => (
                <section key={section.heading} className="section-card">
                  <h4>{section.heading}</h4>
                  <p>{section.text}</p>
                </section>
              ))}
            </div>
          </article>
        ))}
      </section>

      <section className="panel-card" aria-label="Pair scoring">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Scoring</p>
            <h3>Editorial confidence signals</h3>
          </div>
          <Badge tone="success">{Math.round(comparison.totalScore * 100)} total</Badge>
        </div>
        <div className="score-grid">
          <ScoreMeter label="Article embedding" value={comparison.articleEmbeddingSimilarity} />
          <ScoreMeter label="Best chunk" value={comparison.bestChunkSimilarity} />
          <ScoreMeter label="Title similarity" value={comparison.titleSimilarity} />
          <ScoreMeter label="Summary similarity" value={comparison.summarySimilarity} />
          <ScoreMeter label="Metadata agreement" value={comparison.metadataAgreement} />
          <ScoreMeter label="Rerank score" value={comparison.rerankScore} />
        </div>
      </section>

      <EvidenceList
        reasons={comparison.reasons}
        sharedMetadata={comparison.sharedMetadata}
        chunks={comparison.bestChunks}
      />

      {comparison.assistantExplanation ? (
        <section className="panel-card" aria-label="Assistive explanation">
          <div className="panel-header">
            <div>
              <p className="section-kicker">Assistive explanation</p>
              <h3>Secondary LLM note</h3>
            </div>
            <Badge tone="neutral">
              {comparison.assistantExplanation.provider} assist only
            </Badge>
          </div>
          <p className="supporting-copy assistive-warning">
            This explanation is secondary reviewer guidance only. It never overwrites the
            deterministic scores or labels shown above.
          </p>
          <div className="evidence-grid">
            <div className="panel-card inset-panel">
              <h4>Why these look similar</h4>
              <ul className="plain-list">
                {comparison.assistantExplanation.whyTheseAreSimilar.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div className="panel-card inset-panel">
              <h4>What differs</h4>
              <ul className="plain-list">
                {comparison.assistantExplanation.whatDiffers.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
          <p className="supporting-copy">{comparison.assistantExplanation.summary}</p>
          <div className="badge-row">
            <Badge tone="success">
              {Math.round(comparison.assistantExplanation.mergeRecommendationConfidence * 100)}%
              assistive confidence
            </Badge>
            <Badge tone="neutral">{comparison.assistantExplanation.model}</Badge>
            <Badge tone="neutral">{comparison.assistantExplanation.promptVersion}</Badge>
          </div>
        </section>
      ) : null}

      <section className="panel-card decisions-panel" aria-label="Reviewer decisions">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Decision</p>
            <h3>Choose the editorial outcome</h3>
          </div>
        </div>
        <div className="decision-grid">
          {decisionButtons.map((item) => (
            <button
              key={item.decision}
              type="button"
              className="action-button"
              onClick={() => onDecision(item.decision)}
            >
              <Badge tone={item.tone}>{item.label}</Badge>
              <span>
                {item.decision === "merge_candidate" &&
                  "These articles should live as one canonical KB article."}
                {item.decision === "related_only" &&
                  "Keep the family visible for context, but avoid consolidation."}
                {item.decision === "keep_separate" &&
                  "Reject the family because the user problem is materially different."}
                {item.decision === "split_family" &&
                  "Break the family into narrower variants before reviewers merge anything."}
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
