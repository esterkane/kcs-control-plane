import { useState } from "react";

import { Badge } from "../components/Badge";
import { getArticleMap } from "../workflow";
import type {
  CompareDecision,
  ComparisonRecord,
  FamilyRecord,
  LiveClusterSummary,
  ReviewState,
  ArticleRecord,
} from "../types";

type ReviewQueuePageProps = {
  articles: ArticleRecord[];
  comparisons: ComparisonRecord[];
  families: FamilyRecord[];
  onOpenComparison: (comparisonId: string) => void;
  onDecision: (familyId: string, decision: CompareDecision) => void;
  liveClusters: LiveClusterSummary[] | null;
  liveClusterCount: number;
  liveClustersError: string | null;
  onOpenCluster: (clusterId: string) => void;
};

function articleHref(articleId: string): string {
  return `https://support.elastic.dev/knowledge/view/${articleId}`;
}

const queueFilters: ReviewState[] = [
  "pending_review",
  "approved_family",
  "rejected_family",
  "split_required",
];

export function ReviewQueuePage({
  articles,
  comparisons,
  families,
  onOpenComparison,
  onDecision,
  liveClusters,
  liveClusterCount,
  liveClustersError,
  onOpenCluster,
}: ReviewQueuePageProps) {
  const [activeFilter, setActiveFilter] = useState<ReviewState | "all">("pending_review");
  const articleMap = getArticleMap(articles);
  const visibleFamilies = families.filter((family) =>
    activeFilter === "all" ? true : family.reviewState === activeFilter,
  );
  const visibleClusters = (liveClusters ?? []).filter((cluster) =>
    activeFilter === "all" ? true : cluster.reviewState === activeFilter,
  );

  return (
    <div className="page-stack">
      <header className="hero-panel">
        <div className="hero-copy">
          <p className="page-eyebrow">Review Queue</p>
          <h2>Move families through editorial review</h2>
          <p className="page-copy">
            Open a candidate family, inspect the evidence, and record the next editorial
            action without wading through tuning controls.
          </p>
        </div>
      </header>

      <section className="panel-card" aria-label="Review queue filters">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Status filters</p>
            <h3>Queue focus</h3>
          </div>
        </div>
        <div className="filter-row" role="toolbar" aria-label="Queue status filters">
          <button
            type="button"
            className={activeFilter === "all" ? "pill-button pill-button-active" : "pill-button"}
            onClick={() => setActiveFilter("all")}
          >
            All
          </button>
          {queueFilters.map((filterValue) => (
            <button
              key={filterValue}
              type="button"
              className={activeFilter === filterValue ? "pill-button pill-button-active" : "pill-button"}
              onClick={() => setActiveFilter(filterValue)}
            >
              {filterValue.replaceAll("_", " ")}
            </button>
          ))}
        </div>
      </section>

      {liveClusters ? (
        <section className="result-stack" aria-label="Candidate clusters">
          <div className="panel-card">
            <div className="panel-header">
              <div>
                <p className="section-kicker">Live queue</p>
                <h3>Persisted duplicate clusters</h3>
                <p className="supporting-copy">
                  Showing {visibleClusters.length} of {liveClusterCount} cluster records from the
                  backend.
                </p>
              </div>
              <Badge tone="success">{liveClusterCount}</Badge>
            </div>
            {liveClustersError ? <p className="error-copy">{liveClustersError}</p> : null}
          </div>

          {visibleClusters.map((cluster) => (
            <article key={cluster.clusterId} className="result-card">
              <div className="panel-header">
                <div>
                  <p className="section-kicker">Cluster</p>
                  <h3>{cluster.representativeTitle ?? cluster.representativeArticleId}</h3>
                  <p className="supporting-copy">Representative {cluster.representativeArticleId}</p>
                </div>
                <div className="badge-row">
                  <Badge tone="success">{cluster.memberCount} members</Badge>
                  <Badge tone="accent">{cluster.reviewState.replaceAll("_", " ")}</Badge>
                </div>
              </div>
              <dl className="definition-list compact-definition-list">
                <div>
                  <dt>Cluster ID</dt>
                  <dd>{cluster.clusterId}</dd>
                </div>
                <div>
                  <dt>Articles</dt>
                  <dd>
                    {cluster.articleIds.map((articleId, index) => (
                      <span key={articleId}>
                        {index > 0 ? ", " : null}
                        <a href={articleHref(articleId)} target="_blank" rel="noreferrer">
                          {articleId}
                        </a>
                      </span>
                    ))}
                  </dd>
                </div>
              </dl>
              <div className="panel-actions panel-actions-wrap">
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => onOpenCluster(cluster.clusterId)}
                >
                  Open cluster
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <section className="result-stack" aria-label="Candidate families">
          {visibleFamilies.map((family) => {
          const familyComparisons = comparisons.filter((comparison) => comparison.familyId === family.id);
          const leadComparison = familyComparisons[0];
          const representative = articleMap[family.representativeArticleId];
          if (!leadComparison || !representative) {
            return null;
          }
          return (
            <article key={family.id} className="result-card">
              <div className="panel-header">
                <div>
                  <p className="section-kicker">Family</p>
                  <h3>{representative.title}</h3>
                  <p className="supporting-copy">{family.rationale}</p>
                </div>
                <div className="badge-row">
                  <Badge>{family.product}</Badge>
                  <Badge tone="neutral">{family.category}</Badge>
                  <Badge tone="accent">{family.reviewState.replaceAll("_", " ")}</Badge>
                </div>
              </div>

              <dl className="definition-list compact-definition-list">
                <div>
                  <dt>Members</dt>
                  <dd>{family.articleIds.length}</dd>
                </div>
                <div>
                  <dt>Top pair</dt>
                  <dd>
                    {leadComparison.leftArticleId} → {leadComparison.rightArticleId}
                  </dd>
                </div>
                <div>
                  <dt>Evidence score</dt>
                  <dd>{Math.round(leadComparison.totalScore * 100)}%</dd>
                </div>
              </dl>

              <div className="panel-actions panel-actions-wrap">
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => onOpenComparison(leadComparison.id)}
                >
                  Open family
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onDecision(family.id, "merge_candidate")}
                >
                  Approve family
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onDecision(family.id, "split_family")}
                >
                  Request split
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onDecision(family.id, "keep_separate")}
                >
                  Reject family
                </button>
              </div>
            </article>
          );
          })}
        </section>
      )}
    </div>
  );
}
