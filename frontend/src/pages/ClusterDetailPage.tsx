import { Badge } from "../components/Badge";
import { ArticleComparePanel } from "../components/ArticleComparePanel";
import { getArticleMap, getComparisonById, getFamilyById } from "../workflow";
import type {
  ArticleRecord,
  CompareDecision,
  ComparisonRecord,
  FamilyRecord,
  LiveClusterDetail,
  ReviewState,
} from "../types";

type ClusterDetailPageProps = {
  articles: ArticleRecord[];
  comparisons: ComparisonRecord[];
  families: FamilyRecord[];
  selectedComparisonId: string;
  selectedClusterId: string | null;
  liveClusterDetail: LiveClusterDetail | null;
  isLoadingLiveClusterDetail: boolean;
  liveClusterDetailError: string | null;
  isUpdatingLiveClusterDecision: boolean;
  liveClusterDecisionError: string | null;
  onLiveClusterDecision: (reviewState: ReviewState) => void;
  onDecision: (familyId: string, decision: CompareDecision) => void;
};

function articleHref(articleId: string): string {
  return `https://support.elastic.dev/knowledge/view/${articleId}`;
}

export function ClusterDetailPage({
  articles,
  comparisons,
  families,
  selectedComparisonId,
  selectedClusterId,
  liveClusterDetail,
  isLoadingLiveClusterDetail,
  liveClusterDetailError,
  isUpdatingLiveClusterDecision,
  liveClusterDecisionError,
  onLiveClusterDecision,
  onDecision,
}: ClusterDetailPageProps) {
  if (selectedClusterId !== null) {
    if (isLoadingLiveClusterDetail) {
      return (
        <div className="page-stack">
          <header className="hero-panel">
            <div className="hero-copy">
              <p className="page-eyebrow">Cluster Detail</p>
              <h2>Loading live cluster</h2>
              <p className="page-copy">
                Fetching persisted cluster evidence from the backend.
              </p>
            </div>
          </header>
        </div>
      );
    }

    if (liveClusterDetailError || !liveClusterDetail) {
      return (
        <div className="page-stack">
          <header className="hero-panel">
            <div className="hero-copy">
              <p className="page-eyebrow">Cluster Detail</p>
              <h2>Cluster detail unavailable</h2>
              <p className="page-copy">
                {liveClusterDetailError ?? "The selected cluster could not be loaded."}
              </p>
            </div>
          </header>
        </div>
      );
    }

    const titleByArticleId = Object.fromEntries(
      liveClusterDetail.memberships.map((membership) => [membership.articleId, membership.title]),
    );
    const topEdges = liveClusterDetail.edges
      .slice()
      .sort((left, right) => right.totalScore - left.totalScore)
      .slice(0, 12);
    const decisionButtons: Array<{
      reviewState: ReviewState;
      label: string;
      tone: "success" | "neutral" | "warning" | "default";
      description: string;
    }> = [
      {
        reviewState: "approved_family",
        label: "Merge candidate",
        tone: "success",
        description: "These articles should live as one canonical KB article.",
      },
      {
        reviewState: "pending_review",
        label: "Related only",
        tone: "neutral",
        description: "Keep the family visible for context, but avoid consolidation.",
      },
      {
        reviewState: "rejected_family",
        label: "Keep separate",
        tone: "default",
        description: "Reject the family because the user problem is materially different.",
      },
      {
        reviewState: "split_required",
        label: "Split family",
        tone: "warning",
        description: "Break the family into narrower variants before reviewers merge anything.",
      },
    ];

    return (
      <div className="page-stack">
        <header className="hero-panel">
          <div className="hero-copy">
            <p className="page-eyebrow">Cluster Detail</p>
            <h2>{liveClusterDetail.representativeTitle ?? liveClusterDetail.representativeArticleId}</h2>
            <p className="page-copy">
              Reviewing persisted duplicate-family evidence from the cluster index.
            </p>
          </div>
          <div className="hero-actions">
            <Badge tone="success">{liveClusterDetail.memberCount} members</Badge>
            <Badge tone="accent">{liveClusterDetail.reviewState.replaceAll("_", " ")}</Badge>
          </div>
        </header>

        <section className="panel-card" aria-label="Cluster summary">
          <div className="panel-header">
            <div>
              <p className="section-kicker">Summary</p>
              <h3>{liveClusterDetail.clusterId}</h3>
            </div>
          </div>
          <dl className="definition-list compact-definition-list">
            <div>
              <dt>Representative</dt>
              <dd>
                <a
                  href={articleHref(liveClusterDetail.representativeArticleId)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {liveClusterDetail.representativeArticleId}
                </a>
              </dd>
            </div>
            <div>
              <dt>Edges</dt>
              <dd>{liveClusterDetail.edgeIds.length}</dd>
            </div>
            <div>
              <dt>Materialized</dt>
              <dd>{liveClusterDetail.materializedAt}</dd>
            </div>
            <div>
              <dt>Analysis mode</dt>
              <dd>{liveClusterDetail.thresholds.analysisMode}</dd>
            </div>
          </dl>
        </section>

        <section className="panel-card" aria-label="Cluster members">
          <div className="panel-header">
            <div>
              <p className="section-kicker">Members</p>
              <h3>Articles in this family</h3>
            </div>
          </div>
          <div className="result-stack">
            {liveClusterDetail.memberships.map((membership) => (
              <article key={membership.articleId} className="result-card">
                <div className="panel-header">
                  <div>
                    <p className="section-kicker">Article</p>
                    <h3>{membership.title ?? membership.articleId}</h3>
                    <p className="supporting-copy">
                      <a
                        href={articleHref(membership.articleId)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {membership.articleId}
                      </a>
                    </p>
                  </div>
                  <Badge tone="neutral">
                    {membership.supportingEdgeIds.length} supporting edges
                  </Badge>
                </div>
                <p className="supporting-copy">
                  Reasons: {membership.reasons.length > 0 ? membership.reasons.join(", ") : "n/a"}
                </p>
                {Object.keys(membership.sharedMetadata).length > 0 ? (
                  <p className="supporting-copy">
                    Shared metadata:{" "}
                    {Object.entries(membership.sharedMetadata)
                      .map(([key, values]) => `${key}: ${values.join(", ")}`)
                      .join(" • ")}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </section>

        <section className="panel-card" aria-label="Strongest edges">
          <div className="panel-header">
            <div>
              <p className="section-kicker">Evidence</p>
              <h3>Strongest accepted pairs</h3>
            </div>
          </div>
          <div className="result-stack">
            {topEdges.map((edge) => (
              <article key={edge.edgeId} className="result-card">
                <div className="panel-header">
                  <div>
                    <p className="section-kicker">Accepted edge</p>
                    <h3>
                      {titleByArticleId[edge.leftArticleId] ?? edge.leftArticleId} vs.{" "}
                      {titleByArticleId[edge.rightArticleId] ?? edge.rightArticleId}
                    </h3>
                    <p className="supporting-copy">
                      <a href={articleHref(edge.leftArticleId)} target="_blank" rel="noreferrer">
                        {edge.leftArticleId}
                      </a>{" "}
                      →{" "}
                      <a href={articleHref(edge.rightArticleId)} target="_blank" rel="noreferrer">
                        {edge.rightArticleId}
                      </a>
                    </p>
                  </div>
                  <div className="badge-row">
                    <Badge tone="success">{Math.round(edge.totalScore * 100)} score</Badge>
                    <Badge tone="accent">{edge.label.replaceAll("_", " ")}</Badge>
                  </div>
                </div>
                <p className="supporting-copy">
                  Reasons: {edge.evidence.reasons.length > 0 ? edge.evidence.reasons.join(", ") : "n/a"}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="panel-card decisions-panel" aria-label="Reviewer decisions">
          <div className="panel-header">
            <div>
              <p className="section-kicker">Decision</p>
              <h3>Choose the editorial outcome</h3>
            </div>
            <Badge tone="neutral">{liveClusterDetail.reviewState.replaceAll("_", " ")}</Badge>
          </div>
          {liveClusterDecisionError ? <p className="error-copy">{liveClusterDecisionError}</p> : null}
          <div className="decision-grid">
            {decisionButtons.map((item) => (
              <button
                key={item.reviewState}
                type="button"
                className="action-button"
                disabled={isUpdatingLiveClusterDecision}
                onClick={() => onLiveClusterDecision(item.reviewState)}
              >
                <Badge tone={item.tone}>{item.label}</Badge>
                <span>{item.description}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    );
  }

  const articleMap = getArticleMap(articles);
  const comparison = getComparisonById(comparisons, selectedComparisonId);
  const family = comparison ? getFamilyById(families, comparison.familyId) : undefined;
  const leftArticle = comparison ? articleMap[comparison.leftArticleId] : undefined;
  const rightArticle = comparison ? articleMap[comparison.rightArticleId] : undefined;

  if (!comparison || !family || !leftArticle || !rightArticle) {
    return (
      <div className="page-stack">
        <header className="hero-panel">
          <div className="hero-copy">
            <p className="page-eyebrow">Cluster Detail</p>
            <h2>No comparison selected</h2>
            <p className="page-copy">
              Open a family from Lookup, Review Queue, or Cluster Explorer to inspect
              side-by-side evidence.
            </p>
          </div>
        </header>
      </div>
    );
  }

  return (
    <ArticleComparePanel
      comparison={comparison}
      family={family}
      leftArticle={leftArticle}
      rightArticle={rightArticle}
      onDecision={(decision) => onDecision(family.id, decision)}
    />
  );
}
