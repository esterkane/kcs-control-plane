from __future__ import annotations

from app.config import ExplanationRequest
from app.explanations.research import NoopResearchHelper, create_research_helper
from app.explanations.service import ExplanationService


class FakeEsClient:
    def search(self, *, index: str, body: dict):
        return []

    def bulk_index(self, *, index: str, documents):
        return None


class RecordingResearchHelper:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def research(self, query: str) -> str | None:
        self.calls.append(query)
        return "Research"


class FakeProvider:
    def explain(self, context):
        from app.explanations.providers import ExplanationOutput

        return ExplanationOutput.model_validate(
            {
                "summary": "Assistive note",
                "whyTheseAreSimilar": ["Shared metadata"],
                "whatDiffers": ["Scope may differ"],
                "mergeRecommendationConfidence": 0.7,
                "provider": "stub",
                "model": "stub",
                "promptVersion": "pair-cluster-explainer-v1",
                "generatedAt": "2026-04-28T12:00:00Z",
                "researchUsed": False,
            }
        )


def test_create_research_helper_returns_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("DEEPSEARCH_API_KEY", "secret")

    helper = create_research_helper()

    assert isinstance(helper, NoopResearchHelper)


def test_research_helper_not_called_when_request_is_not_opted_in() -> None:
    service = ExplanationService(
        es_client=FakeEsClient(),  # type: ignore[arg-type]
        explanation_provider=FakeProvider(),
        research_helper=RecordingResearchHelper(),
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )

    research_text, research_used = service._research_context(  # type: ignore[attr-defined]
        include_research=False,
        query="vpn loop",
    )

    assert research_text is None
    assert research_used is False


def test_research_helper_called_only_when_opted_in() -> None:
    helper = RecordingResearchHelper()
    service = ExplanationService(
        es_client=FakeEsClient(),  # type: ignore[arg-type]
        explanation_provider=FakeProvider(),
        research_helper=helper,
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )

    research_text, research_used = service._research_context(  # type: ignore[attr-defined]
        include_research=ExplanationRequest(includeResearch=True).include_research,
        query="vpn loop",
    )

    assert research_text == "Research"
    assert research_used is True
    assert helper.calls == ["vpn loop"]
