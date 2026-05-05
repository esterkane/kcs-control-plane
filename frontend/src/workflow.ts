import type {
  ArticleRecord,
  CompareDecision,
  ComparisonRecord,
  FamilyRecord,
  JobKind,
  JobLogRecord,
  PageId,
  ReviewState,
} from "./types";

export type WorkflowState = {
  articles: ArticleRecord[];
  comparisons: ComparisonRecord[];
  families: FamilyRecord[];
  selectedComparisonId: string;
  activePageId: PageId;
  jobLogs: JobLogRecord[];
};

export type WorkflowAction =
  | { type: "navigate"; pageId: PageId }
  | { type: "openComparison"; comparisonId: string }
  | { type: "applyDecision"; familyId: string; decision: CompareDecision }
  | { type: "runJob"; jobKind: JobKind };

export const decisionToReviewState: Record<CompareDecision, ReviewState> = {
  merge_candidate: "approved_family",
  related_only: "pending_review",
  keep_separate: "rejected_family",
  split_family: "split_required",
};

export function reduceWorkflowState(
  state: WorkflowState,
  action: WorkflowAction,
): WorkflowState {
  switch (action.type) {
    case "navigate":
      return {
        ...state,
        activePageId: action.pageId,
      };
    case "openComparison":
      return {
        ...state,
        activePageId: "clusterDetail",
        selectedComparisonId: action.comparisonId,
      };
    case "applyDecision": {
      const nextReviewState = decisionToReviewState[action.decision];
      const nextFamilies = state.families.map((family) =>
        family.id === action.familyId
          ? {
              ...family,
              reviewState: nextReviewState,
            }
          : family,
      );
      return {
        ...state,
        families: nextFamilies,
        activePageId: "reviewQueue",
      };
    }
    case "runJob": {
      const labelByKind: Record<JobKind, string> = {
        ingest: "Ingestion",
        embedding_backfill: "Embedding backfill",
        cluster_materialization: "Cluster materialization",
      };
      const summaryByKind: Record<JobKind, string> = {
        ingest: "Queued a fresh KB ingestion run for the source cluster.",
        embedding_backfill:
          "Queued duplicate-comparison embedding backfill for articles and chunks.",
        cluster_materialization:
          "Queued duplicate-edge materialization and deterministic family clustering.",
      };
      const nextLog: JobLogRecord = {
        id: `job-${action.jobKind}-${state.jobLogs.length + 1}`,
        kind: action.jobKind,
        status: "completed",
        startedAt: "2026-04-28 16:55",
        summary: `${labelByKind[action.jobKind]}: ${summaryByKind[action.jobKind]}`,
      };
      return {
        ...state,
        activePageId: "admin",
        jobLogs: [nextLog, ...state.jobLogs],
      };
    }
    default:
      return state;
  }
}

export function getArticleMap(articles: ArticleRecord[]): Record<string, ArticleRecord> {
  return Object.fromEntries(articles.map((article) => [article.id, article]));
}

export function getFamilyById(
  families: FamilyRecord[],
  familyId: string,
): FamilyRecord | undefined {
  return families.find((family) => family.id === familyId);
}

export function getComparisonById(
  comparisons: ComparisonRecord[],
  comparisonId: string,
): ComparisonRecord | undefined {
  return comparisons.find((comparison) => comparison.id === comparisonId);
}

export function searchComparisons(
  query: string,
  articles: ArticleRecord[],
  comparisons: ComparisonRecord[],
): ComparisonRecord[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return comparisons
      .slice()
      .sort((left, right) => right.totalScore - left.totalScore);
  }

  const articleMap = getArticleMap(articles);
  const ranked = comparisons
    .map((comparison) => {
      const left = articleMap[comparison.leftArticleId];
      const right = articleMap[comparison.rightArticleId];
      if (!left || !right) {
        return null;
      }
      const searchableParts = [
        left.id,
        left.canonicalUrl,
        left.title,
        left.summary,
        right.id,
        right.canonicalUrl,
        right.title,
        right.summary,
        comparison.reasons.join(" "),
        comparison.sharedMetadata.products.join(" "),
        comparison.sharedMetadata.components.join(" "),
      ]
        .join(" ")
        .toLowerCase();
      const isMatch = searchableParts.includes(normalizedQuery);
      if (!isMatch) {
        return null;
      }
      return comparison;
    })
    .filter((comparison): comparison is ComparisonRecord => comparison !== null);

  return ranked.sort((left, right) => right.totalScore - left.totalScore);
}
