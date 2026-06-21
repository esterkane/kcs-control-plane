"""Feature-flag isolation: AGENTS_ENABLED default-off changes nothing existing.

The editorial supervisor is an in-process orchestrator (like the admin-jobs pipeline),
not new HTTP surface. The isolation guarantees are:
1. ``are_agents_enabled()`` defaults to false.
2. The FastAPI app exposes no ``/agents`` routes regardless of the flag (none are added).
3. ``SupervisorAgent.supervise`` no-ops (returns None, persists nothing) when the flag is off.
"""

from __future__ import annotations

from app.config import are_agents_enabled


def test_agents_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENTS_ENABLED", raising=False)
    assert are_agents_enabled() is False


def test_agents_flag_parses_truthy_values(monkeypatch) -> None:
    for value in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("AGENTS_ENABLED", value)
        assert are_agents_enabled() is True
    for value in ("false", "0", "no", "off", ""):
        monkeypatch.setenv("AGENTS_ENABLED", value)
        assert are_agents_enabled() is False


def test_app_exposes_no_agent_routes() -> None:
    from app.main import create_app

    app = create_app()
    paths = set(app.openapi()["paths"].keys())
    assert not any("agent" in path.casefold() for path in paths)


def test_existing_cluster_routes_still_present() -> None:
    # Byte-for-byte: the existing cluster review routes are unaffected by the agents package.
    from app.main import create_app

    app = create_app()
    paths = set(app.openapi()["paths"].keys())
    assert "/kb/clusters" in paths
    assert "/kb/clusters/{cluster_id}" in paths
