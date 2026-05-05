from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.embeddings.providers import EmbeddingProviderError, HttpEmbeddingProvider


@dataclass
class ProviderCall:
    method: str
    url: str
    headers: dict[str, str] | None
    json_body: dict[str, Any] | None


@dataclass
class FakeEmbeddingTransport:
    responses: list[Any]
    calls: list[ProviderCall] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            ProviderCall(
                method=method,
                url=url,
                headers=headers,
                json_body=json_body,
            )
        )
        if not self.responses:
            raise AssertionError("Unexpected embedding request")
        return self.responses.pop(0)


def test_http_embedding_provider_posts_jina_compatible_payload() -> None:
    transport = FakeEmbeddingTransport(
        responses=[
            type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json_body": {
                        "data": [
                            {"embedding": [0.1, 0.2]},
                            {"embedding": [0.3, 0.4]},
                        ]
                    },
                    "text": "",
                },
            )()
        ]
    )
    provider = HttpEmbeddingProvider(
        endpoint_url="http://localhost:5100/v1/embeddings",
        model="jina-embeddings-v3",
        transport=transport,
    )

    vectors = provider.embed_batch(["alpha", "beta"], "retrieval.passage")

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert transport.calls[0].json_body == {
        "model": "jina-embeddings-v3",
        "input": ["alpha", "beta"],
        "task": "retrieval.passage",
        "truncate": True,
    }


def test_http_embedding_provider_retries_transport_failure() -> None:
    transport = FakeEmbeddingTransport(
        responses=[
            RuntimeError("server disconnected"),
            type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json_body": {
                        "data": [
                            {"embedding": [0.1, 0.2]},
                        ]
                    },
                    "text": "",
                },
            )(),
        ]
    )

    def request(*args: Any, **kwargs: Any) -> Any:
        result = FakeEmbeddingTransport.request(transport, *args, **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    transport.request = request  # type: ignore[method-assign]
    provider = HttpEmbeddingProvider(
        endpoint_url="http://localhost:5100/v1/embeddings",
        model="jina-embeddings-v3",
        transport=transport,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )

    vectors = provider.embed_batch(["alpha"], "retrieval.passage")

    assert vectors == [[0.1, 0.2]]
    assert len(transport.calls) == 2


def test_http_embedding_provider_splits_batch_after_retries_exhausted() -> None:
    transport = FakeEmbeddingTransport(responses=[])

    def request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        transport.calls.append(
            ProviderCall(
                method=method,
                url=url,
                headers=headers,
                json_body=json_body,
            )
        )
        payload = json_body or {}
        inputs = payload.get("input") or []
        if len(inputs) > 1:
            raise RuntimeError("server disconnected")
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "json_body": {"data": [{"embedding": [float(len(inputs[0]))]}]},
                "text": "",
            },
        )()

    transport.request = request  # type: ignore[method-assign]
    provider = HttpEmbeddingProvider(
        endpoint_url="http://localhost:5100/v1/embeddings",
        model="jina-embeddings-v3",
        transport=transport,
        max_retries=0,
        retry_backoff_seconds=0.0,
    )

    vectors = provider.embed_batch(["alpha", "beta"], "retrieval.passage")

    assert vectors == [[5.0], [4.0]]
    assert [call.json_body["input"] for call in transport.calls] == [
        ["alpha", "beta"],
        ["alpha"],
        ["beta"],
    ]


def test_http_embedding_provider_tries_fallback_url_after_primary_resolution_failure() -> None:
    transport = FakeEmbeddingTransport(responses=[])

    def request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        transport.calls.append(
            ProviderCall(
                method=method,
                url=url,
                headers=headers,
                json_body=json_body,
            )
        )
        if "local-embeddings" in url:
            raise RuntimeError("[Errno -2] Name or service not known")
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "json_body": {"data": [{"embedding": [0.9, 1.1]}]},
                "text": "",
            },
        )()

    transport.request = request  # type: ignore[method-assign]
    provider = HttpEmbeddingProvider(
        endpoint_url="http://local-embeddings:7997/v1/embeddings",
        fallback_urls=["http://host.docker.internal:7997/v1/embeddings"],
        model="jina-embeddings-v3",
        transport=transport,
        max_retries=0,
        retry_backoff_seconds=0.0,
    )

    vectors = provider.embed_batch(["alpha"], "retrieval.passage")

    assert vectors == [[0.9, 1.1]]
    assert [call.url for call in transport.calls] == [
        "http://local-embeddings:7997/v1/embeddings",
        "http://host.docker.internal:7997/v1/embeddings",
    ]


def test_http_embedding_provider_raises_for_single_item_after_retries() -> None:
    transport = FakeEmbeddingTransport(responses=[])

    def request(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("server disconnected")

    transport.request = request  # type: ignore[method-assign]
    provider = HttpEmbeddingProvider(
        endpoint_url="http://localhost:5100/v1/embeddings",
        model="jina-embeddings-v3",
        transport=transport,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )

    try:
        provider.embed_batch(["alpha"], "retrieval.passage")
    except EmbeddingProviderError as exc:
        assert "attempt 2" in str(exc)
    else:
        raise AssertionError("Expected EmbeddingProviderError")
