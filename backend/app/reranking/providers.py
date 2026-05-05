from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_jina_api_key, get_jina_reranker_model, get_jina_reranker_url


@dataclass(frozen=True)
class RerankItem:
    index: int
    relevance_score: float


@dataclass(frozen=True)
class RerankResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class RerankTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> RerankResponse: ...


class RerankerProviderError(RuntimeError):
    pass


class RerankerProvider(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[RerankItem]: ...


class HttpxRerankTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> RerankResponse:
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
        return RerankResponse(
            status_code=response.status_code,
            json_body=parsed if isinstance(parsed, dict) else None,
            text=response.text,
        )


class StubRerankerProvider:
    def rerank(self, query: str, documents: list[str]) -> list[RerankItem]:
        return [RerankItem(index=index, relevance_score=1.0 / (index + 1)) for index, _ in enumerate(documents)]


class JinaRerankerProvider:
    def __init__(
        self,
        *,
        endpoint_url: str,
        model: str,
        api_key: str,
        transport: RerankTransport | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model = model
        self.api_key = api_key
        self.transport = transport or HttpxRerankTransport()

    def rerank(self, query: str, documents: list[str]) -> list[RerankItem]:
        if not documents:
            return []

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self.transport.request(
            "POST",
            self.endpoint_url,
            headers=headers,
            json_body={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
                "return_documents": False,
            },
        )
        if response.status_code != 200:
            raise RerankerProviderError(
                f"Unexpected reranker response {response.status_code}: {response.text}"
            )

        results = response.json_body.get("results") if response.json_body else None
        if not isinstance(results, list):
            raise RerankerProviderError(f"Reranker response missing results: {response.json_body}")

        reranked: list[RerankItem] = []
        for result in results:
            if not isinstance(result, dict):
                raise RerankerProviderError(f"Invalid reranker result: {result}")
            index = result.get("index")
            score = result.get("relevance_score")
            if not isinstance(index, int) or not isinstance(score, int | float):
                raise RerankerProviderError(f"Invalid reranker result item: {result}")
            reranked.append(RerankItem(index=index, relevance_score=float(score)))
        return reranked


def create_reranker_provider(*, transport: RerankTransport | None = None) -> RerankerProvider:
    import os

    provider_name = os.getenv("RERANKER_PROVIDER", "stub").casefold()
    if provider_name == "jina":
        return JinaRerankerProvider(
            endpoint_url=get_jina_reranker_url(),
            model=get_jina_reranker_model(),
            api_key=get_jina_api_key(),
            transport=transport,
        )
    return StubRerankerProvider()
