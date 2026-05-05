from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.config import (
    get_gemini_api_key,
    get_gemini_api_url,
    get_gemini_model,
    get_llm_explanation_provider,
)


PROMPT_VERSION = "pair-cluster-explainer-v1"


class ExplanationPromptContext(BaseModel):
    subject_id: str = Field(alias="subjectId")
    subject_type: str = Field(alias="subjectType")
    prompt: str

    model_config = {"populate_by_name": True}


class ExplanationOutput(BaseModel):
    summary: str
    why_these_are_similar: list[str] = Field(alias="whyTheseAreSimilar")
    what_differs: list[str] = Field(alias="whatDiffers")
    merge_recommendation_confidence: float = Field(alias="mergeRecommendationConfidence")
    provider: str
    model: str
    prompt_version: str = Field(alias="promptVersion")
    generated_at: str = Field(alias="generatedAt")
    research_used: bool = Field(default=False, alias="researchUsed")

    model_config = {"populate_by_name": True}


@dataclass(frozen=True)
class ExplanationResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class ExplanationTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ExplanationResponse: ...


class ExplanationProviderError(RuntimeError):
    pass


class ExplanationProvider(Protocol):
    def explain(self, context: ExplanationPromptContext) -> ExplanationOutput: ...


class HttpxExplanationTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ExplanationResponse:
        import httpx

        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            timeout=30.0,
        )
        try:
            parsed = response.json()
        except json.JSONDecodeError:
            parsed = None
        return ExplanationResponse(
            status_code=response.status_code,
            json_body=parsed if isinstance(parsed, dict) else None,
            text=response.text,
        )


class StubExplanationProvider:
    def explain(self, context: ExplanationPromptContext) -> ExplanationOutput:
        return ExplanationOutput(
            summary=f"Assistive explanation for {context.subject_type} {context.subject_id}.",
            whyTheseAreSimilar=[
                "Deterministic signals show overlapping compare text and metadata.",
                "Similarity evidence contains matching chunks and aligned product context.",
            ],
            whatDiffers=[
                "Reviewers should still verify whether the operational scope is identical.",
            ],
            mergeRecommendationConfidence=0.72,
            provider="stub",
            model="stub",
            promptVersion=PROMPT_VERSION,
            generatedAt="2026-04-28T12:00:00Z",
            researchUsed=False,
        )


class GeminiExplanationProvider:
    def __init__(
        self,
        *,
        api_url: str,
        model: str,
        api_key: str,
        transport: ExplanationTransport | None = None,
    ) -> None:
        self.api_url = api_url
        self.model = model
        self.api_key = api_key
        self.transport = transport or HttpxExplanationTransport()

    def explain(self, context: ExplanationPromptContext) -> ExplanationOutput:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        response = self.transport.request(
            "POST",
            self.api_url,
            headers=headers,
            json_body={
                "contents": [
                    {
                        "parts": [
                            {
                                "text": context.prompt,
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                },
            },
        )
        if response.status_code != 200:
            raise ExplanationProviderError(
                f"Unexpected Gemini response {response.status_code}: {response.text}"
            )
        candidate_text = (
            response.json_body.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text")
            if response.json_body
            else None
        )
        if not isinstance(candidate_text, str):
            raise ExplanationProviderError(f"Gemini response missing text candidate: {response.json_body}")
        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            raise ExplanationProviderError(f"Gemini response was not valid JSON: {candidate_text}") from exc
        if not isinstance(parsed, dict):
            raise ExplanationProviderError(f"Gemini response JSON was not an object: {parsed}")
        return ExplanationOutput.model_validate(
            {
                **parsed,
                "provider": "gemini",
                "model": self.model,
                "promptVersion": PROMPT_VERSION,
            }
        )


def create_explanation_provider(
    *,
    transport: ExplanationTransport | None = None,
) -> ExplanationProvider:
    provider_name = get_llm_explanation_provider().casefold()
    if provider_name == "gemini":
        return GeminiExplanationProvider(
            api_url=get_gemini_api_url(),
            model=get_gemini_model(),
            api_key=get_gemini_api_key(),
            transport=transport,
        )
    return StubExplanationProvider()
