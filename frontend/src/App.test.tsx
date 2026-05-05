import { fireEvent, render, screen, within } from "@testing-library/react";

import App from "./App";

const indexStatusResponse = {
  articleIndex: {
    indexName: "kcs-kb-articles-v1",
    totalDocuments: 18397,
    coverage: [
      { fieldName: "title", presentCount: 18397, missingCount: 0, percentage: 100.0 },
      { fieldName: "summary", presentCount: 18379, missingCount: 18, percentage: 99.9 },
      { fieldName: "body_markdown", presentCount: 18397, missingCount: 0, percentage: 100.0 },
      { fieldName: "compare_text", presentCount: 5820, missingCount: 12577, percentage: 31.6 },
      {
        fieldName: "compare_text_hash",
        presentCount: 5820,
        missingCount: 12577,
        percentage: 31.6,
      },
      {
        fieldName: "duplicate_comparison_embedding",
        presentCount: 5820,
        missingCount: 12577,
        percentage: 31.6,
      },
      {
        fieldName: "duplicate_title_embedding",
        presentCount: 5820,
        missingCount: 12577,
        percentage: 31.6,
      },
      {
        fieldName: "duplicate_summary_embedding",
        presentCount: 5802,
        missingCount: 12595,
        percentage: 31.5,
      },
      {
        fieldName: "duplicate_body_embedding",
        presentCount: 5820,
        missingCount: 12577,
        percentage: 31.6,
      },
    ],
  },
  chunkIndex: {
    indexName: "kcs-kb-article-chunks-v1",
    totalDocuments: 3183,
    embeddedDocuments: 3183,
    missingEmbeddings: 0,
    embeddingPercentage: 100.0,
  },
};

describe("workflow-first frontend", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes("/admin/index-status")) {
          return {
            ok: true,
            json: async () => indexStatusResponse,
          };
        }
        return {
          ok: true,
          json: async () => [],
        };
      }),
    );
  });

  it("renders the main workflow pages and lookup landing page", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "kcs-control-plane" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lookup" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review Queue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cluster Explorer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cluster Detail" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Admin" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Find possible duplicates fast" }),
    ).toBeInTheDocument();
  });

  it("renders each main page with accessible headings", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Review Queue" }));
    expect(
      screen.getByRole("heading", {
        name: "Move families through editorial review",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cluster Explorer" }));
    expect(
      screen.getByRole("heading", {
        name: "Browse families without losing the reviewer thread",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cluster Detail" }));
    expect(
      screen.getByRole("heading", { name: "Cluster Detail" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(
      screen.getByRole("heading", {
        name: "Run operational jobs without hijacking the workflow",
      }),
    ).toBeInTheDocument();
  });

  it("supports the review decision flow from queue to compare and back", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Review Queue" }));
    fireEvent.click(screen.getByRole("button", { name: "Open family" }));

    expect(
      screen.getByRole("heading", { name: "Cluster Detail" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Merge candidate/ }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Merge candidate/ }));

    expect(
      screen.getByRole("heading", {
        name: "Move families through editorial review",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "approved family" }));
    expect(screen.getAllByText("approved family").length).toBeGreaterThan(0);
  });

  it("shows lookup evidence and opens the compare workflow", () => {
    render(<App />);

    fireEvent.change(screen.getByLabelText("Search for an article or symptom"), {
      target: { value: "MFA redirect loop" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(screen.getByText("KB-10214 → KB-10277")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Why this pair was surfaced" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open compare view" }));
    expect(
      screen.getByRole("heading", { name: "Cluster Detail" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Secondary LLM note" })).toBeInTheDocument();
  });

  it("runs admin actions and prepends a job log entry", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    fireEvent.click(screen.getByRole("button", { name: /Materialize clusters/ }));

    const logs = screen.getByLabelText("Job logs");
    expect(within(logs).getByText(/Cluster materialization:/)).toBeInTheDocument();
  });

  it("renders index completeness in the admin page", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));

    expect(await screen.findByText("Content and dedupe backfill completeness")).toBeInTheDocument();
    expect(await screen.findByText("18397")).toBeInTheDocument();
    expect(
      await screen.findByText("31.6% with duplicate-comparison vectors."),
    ).toBeInTheDocument();
    expect(await screen.findByText("kcs-kb-article-chunks-v1")).toBeInTheDocument();
  });

  it("starts the full pipeline and renders streamed log output", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/workflows/full-refresh")) {
        return {
          ok: true,
          json: async () => ({
            jobId: "job-123",
            status: "queued",
            reusedExistingJob: false,
          }),
        };
      }
      if (url.includes("/admin/index-status")) {
        return {
          ok: true,
          json: async () => indexStatusResponse,
        };
      }
      return {
        ok: true,
        json: async () => [],
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    class FakeEventSource {
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: (() => void) | null = null;
      url: string;

      constructor(url: string) {
        this.url = url;
        setTimeout(() => {
          this.onmessage?.(
            new MessageEvent("message", {
              data: JSON.stringify({
                type: "log",
                jobId: "job-123",
                status: "running",
                entry: {
                  sequence: 1,
                  level: "info",
                  message: "Starting full KB refresh pipeline.",
                  timestamp: "2026-04-28T12:00:00Z",
                },
              }),
            }),
          );
        }, 0);
      }

      close() {
        return undefined;
      }
    }

    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    fireEvent.click(screen.getByRole("button", { name: "Run full pipeline" }));

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/admin/workflows/full-refresh", {
      method: "POST",
    });

    expect(await screen.findByText("Starting full KB refresh pipeline.")).toBeInTheDocument();
  });

  it("reconnects to an already running pipeline when the admin page opens", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/admin/index-status")) {
        return {
          ok: true,
          json: async () => indexStatusResponse,
        };
      }
      if (url.endsWith("/admin/jobs")) {
        return {
          ok: true,
          json: async () => [
            {
              jobId: "job-999",
              kind: "full_kb_refresh",
              status: "running",
              startedAt: "2026-04-28T12:00:00Z",
              completedAt: null,
              logs: [
                {
                  sequence: 1,
                  level: "info",
                  message: "Step 1/4: Ingesting remote KB articles.",
                  timestamp: "2026-04-28T12:00:00Z",
                },
              ],
            },
          ],
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    class FakeEventSource {
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: (() => void) | null = null;
      url: string;

      constructor(url: string) {
        this.url = url;
        setTimeout(() => {
          this.onmessage?.(
            new MessageEvent("message", {
              data: JSON.stringify({
                type: "log",
                jobId: "job-999",
                status: "running",
                entry: {
                  sequence: 2,
                  level: "info",
                  message: "Step 2/4: Backfilling article embeddings.",
                  timestamp: "2026-04-28T12:01:00Z",
                },
              }),
            }),
          );
        }, 0);
      }

      close() {
        return undefined;
      }
    }

    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));

    expect(await screen.findByText("Step 1/4: Ingesting remote KB articles.")).toBeInTheDocument();
    expect(await screen.findByText("Step 2/4: Backfilling article embeddings.")).toBeInTheDocument();
    expect(screen.getByText("job-999")).toBeInTheDocument();
  });

  it("keeps the main pages semantically accessible", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "Skip to content" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Workflow pages" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search for an article or symptom" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review Queue" }));
    expect(screen.getByRole("toolbar", { name: "Queue status filters" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cluster Explorer" }));
    expect(screen.getByRole("checkbox", { name: "Show visualization panel" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(screen.getByLabelText("Job logs")).toBeInTheDocument();
  });
});
