from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

from app.text_sanitize import sanitize_jsonish

@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class ElasticsearchTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> TransportResponse: ...


class ElasticsearchClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchPage:
    hits: list[dict[str, Any]]
    pit_id: str


class HttpxElasticsearchTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> TransportResponse:
        import httpx

        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            content=content,
            timeout=timeout_seconds or 30.0,
        )
        parsed_json: dict[str, Any] | None
        if response.content:
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None
        else:
            payload = None

        parsed_json = payload if isinstance(payload, dict) else None
        return TransportResponse(
            status_code=response.status_code,
            json_body=parsed_json,
            text=response.text,
        )


class ElasticsearchClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        transport: ElasticsearchTransport | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or HttpxElasticsearchTransport()
        self.request_timeout_seconds = request_timeout_seconds

    def _headers(self, *, ndjson: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        if ndjson:
            headers["Content-Type"] = "application/x-ndjson"
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        expected_statuses: set[int] | None = None,
        ndjson: bool = False,
    ) -> dict[str, Any]:
        response = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(ndjson=ndjson),
            params=params,
            json_body=json_body,
            content=content,
            timeout_seconds=self.request_timeout_seconds,
        )
        allowed_statuses = expected_statuses or {200}
        if response.status_code not in allowed_statuses:
            raise ElasticsearchClientError(
                f"Unexpected Elasticsearch response {response.status_code} for {method} {path}: {response.text}"
            )
        return response.json_body or {}

    def open_point_in_time(self, *, index: str, keep_alive: str) -> str:
        response = self._request_json(
            "POST",
            f"/{index}/_pit",
            params={"keep_alive": keep_alive},
        )
        pit_id = response.get("id")
        if not isinstance(pit_id, str) or not pit_id:
            raise ElasticsearchClientError("PIT open response did not contain an id")
        return pit_id

    def close_point_in_time(self, *, pit_id: str) -> None:
        self._request_json(
            "DELETE",
            "/_pit",
            json_body={"id": pit_id},
            expected_statuses={200},
        )

    def search_with_pit(
        self,
        *,
        pit_id: str,
        keep_alive: str,
        size: int,
        query: dict[str, Any] | None = None,
        source_includes: list[str] | None = None,
        search_after: list[Any] | None = None,
    ) -> SearchPage:
        body: dict[str, Any] = {
            "size": size,
            "sort": [{"_shard_doc": "asc"}],
            "track_total_hits": False,
            "query": query or {"match_all": {}},
            "pit": {"id": pit_id, "keep_alive": keep_alive},
        }
        if source_includes is not None:
            body["_source"] = {"includes": source_includes}
        if search_after is not None:
            body["search_after"] = search_after

        response = self._request_json(
            "POST",
            "/_search",
            json_body=body,
        )
        response_pit_id = response.get("pit_id", pit_id)
        if not isinstance(response_pit_id, str) or not response_pit_id:
            raise ElasticsearchClientError("Search response did not contain a PIT id")
        raw_hits = response.get("hits", {}).get("hits", [])
        if not isinstance(raw_hits, list):
            raise ElasticsearchClientError("Search response hits were not a list")
        return SearchPage(hits=raw_hits, pit_id=response_pit_id)

    def index_exists(self, *, index: str) -> bool:
        response = self.transport.request(
            "HEAD",
            f"{self.base_url}/{index}",
            headers=self._headers(),
            timeout_seconds=self.request_timeout_seconds,
        )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise ElasticsearchClientError(
            f"Unexpected Elasticsearch response {response.status_code} for HEAD /{index}: {response.text}"
        )

    def search(self, *, index: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request_json(
            "POST",
            f"/{index}/_search",
            json_body=body,
            expected_statuses={200},
        )
        raw_hits = response.get("hits", {}).get("hits", [])
        if not isinstance(raw_hits, list):
            raise ElasticsearchClientError(f"Search response hits were not a list: {response}")
        return raw_hits

    def get_documents_by_ids(self, *, index: str, document_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not document_ids:
            return {}
        hits = self.search(
            index=index,
            body={
                "size": len(document_ids),
                "_source": {
                    "includes": [
                        "*",
                        "duplicate_comparison_embedding",
                        "duplicate_title_embedding",
                        "duplicate_summary_embedding",
                        "duplicate_body_embedding",
                    ]
                },
                "query": {
                    "ids": {
                        "values": document_ids,
                    }
                },
            },
        )
        documents: dict[str, dict[str, Any]] = {}
        for hit in hits:
            document_id = hit.get("_id")
            source = hit.get("_source")
            if isinstance(document_id, str) and isinstance(source, dict):
                documents[document_id] = source
        return documents

    def create_index(self, *, index: str, mapping: dict[str, Any]) -> None:
        self._request_json(
            "PUT",
            f"/{index}",
            json_body=mapping,
            expected_statuses={200},
        )

    def delete_index(self, *, index: str) -> None:
        self._request_json(
            "DELETE",
            f"/{index}",
            expected_statuses={200},
        )

    def put_mapping(self, *, index: str, mapping: dict[str, Any]) -> None:
        self._request_json(
            "PUT",
            f"/{index}/_mapping",
            json_body=mapping,
            expected_statuses={200},
        )

    def bulk_index(
        self,
        *,
        index: str,
        documents: list[tuple[str, dict[str, Any]]],
    ) -> None:
        if not documents:
            return

        lines: list[str] = []
        for document_id, document in documents:
            safe_document_id = sanitize_jsonish(document_id)
            safe_document = sanitize_jsonish(document)
            lines.append(json.dumps({"index": {"_index": index, "_id": safe_document_id}}))
            lines.append(json.dumps(safe_document))
        payload = ("\n".join(lines) + "\n").encode("utf-8")

        response = self._request_json(
            "POST",
            "/_bulk",
            content=payload,
            expected_statuses={200},
            ndjson=True,
        )
        if response.get("errors") is True:
            raise ElasticsearchClientError(f"Bulk indexing reported errors: {response}")

    def get_document(self, *, index: str, document_id: str) -> dict[str, Any] | None:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/{index}/_doc/{document_id}",
            headers=self._headers(),
            timeout_seconds=self.request_timeout_seconds,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ElasticsearchClientError(
                f"Unexpected Elasticsearch response {response.status_code} for GET /{index}/_doc/{document_id}: {response.text}"
            )
        payload = response.json_body or {}
        source = payload.get("_source")
        return source if isinstance(source, dict) else None

    def create_document(self, *, index: str, document_id: str, document: dict[str, Any]) -> None:
        self._request_json(
            "PUT",
            f"/{index}/_create/{document_id}",
            json_body=sanitize_jsonish(document),
            expected_statuses={201},
        )

    def delete_document(self, *, index: str, document_id: str) -> None:
        response = self.transport.request(
            "DELETE",
            f"{self.base_url}/{index}/_doc/{document_id}",
            headers=self._headers(),
            timeout_seconds=self.request_timeout_seconds,
        )
        if response.status_code in {200, 404}:
            return
        raise ElasticsearchClientError(
            f"Unexpected Elasticsearch response {response.status_code} for DELETE /{index}/_doc/{document_id}: {response.text}"
        )

    def count_documents(self, *, index: str, query: dict[str, Any]) -> int:
        response = self._request_json(
            "POST",
            f"/{index}/_count",
            json_body={"query": query},
            expected_statuses={200},
        )
        count = response.get("count")
        if not isinstance(count, int):
            raise ElasticsearchClientError(f"Count response did not contain an integer count: {response}")
        return count

    def cardinality_aggregation(
        self,
        *,
        index: str,
        field: str,
        query: dict[str, Any] | None = None,
    ) -> int:
        response = self._request_json(
            "POST",
            f"/{index}/_search",
            json_body={
                "size": 0,
                "query": query or {"match_all": {}},
                "aggs": {
                    "value_count": {
                        "cardinality": {
                            "field": field,
                            "precision_threshold": 40000,
                        }
                    }
                },
            },
            expected_statuses={200},
        )
        value = response.get("aggregations", {}).get("value_count", {}).get("value")
        if not isinstance(value, int | float):
            raise ElasticsearchClientError(f"Cardinality aggregation did not return a numeric value: {response}")
        return int(value)

    def delete_by_query(self, *, index: str, query: dict[str, Any]) -> None:
        self._request_json(
            "POST",
            f"/{index}/_delete_by_query",
            json_body={"query": query},
            expected_statuses={200},
        )

    def get_alias_indices(self, *, alias: str) -> list[str]:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/_alias/{alias}",
            headers=self._headers(),
            timeout_seconds=self.request_timeout_seconds,
        )
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise ElasticsearchClientError(
                f"Unexpected Elasticsearch response {response.status_code} for GET /_alias/{alias}: {response.text}"
            )
        payload = response.json_body or {}
        return sorted(index_name for index_name in payload if isinstance(index_name, str))

    def update_aliases(self, *, actions: list[dict[str, Any]]) -> None:
        self._request_json(
            "POST",
            "/_aliases",
            json_body={"actions": actions},
            expected_statuses={200},
        )

    def iterate_document_batches(
        self,
        *,
        index: str,
        page_size: int = 250,
        source_includes: list[str] | None = None,
    ) -> Iterator[list[tuple[str, dict[str, Any]]]]:
        pit_id = self.open_point_in_time(index=index, keep_alive="1m")
        search_after: list[Any] | None = None
        try:
            while True:
                page = self.search_with_pit(
                    pit_id=pit_id,
                    keep_alive="1m",
                    size=page_size,
                    source_includes=source_includes,
                    search_after=search_after,
                )
                pit_id = page.pit_id
                if not page.hits:
                    break
                documents: list[tuple[str, dict[str, Any]]] = []
                for hit in page.hits:
                    source = hit.get("_source")
                    document_id = hit.get("_id")
                    if isinstance(document_id, str) and isinstance(source, dict):
                        documents.append((document_id, source))
                if documents:
                    yield documents
                last_sort = page.hits[-1].get("sort")
                search_after = last_sort if isinstance(last_sort, list) else None
                if search_after is None:
                    break
        finally:
            self.close_point_in_time(pit_id=pit_id)

    def iterate_documents(
        self,
        *,
        index: str,
        page_size: int = 250,
        source_includes: list[str] | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        documents: list[tuple[str, dict[str, Any]]] = []
        for batch in self.iterate_document_batches(
            index=index,
            page_size=page_size,
            source_includes=source_includes,
        ):
            documents.extend(batch)
        return documents
