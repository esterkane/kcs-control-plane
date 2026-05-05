from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import (
    get_duplicate_embedding_provider,
    get_duplicate_embedding_task,
    get_jina_api_key,
    get_jina_embedding_model,
    get_jina_embedding_url,
    get_local_embedding_fallback_urls,
    get_local_embedding_model,
    get_local_embedding_url,
)


@dataclass(frozen=True)
class EmbeddingResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class EmbeddingTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> EmbeddingResponse: ...


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    def embed_batch(self, texts: list[str], task: str) -> list[list[float]]: ...


class HttpxEmbeddingTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> EmbeddingResponse:
        import httpx

        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            timeout=300.0,
        )
        payload: dict[str, Any] | None
        try:
            parsed = response.json()
        except json.JSONDecodeError:
            parsed = None
        payload = parsed if isinstance(parsed, dict) else None
        return EmbeddingResponse(
            status_code=response.status_code,
            json_body=payload,
            text=response.text,
        )


class HttpEmbeddingProvider:
    def __init__(
        self,
        *,
        endpoint_url: str,
        model: str,
        api_key: str = "",
        transport: EmbeddingTransport | None = None,
        fallback_urls: list[str] | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.endpoint_urls = [endpoint_url]
        for fallback_url in fallback_urls or []:
            if fallback_url and fallback_url not in self.endpoint_urls:
                self.endpoint_urls.append(fallback_url)
        self.model = model
        self.api_key = api_key
        self.transport = transport or HttpxEmbeddingTransport()
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def embed_batch(self, texts: list[str], task: str) -> list[list[float]]:
        if not texts:
            return []

        if len(texts) == 1:
            return self._embed_batch_once(texts, task)

        try:
            return self._embed_batch_once(texts, task)
        except EmbeddingProviderError:
            midpoint = max(1, len(texts) // 2)
            left = self.embed_batch(texts[:midpoint], task)
            right = self.embed_batch(texts[midpoint:], task)
            return left + right

    def _embed_batch_once(self, texts: list[str], task: str) -> list[list[float]]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            should_retry = False
            for endpoint_url in self.endpoint_urls:
                try:
                    response = self.transport.request(
                        "POST",
                        endpoint_url,
                        headers=headers,
                        json_body={
                            "model": self.model,
                            "input": texts,
                            "task": task,
                            "truncate": True,
                        },
                    )
                except Exception as exc:
                    last_error = EmbeddingProviderError(
                        f"Embedding request failed on attempt {attempt + 1} via {endpoint_url}: {exc}"
                    )
                    should_retry = True
                    continue

                if response.status_code == 200:
                    return self._parse_embedding_response(response)

                last_error = EmbeddingProviderError(
                    f"Unexpected embedding response {response.status_code} from {endpoint_url}: {response.text}"
                )
                if not self._should_retry_status(response.status_code):
                    raise last_error
                should_retry = True

            if not should_retry or attempt >= self.max_retries:
                if last_error is None:
                    raise EmbeddingProviderError("Embedding request failed without a response.")
                raise last_error
            self._sleep_before_retry(attempt)

        if last_error is None:
            raise EmbeddingProviderError("Embedding request failed without a response.")
        raise last_error

    def _parse_embedding_response(self, response: EmbeddingResponse) -> list[list[float]]:
        data = response.json_body.get("data") if response.json_body else None
        if not isinstance(data, list):
            raise EmbeddingProviderError(f"Embedding response missing data list: {response.json_body}")

        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise EmbeddingProviderError(f"Invalid embedding item: {item}")
            vectors.append([float(value) for value in item["embedding"]])
        return vectors

    def _should_retry_status(self, status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * (attempt + 1))


def create_duplicate_embedding_provider(
    *,
    transport: EmbeddingTransport | None = None,
) -> tuple[EmbeddingProvider, str]:
    provider_name = get_duplicate_embedding_provider().casefold()
    task = get_duplicate_embedding_task()
    if provider_name == "jina":
        return (
            HttpEmbeddingProvider(
                endpoint_url=get_jina_embedding_url(),
                model=get_jina_embedding_model(),
                api_key=get_jina_api_key(),
                transport=transport,
            ),
            task,
        )
    if provider_name == "local":
        return (
            HttpEmbeddingProvider(
                endpoint_url=get_local_embedding_url(),
                model=get_local_embedding_model(),
                transport=transport,
                fallback_urls=get_local_embedding_fallback_urls(),
            ),
            task,
        )
    raise EmbeddingProviderError(f"Unsupported duplicate embedding provider: {provider_name}")
