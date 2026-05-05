from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.elasticsearch.client import ElasticsearchClient, TransportResponse
from app.ingestion.kb import TARGET_INDEX_MAPPING, create_target_index_if_missing, run_full_ingestion


@dataclass
class RecordedCall:
    method: str
    url: str
    headers: dict[str, str] | None
    params: dict[str, Any] | None
    json_body: dict[str, Any] | None
    content: bytes | None


@dataclass
class FakeTransport:
    responses: list[TransportResponse]
    calls: list[RecordedCall] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
    ) -> TransportResponse:
        self.calls.append(
            RecordedCall(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json_body=json_body,
                content=content,
            )
        )
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.responses.pop(0)


def test_run_full_ingestion_uses_pit_and_search_after() -> None:
    source_transport = FakeTransport(
        responses=[
            TransportResponse(status_code=200, json_body={"id": "pit-1"}),
            TransportResponse(
                status_code=200,
                json_body={
                    "pit_id": "pit-2",
                    "hits": {
                        "hits": [
                            {
                                "_id": "remote-1",
                                "sort": [1],
                                "_source": {
                                    "id": "article-1",
                                    "workflow_state": "published",
                                    "title": "Article 1",
                                    "body": "Body 1",
                                },
                            },
                            {
                                "_id": "remote-2-draft",
                                "sort": [2],
                                "_source": {
                                    "id": "article-2",
                                    "workflow_state": "published",
                                    "title": "Draft article",
                                },
                            },
                        ]
                    },
                },
            ),
            TransportResponse(
                status_code=200,
                json_body={
                    "pit_id": "pit-3",
                    "hits": {
                        "hits": [
                            {
                                "_id": "remote-3",
                                "sort": [3],
                                "_source": {
                                    "id": "article-3",
                                    "workflow_state": "published",
                                    "title": "Article 3",
                                    "body": "Body 3",
                                },
                            }
                        ]
                    },
                },
            ),
            TransportResponse(
                status_code=200,
                json_body={
                    "pit_id": "pit-4",
                    "hits": {"hits": []},
                },
            ),
            TransportResponse(status_code=200, json_body={"succeeded": True, "num_freed": 1}),
        ]
    )
    target_transport = FakeTransport(
        responses=[
            TransportResponse(status_code=404),
            TransportResponse(status_code=200, json_body={"acknowledged": True}),
            TransportResponse(status_code=200, json_body={"hits": {"hits": []}}),
            TransportResponse(status_code=200, json_body={"errors": False, "items": []}),
            TransportResponse(status_code=200, json_body={"hits": {"hits": []}}),
            TransportResponse(status_code=200, json_body={"errors": False, "items": []}),
        ]
    )

    result = run_full_ingestion(
        source_client=ElasticsearchClient(base_url="https://source.example.com", api_key="source-key", transport=source_transport),
        target_client=ElasticsearchClient(base_url="http://local-es:9200", transport=target_transport),
        source_index="source-index",
        target_index="kcs-kb-articles-v1",
        batch_size=2,
    )

    assert result.fetched_documents == 3
    assert result.indexed_documents == 2
    assert result.skipped_documents == 1

    first_search_call = source_transport.calls[1]
    second_search_call = source_transport.calls[2]
    assert first_search_call.json_body is not None
    assert second_search_call.json_body is not None
    assert first_search_call.json_body["pit"]["id"] == "pit-1"
    assert "search_after" not in first_search_call.json_body
    assert second_search_call.json_body["pit"]["id"] == "pit-2"
    assert second_search_call.json_body["search_after"] == [2]

    first_lookup_call = target_transport.calls[2]
    first_bulk_call = target_transport.calls[3]
    second_lookup_call = target_transport.calls[4]
    second_bulk_call = target_transport.calls[5]
    assert first_lookup_call.json_body == {"size": 1, "query": {"ids": {"values": ["remote-1"]}}}
    assert second_lookup_call.json_body == {"size": 1, "query": {"ids": {"values": ["remote-3"]}}}
    assert first_bulk_call.content is not None
    assert second_bulk_call.content is not None
    first_bulk_lines = first_bulk_call.content.decode("utf-8").strip().splitlines()
    second_bulk_lines = second_bulk_call.content.decode("utf-8").strip().splitlines()
    assert json.loads(first_bulk_lines[0]) == {"index": {"_index": "kcs-kb-articles-v1", "_id": "remote-1"}}
    assert json.loads(second_bulk_lines[0]) == {"index": {"_index": "kcs-kb-articles-v1", "_id": "remote-3"}}


def test_create_target_index_if_missing_uses_expected_mapping() -> None:
    transport = FakeTransport(
        responses=[
            TransportResponse(status_code=404),
            TransportResponse(status_code=200, json_body={"acknowledged": True}),
        ]
    )
    client = ElasticsearchClient(base_url="http://local-es:9200", transport=transport)

    create_target_index_if_missing(client, index_name="kcs-kb-articles-v1")

    assert transport.calls[0].method == "HEAD"
    assert transport.calls[1].method == "PUT"
    assert transport.calls[1].json_body == TARGET_INDEX_MAPPING


def test_run_full_ingestion_preserves_existing_enrichment_fields() -> None:
    source_transport = FakeTransport(
        responses=[
            TransportResponse(status_code=200, json_body={"id": "pit-1"}),
            TransportResponse(
                status_code=200,
                json_body={
                    "pit_id": "pit-2",
                    "hits": {
                        "hits": [
                            {
                                "_id": "remote-1",
                                "sort": [1],
                                "_source": {
                                    "id": "article-1",
                                    "workflow_state": "published",
                                    "title": "Article 1",
                                    "body": "Body 1 updated",
                                },
                            }
                        ]
                    },
                },
            ),
            TransportResponse(
                status_code=200,
                json_body={
                    "pit_id": "pit-3",
                    "hits": {"hits": []},
                },
            ),
            TransportResponse(status_code=200, json_body={"succeeded": True, "num_freed": 1}),
        ]
    )
    target_transport = FakeTransport(
        responses=[
            TransportResponse(status_code=200),
            TransportResponse(status_code=200, json_body={"acknowledged": True}),
            TransportResponse(
                status_code=200,
                json_body={
                    "hits": {
                        "hits": [
                            {
                                "_id": "remote-1",
                                "_source": {
                                    "article_id": "article-1",
                                    "remote_document_id": "remote-1",
                                    "title": "Article 1",
                                    "summary": None,
                                    "body_markdown": "Body 1",
                                    "symptoms": None,
                                    "category": None,
                                    "visibility_external": None,
                                    "visibility_was_published": None,
                                    "visibility_was_checked_in": None,
                                    "products": [],
                                    "components": [],
                                    "product_versions": [],
                                    "deployments": [],
                                    "platforms": [],
                                    "ai_summary": None,
                                    "ai_subtitle": None,
                                    "ai_questions": [],
                                    "ai_tags": [],
                                    "source_updated_at": None,
                                    "source_index": "source-index",
                                    "compare_text": "# Article 1\n\n## Body\nBody 1",
                                    "compare_text_hash": "abc123",
                                    "duplicate_comparison_embedding": [0.1, 0.2],
                                    "duplicate_title_embedding": [0.2, 0.1],
                                    "duplicate_summary_embedding": [0.3, 0.2],
                                    "duplicate_body_embedding": [0.4, 0.3],
                                },
                            }
                        ]
                    }
                },
            ),
            TransportResponse(status_code=200, json_body={"errors": False, "items": []}),
        ]
    )

    run_full_ingestion(
        source_client=ElasticsearchClient(
            base_url="https://source.example.com",
            api_key="source-key",
            transport=source_transport,
        ),
        target_client=ElasticsearchClient(base_url="http://local-es:9200", transport=target_transport),
        source_index="source-index",
        target_index="kcs-kb-articles-v1",
        batch_size=1,
    )

    put_mapping_call = target_transport.calls[1]
    enrichment_lookup_call = target_transport.calls[2]
    assert enrichment_lookup_call.method == "POST"
    assert put_mapping_call.method == "PUT"
    assert put_mapping_call.url.endswith("/kcs-kb-articles-v1/_mapping")
    assert enrichment_lookup_call.json_body == {
        "size": 1,
        "query": {
            "ids": {
                "values": ["remote-1"],
            }
        },
    }

    bulk_call = target_transport.calls[3]
    assert bulk_call.content is not None
    bulk_lines = bulk_call.content.decode("utf-8").strip().splitlines()
    indexed_document = json.loads(bulk_lines[1])
    assert indexed_document["body_markdown"] == "Body 1 updated"
    assert indexed_document["compare_text"] == "# Article 1\n\n## Body\nBody 1"
    assert indexed_document["compare_text_hash"] == "abc123"
    assert indexed_document["duplicate_comparison_embedding"] == [0.1, 0.2]
    assert indexed_document["duplicate_title_embedding"] == [0.2, 0.1]
    assert indexed_document["duplicate_summary_embedding"] == [0.3, 0.2]
    assert indexed_document["duplicate_body_embedding"] == [0.4, 0.3]
