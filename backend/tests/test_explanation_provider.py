from __future__ import annotations

import os

from app.explanations.providers import (
    ExplanationPromptContext,
    GeminiExplanationProvider,
    StubExplanationProvider,
    create_explanation_provider,
)
from app.explanations.research import DeepSearchResearchHelper


class FakeExplanationTransport:
    def request(self, method: str, url: str, *, headers=None, json_body=None):
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "json_body": {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": (
                                            '{"summary":"Pair looks similar.",'
                                            '"whyTheseAreSimilar":["Shared product"],'
                                            '"whatDiffers":["Resolution phrasing differs"],'
                                            '"mergeRecommendationConfidence":0.81,'
                                            '"generatedAt":"2026-04-28T12:00:00Z",'
                                            '"researchUsed":false}'
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
                "text": "",
            },
        )()


class FakeResearchTransport:
    def request(self, method: str, url: str, *, headers=None):
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "json_body": {"answer": "Supplemental research"},
                "text": "",
            },
        )()


def test_stub_explanation_provider_returns_assistive_output() -> None:
    output = StubExplanationProvider().explain(
        ExplanationPromptContext(subjectId="edge-1", subjectType="pair", prompt="Explain")
    )

    assert output.provider == "stub"
    assert output.why_these_are_similar
    assert output.merge_recommendation_confidence > 0


def test_gemini_explanation_provider_parses_json_candidate() -> None:
    provider = GeminiExplanationProvider(
        api_url="https://example.test/generate",
        model="gemini-test",
        api_key="secret",
        transport=FakeExplanationTransport(),
    )

    output = provider.explain(
        ExplanationPromptContext(subjectId="edge-1", subjectType="pair", prompt="Explain")
    )

    assert output.provider == "gemini"
    assert output.model == "gemini-test"
    assert output.summary == "Pair looks similar."
    assert output.why_these_are_similar == ["Shared product"]


def test_create_explanation_provider_honors_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_EXPLANATION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_API_URL", "https://example.test/generate")

    provider = create_explanation_provider(transport=FakeExplanationTransport())
    output = provider.explain(
        ExplanationPromptContext(subjectId="edge-2", subjectType="pair", prompt="Explain")
    )

    assert output.provider == "gemini"


def test_deepsearch_adapter_returns_serialized_json() -> None:
    helper = DeepSearchResearchHelper(
        endpoint_url="https://example.test/v1/compute",
        api_key="secret",
        transport=FakeResearchTransport(),
    )

    result = helper.research("vpn redirect loop")

    assert result is not None
    assert "Supplemental research" in result
