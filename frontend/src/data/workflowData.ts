import type {
  ArticleRecord,
  ComparisonRecord,
  FamilyRecord,
  JobLogRecord,
  SharedMetadata,
} from "../types";

const emptySharedMetadata = (): SharedMetadata => ({
  products: [],
  components: [],
  productVersions: [],
  deployments: [],
  platforms: [],
  category: [],
});

export const mockArticles: ArticleRecord[] = [
  {
    id: "KB-10214",
    canonicalUrl: "https://kb.example.com/articles/KB-10214",
    title: "VPN users are redirected back to the sign-in page after MFA",
    summary: "Remote workers complete MFA successfully but return to the original sign-in screen instead of entering the portal.",
    category: "Access",
    visibility: ["External", "Published", "Checked In"],
    products: ["Cloud Secure Access"],
    components: ["Identity Gateway"],
    productVersions: ["2026.3"],
    deployments: ["Multi-tenant"],
    platforms: ["Windows", "macOS"],
    keySections: [
      {
        heading: "Summary",
        text: "Users on remote VPN see a successful MFA prompt and are redirected to the sign-in page with no portal access.",
      },
      {
        heading: "Cause",
        text: "The IdP session cookie is scoped to the vanity hostname while the callback target is still the platform hostname.",
      },
      {
        heading: "Resolution",
        text: "Align the callback hostname with the vanity domain and rotate the SSO connector metadata after saving the new redirect URI.",
      },
      {
        heading: "Environment",
        text: "Cloud Secure Access 2026.3 with Identity Gateway and SAML-based MFA.",
      },
    ],
  },
  {
    id: "KB-10277",
    canonicalUrl: "https://kb.example.com/articles/KB-10277",
    title: "MFA redirect loop after VPN authentication",
    summary: "After a valid MFA challenge, the portal returns users to the login page and never opens the app launcher.",
    category: "Access",
    visibility: ["External", "Published"],
    products: ["Cloud Secure Access"],
    components: ["Identity Gateway"],
    productVersions: ["2026.3"],
    deployments: ["Multi-tenant"],
    platforms: ["Windows", "macOS"],
    keySections: [
      {
        heading: "Summary",
        text: "An MFA-complete session loops back to login instead of establishing the final portal session.",
      },
      {
        heading: "Workaround",
        text: "Set the SSO connector to use the vanity callback URL and clear the cached IdP metadata before retrying.",
      },
      {
        heading: "Resolution",
        text: "Re-publish the connector configuration with a callback host that matches the SAML audience and portal origin.",
      },
      {
        heading: "Environment",
        text: "Identity Gateway with Cloud Secure Access running the 2026.3 rollout.",
      },
    ],
  },
  {
    id: "KB-10401",
    canonicalUrl: "https://kb.example.com/articles/KB-10401",
    title: "Provisioning succeeds but new macOS devices stay in pending sync",
    summary: "Enrollment jobs finish on the server, yet the device list shows pending sync for newly registered macOS endpoints.",
    category: "Device Management",
    visibility: ["Published", "Checked In"],
    products: ["Endpoint Control"],
    components: ["Provisioning Service"],
    productVersions: ["11.9"],
    deployments: ["Regional"],
    platforms: ["macOS"],
    keySections: [
      {
        heading: "Summary",
        text: "Provisioning completes but device state remains pending sync for up to six hours.",
      },
      {
        heading: "Cause",
        text: "The queue consumer cannot reconcile the bootstrap token if the initial sync happens before the profile trust handshake completes.",
      },
      {
        heading: "Resolution",
        text: "Restart the Provisioning Service consumers and trigger a policy refresh after trust enrollment completes.",
      },
      {
        heading: "Environment",
        text: "Endpoint Control 11.9 on regional deployments managing macOS endpoints.",
      },
    ],
  },
  {
    id: "KB-10408",
    canonicalUrl: "https://kb.example.com/articles/KB-10408",
    title: "macOS endpoint remains queued after enrollment",
    summary: "Administrators see a successful enrollment event, but the endpoint dashboard keeps the device in queued sync state.",
    category: "Device Management",
    visibility: ["Published"],
    products: ["Endpoint Control"],
    components: ["Provisioning Service"],
    productVersions: ["11.9"],
    deployments: ["Regional"],
    platforms: ["macOS"],
    keySections: [
      {
        heading: "Summary",
        text: "Recently enrolled devices remain queued instead of moving into active policy sync.",
      },
      {
        heading: "Workaround",
        text: "Force a second policy pull after the trust profile finishes installing and confirm the bootstrap token record is present.",
      },
      {
        heading: "Resolution",
        text: "Upgrade the Provisioning Service consumer patch and replay delayed queue items from the regional worker.",
      },
      {
        heading: "Environment",
        text: "Regional Endpoint Control tenant running macOS enrollments on version 11.9.",
      },
    ],
  },
  {
    id: "KB-10555",
    canonicalUrl: "https://kb.example.com/articles/KB-10555",
    title: "How to rotate SAML signing certificates for Identity Gateway",
    summary: "Planned maintenance guide for rolling SAML signing certificates without disrupting user sessions.",
    category: "Administration",
    visibility: ["External", "Published"],
    products: ["Cloud Secure Access"],
    components: ["Identity Gateway"],
    productVersions: ["2026.3"],
    deployments: ["Multi-tenant"],
    platforms: ["Windows", "macOS"],
    keySections: [
      {
        heading: "Summary",
        text: "Certificate rotation procedure for Identity Gateway administrators.",
      },
      {
        heading: "Resolution",
        text: "Upload the new signing certificate, publish the federation metadata, and verify the IdP trust path before expiry.",
      },
      {
        heading: "Environment",
        text: "Cloud Secure Access with Identity Gateway and external IdP federation.",
      },
    ],
  },
];

export const mockComparisons: ComparisonRecord[] = [
  {
    id: "cmp-lookup-vpn-loop",
    familyId: "family-access-mfa",
    leftArticleId: "KB-10214",
    rightArticleId: "KB-10277",
    label: "exact_duplicate",
    totalScore: 0.94,
    titleSimilarity: 0.89,
    summarySimilarity: 0.82,
    articleEmbeddingSimilarity: 0.93,
    bestChunkSimilarity: 0.88,
    metadataAgreement: 1,
    rerankScore: 0.91,
    reasons: [
      "high_article_embedding_similarity",
      "high_chunk_similarity",
      "shared_metadata",
      "reranker_support",
    ],
    sharedMetadata: {
      products: ["Cloud Secure Access"],
      components: ["Identity Gateway"],
      productVersions: ["2026.3"],
      deployments: ["Multi-tenant"],
      platforms: ["Windows", "macOS"],
      category: ["Access"],
    },
    bestChunks: [
      {
        queryHeading: "Cause",
        candidateHeading: "Resolution",
        similarity: 0.88,
        queryText: "The IdP session cookie is scoped to the vanity hostname while the callback target is still the platform hostname.",
        candidateText: "Re-publish the connector configuration with a callback host that matches the SAML audience and portal origin.",
      },
      {
        queryHeading: "Resolution",
        candidateHeading: "Workaround",
        similarity: 0.83,
        queryText: "Align the callback hostname with the vanity domain and rotate the SSO connector metadata after saving the new redirect URI.",
        candidateText: "Set the SSO connector to use the vanity callback URL and clear the cached IdP metadata before retrying.",
      },
    ],
    assistantExplanation: {
      summary: "Assistive model note: both writeups describe the same MFA callback mismatch and differ mostly in phrasing.",
      whyTheseAreSimilar: [
        "The environment and product metadata are identical.",
        "The best matching chunks point to the same callback-hostname failure mode.",
      ],
      whatDiffers: [
        "The second article frames one remediation step as a workaround rather than the primary fix.",
      ],
      mergeRecommendationConfidence: 0.84,
      provider: "gemini",
      model: "gemini-3-flash-preview",
      promptVersion: "pair-cluster-explainer-v1",
      generatedAt: "2026-04-28T12:00:00Z",
    },
  },
  {
    id: "cmp-access-guide",
    familyId: "family-access-mfa",
    leftArticleId: "KB-10214",
    rightArticleId: "KB-10555",
    label: "same_topic_related",
    totalScore: 0.48,
    titleSimilarity: 0.24,
    summarySimilarity: 0.18,
    articleEmbeddingSimilarity: 0.47,
    bestChunkSimilarity: 0.39,
    metadataAgreement: 0.8,
    rerankScore: 0.44,
    reasons: ["shared_metadata", "reranker_support"],
    sharedMetadata: {
      ...emptySharedMetadata(),
      products: ["Cloud Secure Access"],
      components: ["Identity Gateway"],
      productVersions: ["2026.3"],
      deployments: ["Multi-tenant"],
      platforms: ["Windows", "macOS"],
      category: ["Access"],
    },
    bestChunks: [
      {
        queryHeading: "Environment",
        candidateHeading: "Environment",
        similarity: 0.39,
        queryText: "Cloud Secure Access 2026.3 with Identity Gateway and SAML-based MFA.",
        candidateText: "Cloud Secure Access with Identity Gateway and external IdP federation.",
      },
    ],
  },
  {
    id: "cmp-device-sync",
    familyId: "family-device-sync",
    leftArticleId: "KB-10401",
    rightArticleId: "KB-10408",
    label: "near_duplicate",
    totalScore: 0.87,
    titleSimilarity: 0.74,
    summarySimilarity: 0.76,
    articleEmbeddingSimilarity: 0.88,
    bestChunkSimilarity: 0.81,
    metadataAgreement: 1,
    rerankScore: 0.84,
    reasons: [
      "high_article_embedding_similarity",
      "high_chunk_similarity",
      "high_summary_similarity",
      "shared_metadata",
    ],
    sharedMetadata: {
      products: ["Endpoint Control"],
      components: ["Provisioning Service"],
      productVersions: ["11.9"],
      deployments: ["Regional"],
      platforms: ["macOS"],
      category: ["Device Management"],
    },
    bestChunks: [
      {
        queryHeading: "Cause",
        candidateHeading: "Workaround",
        similarity: 0.81,
        queryText: "The queue consumer cannot reconcile the bootstrap token if the initial sync happens before the profile trust handshake completes.",
        candidateText: "Force a second policy pull after the trust profile finishes installing and confirm the bootstrap token record is present.",
      },
      {
        queryHeading: "Resolution",
        candidateHeading: "Resolution",
        similarity: 0.79,
        queryText: "Restart the Provisioning Service consumers and trigger a policy refresh after trust enrollment completes.",
        candidateText: "Upgrade the Provisioning Service consumer patch and replay delayed queue items from the regional worker.",
      },
    ],
    assistantExplanation: {
      summary: "Assistive model note: the articles cover the same provisioning-sync failure but may diverge by consumer patch level.",
      whyTheseAreSimilar: [
        "The same product, component, platform, and symptom pattern recur in both articles.",
      ],
      whatDiffers: [
        "One article emphasizes queue replay while the other emphasizes trust-handshake timing.",
      ],
      mergeRecommendationConfidence: 0.73,
      provider: "gemini",
      model: "gemini-3-flash-preview",
      promptVersion: "pair-cluster-explainer-v1",
      generatedAt: "2026-04-28T12:05:00Z",
    },
  },
];

export const mockFamilies: FamilyRecord[] = [
  {
    id: "family-access-mfa",
    representativeArticleId: "KB-10214",
    articleIds: ["KB-10214", "KB-10277"],
    category: "Access",
    product: "Cloud Secure Access",
    reviewState: "pending_review",
    rationale: "Two MFA-loop writeups with matching environment metadata and overlapping resolution steps.",
  },
  {
    id: "family-device-sync",
    representativeArticleId: "KB-10401",
    articleIds: ["KB-10401", "KB-10408"],
    category: "Device Management",
    product: "Endpoint Control",
    reviewState: "split_required",
    rationale: "Queued-sync device articles share the same component but may need a variant split by worker patch level.",
  },
];

export const initialJobLogs: JobLogRecord[] = [
  {
    id: "job-2026-04-28-ingest",
    kind: "ingest",
    status: "completed",
    startedAt: "2026-04-28 09:15",
    summary: "Remote KB ingestion refreshed 238 normalized articles.",
  },
  {
    id: "job-2026-04-28-embeddings",
    kind: "embedding_backfill",
    status: "completed",
    startedAt: "2026-04-28 10:05",
    summary: "Duplicate-comparison embeddings backfilled for 238 articles and 612 chunks.",
  },
  {
    id: "job-2026-04-28-clusters",
    kind: "cluster_materialization",
    status: "completed",
    startedAt: "2026-04-28 11:40",
    summary: "Deterministic family materialization produced 34 clusters and 52 accepted edges.",
  },
];
