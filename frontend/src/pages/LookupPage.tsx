import { useDeferredValue, useEffect, useState, useTransition } from "react";

import { Badge } from "../components/Badge";
import { EvidenceList } from "../components/EvidenceList";
import { getArticleMap, searchComparisons } from "../workflow";
import type {
  ArticleRecord,
  ComparisonRecord,
  FamilyRecord,
  LiveClusterSummary,
  LiveSimilarSearchResponse,
  SharedMetadata,
} from "../types";

type LookupPageProps = {
  apiBaseUrl: string;
  articles: ArticleRecord[];
  comparisons: ComparisonRecord[];
  families: FamilyRecord[];
  onOpenComparison: (comparisonId: string) => void;
  onOpenCluster: (clusterId: string) => void;
};

const articleBaseUrl = (import.meta.env.VITE_SUPPORT_ARTICLE_BASE_URL ?? "").replace(/\/$/, "");

function articleHref(articleId: string): string {
  return articleBaseUrl ? `${articleBaseUrl}/${encodeURIComponent(articleId)}` : "#";
}

function isLiveSimilarSearchResponse(payload: unknown): payload is LiveSimilarSearchResponse {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const candidate = payload as Record<string, unknown>;
  return typeof candidate.candidateCount === "number" && Array.isArray(candidate.candidates);
}

function normalizeSharedMetadata(input: Record<string, string[]>): SharedMetadata {
  return {
    products: input.products ?? [],
    components: input.components ?? [],
    productVersions: input.product_versions ?? [],
    deployments: input.deployments ?? [],
    platforms: input.platforms ?? [],
    category: input.category ?? [],
  };
}

export function LookupPage({
  apiBaseUrl,
  articles,
  comparisons,
  families,
  onOpenComparison,
  onOpenCluster,
}: LookupPageProps) {
  const [query, setQuery] = useState("");
  const [searchText, setSearchText] = useState("");
  const [liveResults, setLiveResults] = useState<LiveSimilarSearchResponse | null>(null);
  const [liveSearchError, setLiveSearchError] = useState<string | null>(null);
  const [liveResultClusters, setLiveResultClusters] = useState<Record<string, LiveClusterSummary | null>>({});
  const [isPending, startTransition] = useTransition();
  const deferredSearchText = useDeferredValue(searchText);
  const articleMap = getArticleMap(articles);
  const fallbackResults = searchComparisons(deferredSearchText, articles, comparisons);

  async function runLiveSearch(rawQuery: string): Promise<void> {
    const trimmedQuery = rawQuery.trim();
    if (!trimmedQuery) {
      setLiveResults(null);
      setLiveSearchError(null);
      return;
    }

    try {
      const articleIdLike = /^[A-Za-z0-9-]{4,}$/.test(trimmedQuery) && !trimmedQuery.includes(" ");
      if (articleIdLike) {
        const articleResponse = await fetch(
          `${apiBaseUrl}/kb/articles/${encodeURIComponent(trimmedQuery)}/similar?limit=12`,
        );
        if (articleResponse.ok) {
          const articlePayload = await articleResponse.json();
          if (isLiveSimilarSearchResponse(articlePayload)) {
            setLiveResults(articlePayload);
            setLiveSearchError(null);
            return;
          }
        }
      }

      const response = await fetch(`${apiBaseUrl}/kb/similar/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: trimmedQuery,
          summary: trimmedQuery,
          compareText: trimmedQuery,
          includeChunkSeed: true,
          limit: 12,
        }),
      });
      if (!response.ok) {
        throw new Error(`Search failed: ${response.status}`);
      }
      const payload = await response.json();
      if (!isLiveSimilarSearchResponse(payload)) {
        setLiveResults(null);
        setLiveSearchError(null);
        return;
      }
      setLiveResults(payload);
      setLiveResultClusters({});
      setLiveSearchError(null);
    } catch (error) {
      setLiveResults(null);
      setLiveResultClusters({});
      setLiveSearchError(error instanceof Error ? error.message : "Search failed.");
    }
  }

  useEffect(() => {
    if (!liveResults) {
      return;
    }

    let cancelled = false;

    async function loadClusterMemberships(): Promise<void> {
      const entries = await Promise.all(
        liveResults.candidates.map(async (candidate) => {
          try {
            const response = await fetch(
              `${apiBaseUrl}/kb/articles/${encodeURIComponent(candidate.articleId)}/cluster`,
            );
            if (!response.ok) {
              return [candidate.articleId, null] as const;
            }
            const payload = (await response.json()) as LiveClusterSummary;
            return [candidate.articleId, payload] as const;
          } catch {
            return [candidate.articleId, null] as const;
          }
        }),
      );
      if (cancelled) {
        return;
      }
      setLiveResultClusters(Object.fromEntries(entries));
    }

    void loadClusterMemberships();

    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, liveResults]);

  return (
    <div className="page-stack">
      <header className="hero-panel">
        <div className="hero-copy">
          <p className="page-eyebrow">Lookup</p>
          <h2>Find possible duplicates fast</h2>
          <p className="page-copy">
            Search by article ID, canonical URL, title, or free text and jump straight
            into the evidence that matters for editorial review.
          </p>
        </div>
      </header>

      <section className="panel-card" aria-label="Lookup search">
        <form
          className="search-form"
          onSubmit={(event) => {
            event.preventDefault();
            startTransition(() => {
              setSearchText(query);
            });
            void runLiveSearch(query);
          }}
        >
          <label className="field-label" htmlFor="lookup-query">
            Search for an article or symptom
          </label>
          <div className="search-row">
            <input
              id="lookup-query"
              name="lookup-query"
              type="search"
              value={query}
              placeholder="Try KB-10214, a portal URL, or 'MFA redirect loop'"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button type="submit" className="primary-button">
              Search
            </button>
          </div>
        </form>
        <p className="supporting-copy" aria-live="polite">
          {isPending
            ? "Updating results…"
            : liveResults
              ? `${liveResults.candidateCount} live candidates ready for review.`
              : `${fallbackResults.length} ranked candidates ready for review.`}
        </p>
        {liveSearchError ? <p className="error-copy">{liveSearchError}</p> : null}
      </section>

      <section className="result-stack" aria-label="Ranked similar candidates">
        {liveResults ? liveResults.candidates.map((candidate) => {
          const totalScore = candidate.pairScores.totalScore;
          const cluster = liveResultClusters[candidate.articleId] ?? null;
          return (
            <article key={candidate.articleId} className="result-card">
              <div className="panel-header">
                <div>
                  <p className="section-kicker">Candidate article</p>
                  <h3>{candidate.articleId}</h3>
                  <p className="supporting-copy">{candidate.title ?? "Untitled article"}</p>
                </div>
                <div className="badge-row">
                  <Badge tone="success">{Math.round(totalScore * 100)} score</Badge>
                  <Badge tone="accent">{candidate.label.replaceAll("_", " ")}</Badge>
                </div>
              </div>

              <div className="result-summary-grid">
                <section className="panel-card inset-panel">
                  <h4>Search query</h4>
                  <p>{searchText || query}</p>
                </section>
                <section className="panel-card inset-panel">
                  <h4>{candidate.title ?? candidate.articleId}</h4>
                  <p>{candidate.summary ?? "No summary available."}</p>
                </section>
              </div>

              <EvidenceList
                reasons={candidate.evidence.reasons}
                sharedMetadata={normalizeSharedMetadata(candidate.evidence.sharedMetadata)}
                chunks={candidate.evidence.mostSimilarChunks.map((chunk) => ({
                  queryHeading: chunk.queryHeading ?? "Query",
                  candidateHeading: chunk.candidateHeading ?? "Candidate",
                  similarity: chunk.similarity,
                  queryText: chunk.queryText,
                  candidateText: chunk.candidateText,
                }))}
              />

              <section className="panel-card inset-panel" aria-label="Cluster membership">
                <h4>Potential duplicate cluster</h4>
                {cluster ? (
                  <>
                    <p className="supporting-copy">
                      This article is already part of cluster <strong>{cluster.clusterId}</strong>.
                    </p>
                    <div className="badge-row">
                      <Badge tone="success">{cluster.memberCount} members</Badge>
                      <Badge tone="accent">{cluster.reviewState.replaceAll("_", " ")}</Badge>
                    </div>
                    <p className="supporting-copy">
                      Representative: {cluster.representativeTitle ?? cluster.representativeArticleId}
                    </p>
                  </>
                ) : (
                  <p className="supporting-copy">
                    This article is not currently assigned to a persisted duplicate cluster.
                  </p>
                )}
              </section>

              <div className="panel-actions">
                <a
                  className="primary-button"
                  href={articleHref(candidate.articleId)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open article
                </a>
                {cluster ? (
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => onOpenCluster(cluster.clusterId)}
                  >
                    Open cluster
                  </button>
                ) : null}
              </div>
            </article>
          );
        }) : fallbackResults.map((comparison) => {
          const leftArticle = articleMap[comparison.leftArticleId];
          const rightArticle = articleMap[comparison.rightArticleId];
          const family = families.find((item) => item.id === comparison.familyId);
          if (!leftArticle || !rightArticle || !family) {
            return null;
          }
          return (
            <article key={comparison.id} className="result-card">
              <div className="panel-header">
                <div>
                  <p className="section-kicker">Candidate pair</p>
                  <h3>{leftArticle.id} → {rightArticle.id}</h3>
                  <p className="supporting-copy">
                    {leftArticle.title} <strong>vs.</strong> {rightArticle.title}
                  </p>
                </div>
                <div className="badge-row">
                  <Badge tone="success">{Math.round(comparison.totalScore * 100)} score</Badge>
                  <Badge tone="accent">{comparison.label.replaceAll("_", " ")}</Badge>
                  <Badge tone="neutral">{family.reviewState.replaceAll("_", " ")}</Badge>
                </div>
              </div>

              <div className="result-summary-grid">
                <section className="panel-card inset-panel">
                  <h4>{leftArticle.title}</h4>
                  <p>{leftArticle.summary}</p>
                </section>
                <section className="panel-card inset-panel">
                  <h4>{rightArticle.title}</h4>
                  <p>{rightArticle.summary}</p>
                </section>
              </div>

              <EvidenceList
                reasons={comparison.reasons}
                sharedMetadata={comparison.sharedMetadata}
                chunks={comparison.bestChunks}
              />

              <div className="panel-actions">
                <a
                  className="secondary-button"
                  href={articleHref(leftArticle.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Left article
                </a>
                <a
                  className="secondary-button"
                  href={articleHref(rightArticle.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Right article
                </a>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => onOpenComparison(comparison.id)}
                >
                  Open compare view
                </button>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
