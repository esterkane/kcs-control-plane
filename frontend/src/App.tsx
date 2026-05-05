import { useEffect, useReducer, useRef, useState } from "react";

import "./App.css";
import { AppShell } from "./components/AppShell";
import { initialJobLogs, mockArticles, mockComparisons, mockFamilies } from "./data/workflowData";
import { AdminPage } from "./pages/AdminPage";
import { ClusterDetailPage } from "./pages/ClusterDetailPage";
import { ClusterExplorerPage } from "./pages/ClusterExplorerPage";
import { LookupPage } from "./pages/LookupPage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { reduceWorkflowState } from "./workflow";
import type {
  AdminIndexStatus,
  AdminPipelineRun,
  LiveClusterDetail,
  LiveClusterListResponse,
  PageId,
  RemoteAnalysisStatus,
} from "./types";

type PageDefinition = {
  id: PageId;
  label: string;
};

const pages: PageDefinition[] = [
  { id: "lookup", label: "Lookup" },
  { id: "reviewQueue", label: "Review Queue" },
  { id: "clusterExplorer", label: "Cluster Explorer" },
  { id: "clusterDetail", label: "Cluster Detail" },
  { id: "admin", label: "Admin" },
];

const initialState = {
  articles: mockArticles,
  comparisons: mockComparisons,
  families: mockFamilies,
  selectedComparisonId: "cmp-lookup-vpn-loop",
  activePageId: "lookup" as const,
  jobLogs: initialJobLogs,
};

const activePipelineJobStorageKey = "kcs-control-plane.activePipelineJobId";

type PipelineJobResponse = {
  jobId: string;
  kind: string;
  status: AdminPipelineRun["status"];
  startedAt: string;
  completedAt: string | null;
  logs: AdminPipelineRun["logs"];
};

type PipelineStreamMessage =
  | {
      type: "log";
      jobId: string;
      status: AdminPipelineRun["status"];
      entry: AdminPipelineRun["logs"][number];
    }
  | {
      type: "status";
      jobId: string;
      status: AdminPipelineRun["status"];
      completedAt?: string | null;
    };

function isLiveClusterListResponse(payload: unknown): payload is LiveClusterListResponse {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const candidate = payload as Record<string, unknown>;
  return typeof candidate.count === "number" && Array.isArray(candidate.items);
}

function isAdminIndexStatus(payload: unknown): payload is AdminIndexStatus {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const candidate = payload as Record<string, unknown>;
  return typeof candidate.articleIndex === "object" && candidate.articleIndex !== null
    && typeof candidate.chunkIndex === "object" && candidate.chunkIndex !== null;
}

function isRemoteAnalysisStatus(payload: unknown): payload is RemoteAnalysisStatus {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const candidate = payload as Record<string, unknown>;
  return typeof candidate.enabled === "boolean"
    && typeof candidate.aliases === "object"
    && candidate.aliases !== null;
}

function mergePipelineLogs(
  currentLogs: AdminPipelineRun["logs"],
  nextEntries: AdminPipelineRun["logs"],
): AdminPipelineRun["logs"] {
  const entriesBySequence = new Map<number, AdminPipelineRun["logs"][number]>();
  for (const entry of currentLogs) {
    entriesBySequence.set(entry.sequence, entry);
  }
  for (const entry of nextEntries) {
    entriesBySequence.set(entry.sequence, entry);
  }
  return [...entriesBySequence.values()].sort((left, right) => left.sequence - right.sequence);
}

export default function App() {
  const [state, dispatch] = useReducer(reduceWorkflowState, initialState);
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  const [activeRun, setActiveRun] = useState<AdminPipelineRun | null>(null);
  const [indexStatus, setIndexStatus] = useState<AdminIndexStatus | null>(null);
  const [remoteAnalysisStatus, setRemoteAnalysisStatus] = useState<RemoteAnalysisStatus | null>(null);
  const [isStartingPipeline, setIsStartingPipeline] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [indexStatusError, setIndexStatusError] = useState<string | null>(null);
  const [remoteAnalysisStatusError, setRemoteAnalysisStatusError] = useState<string | null>(null);
  const [liveClusters, setLiveClusters] = useState<LiveClusterListResponse["items"] | null>(null);
  const [liveClusterCount, setLiveClusterCount] = useState(0);
  const [liveClustersError, setLiveClustersError] = useState<string | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [liveClusterDetail, setLiveClusterDetail] = useState<LiveClusterDetail | null>(null);
  const [isLoadingLiveClusterDetail, setIsLoadingLiveClusterDetail] = useState(false);
  const [liveClusterDetailError, setLiveClusterDetailError] = useState<string | null>(null);
  const [isUpdatingLiveClusterDecision, setIsUpdatingLiveClusterDecision] = useState(false);
  const [liveClusterDecisionError, setLiveClusterDecisionError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const hasAttemptedReconnectRef = useRef(false);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (state.activePageId !== "admin") {
      hasAttemptedReconnectRef.current = false;
    }
  }, [state.activePageId]);

  function connectToJobStream(initialRun: AdminPipelineRun): void {
    window.localStorage.setItem(activePipelineJobStorageKey, initialRun.jobId);
    setActiveRun(initialRun);
    eventSourceRef.current?.close();

    const source = new EventSource(`${apiBaseUrl}/admin/jobs/${initialRun.jobId}/stream`);
    eventSourceRef.current = source;

    source.onmessage = (event) => {
      const message = JSON.parse(event.data) as PipelineStreamMessage;

      if (message.type === "log") {
        setActiveRun((current) => {
          const base = current ?? initialRun;
          return {
            jobId: message.jobId,
            status: message.status,
            logs: mergePipelineLogs(base.logs, [message.entry]),
          };
        });
        return;
      }

      setActiveRun((current) =>
        current
          ? {
              ...current,
              status: message.status,
            }
          : current,
      );
      if (message.status === "succeeded" || message.status === "failed") {
        window.localStorage.removeItem(activePipelineJobStorageKey);
        source.close();
      }
    };

    source.onerror = () => {
      setPipelineError("Lost connection to the live pipeline log stream.");
      source.close();
    };
  }

  useEffect(() => {
    if (state.activePageId !== "admin" || hasAttemptedReconnectRef.current || activeRun !== null) {
      return;
    }

    hasAttemptedReconnectRef.current = true;
    void (async () => {
      try {
        const rememberedJobId = window.localStorage.getItem(activePipelineJobStorageKey);
        if (rememberedJobId) {
          const rememberedResponse = await fetch(`${apiBaseUrl}/admin/jobs/${rememberedJobId}`);
          if (rememberedResponse.ok) {
            const rememberedJob = (await rememberedResponse.json()) as PipelineJobResponse;
            const rememberedRun: AdminPipelineRun = {
              jobId: rememberedJob.jobId,
              status: rememberedJob.status,
              logs: rememberedJob.logs,
            };
            if (rememberedJob.status === "queued" || rememberedJob.status === "running") {
              connectToJobStream(rememberedRun);
              return;
            }
            window.localStorage.removeItem(activePipelineJobStorageKey);
            setActiveRun(rememberedRun);
            return;
          }
          window.localStorage.removeItem(activePipelineJobStorageKey);
        }

        const response = await fetch(`${apiBaseUrl}/admin/jobs`);
        if (!response.ok) {
          return;
        }
        const jobs = (await response.json()) as PipelineJobResponse[];
        const latestJob =
          jobs.find((job) => job.status === "queued" || job.status === "running") ?? jobs[0];
        if (latestJob === undefined) {
          return;
        }
        const latestRun = {
          jobId: latestJob.jobId,
          status: latestJob.status,
          logs: latestJob.logs,
        };
        if (latestJob.status === "queued" || latestJob.status === "running") {
          connectToJobStream(latestRun);
          return;
        }
        setActiveRun(latestRun);
      } catch {
        return;
      }
    })();
  }, [activeRun, apiBaseUrl, state.activePageId]);

  useEffect(() => {
    if (
      state.activePageId !== "clusterExplorer"
      && state.activePageId !== "reviewQueue"
      && state.activePageId !== "clusterDetail"
    ) {
      return;
    }

    let cancelled = false;

    async function loadClusters(): Promise<void> {
      try {
        const response = await fetch(`${apiBaseUrl}/kb/clusters?size=100`);
        if (!response.ok) {
          throw new Error(`Failed to load clusters: ${response.status}`);
        }
        const payload = await response.json();
        if (!isLiveClusterListResponse(payload)) {
          throw new Error("Cluster list response was malformed.");
        }
        if (cancelled) {
          return;
        }
        setLiveClusters(payload.items);
        setLiveClusterCount(payload.count);
        setLiveClustersError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLiveClustersError(
          error instanceof Error ? error.message : "Failed to load cluster list.",
        );
      }
    }

    void loadClusters();
    const intervalId = window.setInterval(() => {
      void loadClusters();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [apiBaseUrl, state.activePageId]);

  useEffect(() => {
    if (state.activePageId !== "clusterDetail" || selectedClusterId === null) {
      return;
    }

    let cancelled = false;

    async function loadClusterDetail(): Promise<void> {
      setIsLoadingLiveClusterDetail(true);
      try {
        const response = await fetch(`${apiBaseUrl}/kb/clusters/${selectedClusterId}`);
        if (!response.ok) {
          throw new Error(`Failed to load cluster detail: ${response.status}`);
        }
        const payload = (await response.json()) as LiveClusterDetail;
        if (cancelled) {
          return;
        }
        setLiveClusterDetail(payload);
        setLiveClusterDetailError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLiveClusterDetail(null);
        setLiveClusterDetailError(
          error instanceof Error ? error.message : "Failed to load cluster detail.",
        );
      } finally {
        if (!cancelled) {
          setIsLoadingLiveClusterDetail(false);
        }
      }
    }

    void loadClusterDetail();

    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, selectedClusterId, state.activePageId]);

  useEffect(() => {
    if (state.activePageId !== "admin") {
      return;
    }

    let cancelled = false;

    async function loadIndexStatus(): Promise<void> {
      try {
        const response = await fetch(`${apiBaseUrl}/admin/index-status`);
        if (!response.ok) {
          throw new Error(`Failed to load index status: ${response.status}`);
        }
        const payload = await response.json();
        if (!isAdminIndexStatus(payload)) {
          throw new Error("Index status response was malformed.");
        }
        if (cancelled) {
          return;
        }
        setIndexStatus(payload);
        setIndexStatusError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setIndexStatusError(
          error instanceof Error ? error.message : "Failed to load index status.",
        );
      }
    }

    async function loadRemoteAnalysisStatus(): Promise<void> {
      try {
        const response = await fetch(`${apiBaseUrl}/admin/remote-analysis-status`);
        if (!response.ok) {
          throw new Error(`Failed to load remote analysis status: ${response.status}`);
        }
        const payload = await response.json();
        if (!isRemoteAnalysisStatus(payload)) {
          throw new Error("Remote analysis status response was malformed.");
        }
        if (cancelled) {
          return;
        }
        setRemoteAnalysisStatus(payload);
        setRemoteAnalysisStatusError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setRemoteAnalysisStatusError(
          error instanceof Error ? error.message : "Failed to load remote analysis status.",
        );
      }
    }

    void loadIndexStatus();
    void loadRemoteAnalysisStatus();
    const intervalId = window.setInterval(() => {
      void loadIndexStatus();
      void loadRemoteAnalysisStatus();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [apiBaseUrl, state.activePageId]);

  async function handleRunFullPipeline(): Promise<void> {
    await handleStartAdminWorkflow("/admin/workflows/full-refresh", "Failed to start pipeline.");
  }

  async function handleStartAdminWorkflow(path: string, fallbackError: string): Promise<void> {
    setIsStartingPipeline(true);
    setPipelineError(null);
    try {
      const response = await fetch(`${apiBaseUrl}${path}`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`Failed to start workflow: ${response.status}`);
      }
      const payload = (await response.json()) as {
        jobId: string;
        status: "queued" | "running" | "succeeded" | "failed";
      };
      const initialRun: AdminPipelineRun = {
        jobId: payload.jobId,
        status: payload.status,
        logs: [],
      };
      connectToJobStream(initialRun);
    } catch (error) {
      setPipelineError(error instanceof Error ? error.message : fallbackError);
    } finally {
      setIsStartingPipeline(false);
    }
  }

  function handleOpenComparison(comparisonId: string): void {
    setSelectedClusterId(null);
    setLiveClusterDetail(null);
    setLiveClusterDetailError(null);
    dispatch({ type: "openComparison", comparisonId });
  }

  function handleOpenCluster(clusterId: string): void {
    setSelectedClusterId(clusterId);
    setLiveClusterDecisionError(null);
    dispatch({ type: "navigate", pageId: "clusterDetail" });
  }

  async function handleLiveClusterDecision(reviewState: string): Promise<void> {
    if (selectedClusterId === null) {
      return;
    }
    setIsUpdatingLiveClusterDecision(true);
    setLiveClusterDecisionError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/kb/clusters/${selectedClusterId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewState }),
      });
      if (!response.ok) {
        throw new Error(`Failed to update cluster: ${response.status}`);
      }
      const payload = (await response.json()) as LiveClusterDetail;
      setLiveClusterDetail(payload);
      setLiveClusters((current) =>
        current
          ? current.map((cluster) =>
              cluster.clusterId === payload.clusterId
                ? {
                    ...cluster,
                    reviewState: payload.reviewState,
                  }
                : cluster,
            )
          : current,
      );
    } catch (error) {
      setLiveClusterDecisionError(
        error instanceof Error ? error.message : "Failed to update cluster review state.",
      );
    } finally {
      setIsUpdatingLiveClusterDecision(false);
    }
  }

  const activePageContent = (() => {
    switch (state.activePageId) {
      case "lookup":
        return (
          <LookupPage
            apiBaseUrl={apiBaseUrl}
            articles={state.articles}
            comparisons={state.comparisons}
            families={state.families}
            onOpenComparison={handleOpenComparison}
            onOpenCluster={handleOpenCluster}
          />
        );
      case "reviewQueue":
        return (
          <ReviewQueuePage
            articles={state.articles}
            comparisons={state.comparisons}
            families={state.families}
            onOpenComparison={handleOpenComparison}
            onDecision={(familyId, decision) =>
              dispatch({ type: "applyDecision", familyId, decision })
            }
            liveClusters={liveClusters}
            liveClusterCount={liveClusterCount}
            liveClustersError={liveClustersError}
            onOpenCluster={handleOpenCluster}
          />
        );
      case "clusterExplorer":
        return (
          <ClusterExplorerPage
            articles={state.articles}
            comparisons={state.comparisons}
            families={state.families}
            onOpenComparison={handleOpenComparison}
            liveClusters={liveClusters}
            liveClusterCount={liveClusterCount}
            liveClustersError={liveClustersError}
            onOpenCluster={handleOpenCluster}
          />
        );
      case "clusterDetail":
        return (
          <ClusterDetailPage
            articles={state.articles}
            comparisons={state.comparisons}
            families={state.families}
            selectedComparisonId={state.selectedComparisonId}
            selectedClusterId={selectedClusterId}
            liveClusterDetail={liveClusterDetail}
            isLoadingLiveClusterDetail={isLoadingLiveClusterDetail}
            liveClusterDetailError={liveClusterDetailError}
            isUpdatingLiveClusterDecision={isUpdatingLiveClusterDecision}
            liveClusterDecisionError={liveClusterDecisionError}
            onLiveClusterDecision={(reviewState) => {
              void handleLiveClusterDecision(reviewState);
            }}
            onDecision={(familyId, decision) =>
              dispatch({ type: "applyDecision", familyId, decision })
            }
          />
        );
      case "admin":
        return (
          <AdminPage
            apiBaseUrl={apiBaseUrl}
            activeRun={activeRun}
            indexStatus={indexStatus}
            indexStatusError={indexStatusError}
            remoteAnalysisStatus={remoteAnalysisStatus}
            remoteAnalysisStatusError={remoteAnalysisStatusError}
            isStartingPipeline={isStartingPipeline}
            jobLogs={state.jobLogs}
            pipelineError={pipelineError}
            onRunFullPipeline={() => {
              void handleRunFullPipeline();
            }}
            onRunJob={(jobKind) => dispatch({ type: "runJob", jobKind })}
            onPullRemoteAnalysis={() => {
              void handleStartAdminWorkflow(
                "/admin/workflows/pull-remote-analysis",
                "Failed to start remote analysis pull.",
              );
            }}
            onPublishRemoteAnalysis={() => {
              void handleStartAdminWorkflow(
                "/admin/workflows/publish-remote-analysis",
                "Failed to start remote analysis publish.",
              );
            }}
          />
        );
      default:
        return null;
    }
  })();

  return (
    <AppShell
      activePageId={state.activePageId}
      onNavigate={(pageId) => dispatch({ type: "navigate", pageId })}
      pages={pages}
    >
      {activePageContent}
    </AppShell>
  );
}
