import type { ReactNode } from "react";
import type { PageId } from "../types";

type AppShellPage = {
  id: PageId;
  label: string;
};

type AppShellProps = {
  activePageId: PageId;
  children: ReactNode;
  onNavigate: (pageId: PageId) => void;
  pages: AppShellPage[];
};

export function AppShell({
  activePageId,
  children,
  onNavigate,
  pages,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Primary">
        <div className="brand">
          <p className="brand-kicker">KB Control Plane</p>
          <h1>kcs-control-plane</h1>
          <p className="brand-copy">
            Review-first tooling for duplicate detection, family curation, and KB consolidation.
          </p>
        </div>

        <nav className="nav" aria-label="Workflow pages">
          {pages.map((page) => {
            const isActive = page.id === activePageId;
            return (
              <button
                key={page.id}
                type="button"
                className={isActive ? "nav-item nav-item-active" : "nav-item"}
                onClick={() => onNavigate(page.id)}
                aria-current={isActive ? "page" : undefined}
              >
                {page.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="content" id="main-content">
        {children}
      </main>
    </div>
  );
}
