import { useState } from "react";

import { Badge } from "../components/Badge";
import { getArticleMap } from "../workflow";
import type {
  ArticleRecord,
  ComparisonRecord,
  FamilyRecord,
  LiveClusterSummary,
} from "../types";

type ClusterExplorerPageProps = {
  articles: ArticleRecord[];
  comparisons: ComparisonRecord[];
  families: FamilyRecord[];
  onOpenComparison: (comparisonId: string) => void;
  liveClusters: LiveClusterSummary[] | null;
  liveClusterCount: number;
  liveClusterPage: number;
  liveClusterPageSize: number;
  liveClusterTotalPages: number;
  liveClustersError: string | null;
  onOpenCluster: (clusterId: string) => void;
  onChangeLiveClusterPage: (page: number) => void;
};

const articleBaseUrl = (import.meta.env.VITE_SUPPORT_ARTICLE_BASE_URL ?? "").replace(/\/$/, "");

function articleHref(articleId: string): string {
  return articleBaseUrl ? `${articleBaseUrl}/${encodeURIComponent(articleId)}` : "#";
}

export function ClusterExplorerPage({
  articles,
  comparisons,
  families,
  onOpenComparison,
  liveClusters,
  liveClusterCount,
  liveClusterPage,
  liveClusterPageSize,
  liveClusterTotalPages,
  liveClustersError,
  onOpenCluster,
  onChangeLiveClusterPage,
}: ClusterExplorerPageProps) {
  const [showVisualization, setShowVisualization] = useState(false);
  const [productFilter, setProductFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");

  const articleMap = getArticleMap(articles);
  const products = Array.from(new Set(families.map((family) => family.product))).sort();
  const categories = Array.from(new Set(families.map((family) => family.category))).sort();

  const visibleFamilies = families.filter((family) => {
    const matchesProduct = productFilter === "all" || family.product === productFilter;
    const matchesCategory = categoryFilter === "all" || family.category === categoryFilter;
    return matchesProduct && matchesCategory;
  });
  const visibleClusters = liveClusters ?? [];

  return (
    <div className="page-stack">
      <header className="hero-panel">
        <div className="hero-copy">
          <p className="page-eyebrow">Cluster Explorer</p>
          <h2>Browse families without losing the reviewer thread</h2>
          <p className="page-copy">
            Use filters to narrow by product and category, then open the strongest pair
            directly into the compare workflow.
          </p>
        </div>
      </header>

      {liveClusters ? (
        <>
          <section className="panel-card" aria-label="Live cluster explorer">
            <div className="panel-header">
              <div>
                <p className="section-kicker">Live clusters</p>
                <h3>Real cluster materialization output</h3>
                <p className="supporting-copy">
                  Showing page {liveClusterPage} of {liveClusterTotalPages}, with up to {liveClusterPageSize}
                  {" "}persisted clusters per page. Total persisted clusters: {liveClusterCount}.
                </p>
              </div>
              <Badge tone="success">{liveClusterCount} total</Badge>
            </div>
            {liveClustersError ? <p className="error-copy">{liveClustersError}</p> : null}
            <div className="panel-actions panel-actions-wrap">
              <button
                type="button"
                className="secondary-button"
                onClick={() => onChangeLiveClusterPage(liveClusterPage - 1)}
                disabled={liveClusterPage <= 1}
              >
                Previous page
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => onChangeLiveClusterPage(liveClusterPage + 1)}
                disabled={liveClusterPage >= liveClusterTotalPages}
              >
                Next page
              </button>
            </div>
          </section>

          <section className="result-stack" aria-label="Live cluster list">
            {visibleClusters.map((cluster) => (
              <article key={cluster.clusterId} className="result-card">
                <div className="panel-header">
                  <div>
                    <p className="section-kicker">Cluster</p>
                    <h3>{cluster.representativeTitle ?? cluster.representativeArticleId}</h3>
                    <p className="supporting-copy">
                      Representative article {cluster.representativeArticleId}
                    </p>
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
                    <dt>Representative</dt>
                    <dd>
                      <a
                        href={articleHref(cluster.representativeArticleId)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {cluster.representativeArticleId}
                      </a>
                    </dd>
                  </div>
                </dl>
                <div className="panel-actions">
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => onOpenCluster(cluster.clusterId)}
                  >
                    Open cluster detail
                  </button>
                </div>
              </article>
            ))}
          </section>
        </>
      ) : (
        <>
          <section className="panel-card" aria-label="Cluster explorer controls">
            <div className="filter-grid">
              <label className="field-label">
                Product
                <select
                  value={productFilter}
                  onChange={(event) => setProductFilter(event.target.value)}
                >
                  <option value="all">All products</option>
                  {products.map((product) => (
                    <option key={product} value={product}>
                      {product}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-label">
                Category
                <select
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                >
                  <option value="all">All categories</option>
                  {categories.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </label>
              <label className="toggle-card">
                <input
                  type="checkbox"
                  checked={showVisualization}
                  onChange={(event) => setShowVisualization(event.target.checked)}
                />
                <span>Show visualization panel</span>
              </label>
            </div>
          </section>

          {showVisualization ? (
            <section className="panel-card visualization-panel" aria-label="Visualization panel">
              <div className="panel-header">
                <div>
                  <p className="section-kicker">Optional view</p>
                  <h3>Family topology preview</h3>
                </div>
              </div>
              <div className="viz-grid">
                {visibleFamilies.map((family) => (
                  <div key={family.id} className="viz-card">
                    <strong>{family.id}</strong>
                    <span>{family.articleIds.length} members</span>
                    <div className="viz-nodes" aria-hidden="true">
                      {family.articleIds.map((articleId) => (
                        <span key={articleId} className="viz-node" />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="result-stack" aria-label="Cluster list">
            {visibleFamilies.map((family) => {
              const representative = articleMap[family.representativeArticleId];
              const leadComparison = comparisons.find((comparison) => comparison.familyId === family.id);
              if (!representative || !leadComparison) {
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
                      <dt>Lead pair</dt>
                      <dd>{leadComparison.leftArticleId} → {leadComparison.rightArticleId}</dd>
                    </div>
                    <div>
                      <dt>Best score</dt>
                      <dd>{Math.round(leadComparison.totalScore * 100)}%</dd>
                    </div>
                  </dl>
                  <div className="panel-actions">
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => onOpenComparison(leadComparison.id)}
                    >
                      Open compare view
                    </button>
                  </div>
                </article>
              );
            })}
          </section>
        </>
      )}
    </div>
  );
}
