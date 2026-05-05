export type PageId =
  | "lookup"
  | "reviewQueue"
  | "clusterExplorer"
  | "clusterDetail"
  | "admin";

export type ReviewState =
  | "pending_review"
  | "approved_family"
  | "rejected_family"
  | "split_required";

export type CompareDecision =
  | "merge_candidate"
  | "related_only"
  | "keep_separate"
  | "split_family";

export type SimilarLabel =
  | "exact_duplicate"
  | "near_duplicate"
  | "same_topic_related"
  | "keep_separate";

export type VisibilityBadge =
  | "External"
  | "Published"
  | "Checked In";

export type SharedMetadata = {
  products: string[];
  components: string[];
  productVersions: string[];
  deployments: string[];
  platforms: string[];
  category: string[];
};

export type ArticleRecord = {
  id: string;
  canonicalUrl: string;
  title: string;
  summary: string;
  category: string;
  visibility: VisibilityBadge[];
  products: string[];
  components: string[];
  productVersions: string[];
  deployments: string[];
  platforms: string[];
  keySections: Array<{
    heading: string;
    text: string;
  }>;
};

export type ChunkEvidence = {
  queryHeading: string;
  candidateHeading: string;
  similarity: number;
  queryText: string;
  candidateText: string;
};

export type AssistiveExplanation = {
  summary: string;
  whyTheseAreSimilar: string[];
  whatDiffers: string[];
  mergeRecommendationConfidence: number;
  provider: string;
  model: string;
  promptVersion: string;
  generatedAt: string;
};

export type ComparisonRecord = {
  id: string;
  familyId: string;
  leftArticleId: string;
  rightArticleId: string;
  label: SimilarLabel;
  totalScore: number;
  titleSimilarity: number;
  summarySimilarity: number;
  articleEmbeddingSimilarity: number;
  bestChunkSimilarity: number;
  metadataAgreement: number;
  rerankScore: number;
  reasons: string[];
  sharedMetadata: SharedMetadata;
  bestChunks: ChunkEvidence[];
  assistantExplanation?: AssistiveExplanation;
};

export type FamilyRecord = {
  id: string;
  representativeArticleId: string;
  articleIds: string[];
  category: string;
  product: string;
  reviewState: ReviewState;
  rationale: string;
};

export type JobKind =
  | "ingest"
  | "embedding_backfill"
  | "cluster_materialization";

export type JobLogRecord = {
  id: string;
  kind: JobKind;
  status: "completed";
  startedAt: string;
  summary: string;
};

export type AdminJobLogEntry = {
  sequence: number;
  level: string;
  message: string;
  timestamp: string;
};

export type AdminPipelineRun = {
  jobId: string;
  status: "queued" | "running" | "succeeded" | "failed";
  logs: AdminJobLogEntry[];
};

export type IndexCoverageStat = {
  fieldName: string;
  presentCount: number;
  missingCount: number;
  percentage: number;
};

export type AdminIndexStatus = {
  articleIndex: {
    indexName: string;
    totalDocuments: number;
    uniqueArticleIds: number;
    coverage: IndexCoverageStat[];
  };
  chunkIndex: {
    indexName: string;
    totalDocuments: number;
    embeddedDocuments: number;
    missingEmbeddings: number;
    embeddingPercentage: number;
    chunkedArticles: number;
    missingArticles: number;
    articleCoveragePercentage: number;
  };
};

export type LiveClusterSummary = {
  clusterId: string;
  articleIds: string[];
  memberCount: number;
  reviewState: ReviewState;
  representativeArticleId: string;
  representativeTitle: string | null;
};

export type LiveClusterListResponse = {
  count: number;
  items: LiveClusterSummary[];
};

export type LiveClusterThresholds = {
  topN: number;
  includeCve: boolean;
  includeChunkSeed: boolean;
  maxComponentSize: number;
  weakEdgeThreshold: number;
  analysisMode: string;
};

export type LiveClusterMembership = {
  articleId: string;
  title: string | null;
  supportingEdgeIds: string[];
  reasons: string[];
  sharedMetadata: Record<string, string[]>;
};

export type LivePairScores = {
  rrfScore: number;
  articleEmbeddingSimilarity: number;
  bestChunkSimilarity: number;
  titleSimilarity: number;
  summarySimilarity: number;
  metadataAgreement: number;
  rerankScore: number;
  totalScore: number;
};

export type LiveChunkEvidence = {
  queryChunkId: string;
  candidateChunkId: string;
  similarity: number;
  queryHeading: string | null;
  candidateHeading: string | null;
  queryText: string;
  candidateText: string;
};

export type LiveClusterEdge = {
  edgeId: string;
  leftArticleId: string;
  rightArticleId: string;
  label: SimilarLabel;
  accepted: boolean;
  totalScore: number;
  pairScores: LivePairScores;
  evidence: {
    sharedMetadata: Record<string, string[]>;
    mostSimilarChunks: LiveChunkEvidence[];
    reasons: string[];
  };
  sourceQueryArticleId: string;
  sourceCandidateArticleId: string;
  materializedAt: string;
  assistantExplanation?: Record<string, unknown> | null;
};

export type LiveClusterDetail = {
  clusterId: string;
  articleIds: string[];
  edgeIds: string[];
  memberCount: number;
  reviewState: ReviewState;
  representativeArticleId: string;
  representativeTitle: string | null;
  memberships: LiveClusterMembership[];
  thresholds: LiveClusterThresholds;
  materializedAt: string;
  assistantExplanation?: Record<string, unknown> | null;
  edges: LiveClusterEdge[];
};

export type LiveSimilarSearchChunk = {
  queryChunkId: string;
  candidateChunkId: string;
  similarity: number;
  queryHeading: string | null;
  candidateHeading: string | null;
  queryText: string;
  candidateText: string;
};

export type LiveSimilarSearchCandidate = {
  articleId: string;
  label: SimilarLabel;
  title: string | null;
  summary: string | null;
  pairScores: LivePairScores;
  evidence: {
    sharedMetadata: Record<string, string[]>;
    mostSimilarChunks: LiveSimilarSearchChunk[];
    reasons: string[];
  };
};

export type LiveSimilarSearchResponse = {
  queryArticleId: string | null;
  candidateCount: number;
  candidates: LiveSimilarSearchCandidate[];
};
