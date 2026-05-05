from __future__ import annotations

from app.elasticsearch.client import ElasticsearchClientError
from app.sync.analysis import RemoteAnalysisSyncService


class FakeElasticsearchClient:
    def __init__(self) -> None:
        self.indices: dict[str, dict[str, object]] = {}
        self.aliases: dict[str, list[str]] = {}
        self.deleted_indices: list[str] = []
        self.updated_alias_actions: list[dict[str, object]] = []

    def index_exists(self, *, index: str) -> bool:
        return index in self.indices or index in self.aliases

    def delete_index(self, *, index: str) -> None:
        self.indices.pop(index, None)
        self.deleted_indices.append(index)

    def create_index(self, *, index: str, mapping: dict[str, object]) -> None:
        self.indices[index] = {"mapping": mapping, "documents": []}

    def put_mapping(self, *, index: str, mapping: dict[str, object]) -> None:
        self.indices.setdefault(index, {"mapping": {}, "documents": []})
        self.indices[index]["mapping"] = mapping

    def count_documents(self, *, index: str, query: dict[str, object]) -> int:
        resolved_index = self.aliases[index][0] if index in self.aliases and self.aliases[index] else index
        documents = self.indices.get(resolved_index, {}).get("documents", [])
        return len(documents) if isinstance(documents, list) else 0

    def search(self, *, index: str, body: dict[str, object]) -> list[dict[str, object]]:
        resolved_index = self.aliases[index][0] if index in self.aliases and self.aliases[index] else index
        documents = self.indices.get(resolved_index, {}).get("documents", [])
        if not isinstance(documents, list):
            return []
        hits = [{"_id": document_id, "_source": source} for document_id, source in documents]
        query = body.get("query")
        if isinstance(query, dict):
            ids_query = query.get("ids")
            if isinstance(ids_query, dict):
                values = ids_query.get("values")
                if isinstance(values, list):
                    allowed = {value for value in values if isinstance(value, str)}
                    hits = [hit for hit in hits if hit["_id"] in allowed]
            bool_query = query.get("bool")
            if isinstance(bool_query, dict):
                must = bool_query.get("must")
                must_not = bool_query.get("must_not")
                if isinstance(must, list):
                    for clause in must:
                        if isinstance(clause, dict) and isinstance(clause.get("term"), dict):
                            term = clause["term"]
                            for key, value in term.items():
                                hits = [hit for hit in hits if hit["_source"].get(key) == value]
                if isinstance(must_not, list):
                    for clause in must_not:
                        if isinstance(clause, dict) and isinstance(clause.get("ids"), dict):
                            values = clause["ids"].get("values")
                            if isinstance(values, list):
                                excluded = {value for value in values if isinstance(value, str)}
                                hits = [hit for hit in hits if hit["_id"] not in excluded]
        sort_spec = body.get("sort")
        if isinstance(sort_spec, list) and sort_spec:
            first_sort = sort_spec[0]
            if isinstance(first_sort, dict) and "published_at" in first_sort:
                direction = first_sort["published_at"]
                reverse = direction == "desc"
                hits.sort(key=lambda hit: str(hit["_source"].get("published_at", "")), reverse=reverse)
        size = body.get("size")
        if isinstance(size, int):
            hits = hits[:size]
        return hits

    def iterate_documents(self, *, index: str, page_size: int, source_includes: list[str]) -> list[tuple[str, dict[str, object]]]:
        resolved_index = self.aliases[index][0] if index in self.aliases and self.aliases[index] else index
        documents = self.indices.get(resolved_index, {}).get("documents", [])
        return list(documents) if isinstance(documents, list) else []

    def iterate_document_batches(
        self,
        *,
        index: str,
        page_size: int,
        source_includes: list[str],
    ):
        documents = self.iterate_documents(index=index, page_size=page_size, source_includes=source_includes)
        for offset in range(0, len(documents), page_size):
            yield documents[offset : offset + page_size]

    def bulk_index(self, *, index: str, documents: list[tuple[str, dict[str, object]]]) -> None:
        self.indices.setdefault(index, {"mapping": {}, "documents": []})
        stored = self.indices[index]["documents"]
        assert isinstance(stored, list)
        existing_by_id = {document_id: idx for idx, (document_id, _document) in enumerate(stored)}
        for document_id, document in documents:
            if document_id in existing_by_id:
                stored[existing_by_id[document_id]] = (document_id, document)
            else:
                existing_by_id[document_id] = len(stored)
                stored.append((document_id, document))

    def get_alias_indices(self, *, alias: str) -> list[str]:
        return list(self.aliases.get(alias, []))

    def update_aliases(self, *, actions: list[dict[str, object]]) -> None:
        self.updated_alias_actions = actions
        for action in actions:
            if "remove" in action:
                payload = action["remove"]
                assert isinstance(payload, dict)
                alias = payload["alias"]
                index = payload["index"]
                assert isinstance(alias, str)
                assert isinstance(index, str)
                self.aliases[alias] = [current for current in self.aliases.get(alias, []) if current != index]
            elif "add" in action:
                payload = action["add"]
                assert isinstance(payload, dict)
                alias = payload["alias"]
                index = payload["index"]
                assert isinstance(alias, str)
                assert isinstance(index, str)
                self.aliases.setdefault(alias, [])
                if index not in self.aliases[alias]:
                    self.aliases[alias].append(index)

    def get_document(self, *, index: str, document_id: str) -> dict[str, object] | None:
        documents = self.indices.get(index, {}).get("documents", [])
        if not isinstance(documents, list):
            return None
        for current_id, source in documents:
            if current_id == document_id:
                return dict(source)
        return None

    def create_document(self, *, index: str, document_id: str, document: dict[str, object]) -> None:
        if self.get_document(index=index, document_id=document_id) is not None:
            raise ElasticsearchClientError(
                f"Unexpected Elasticsearch response 409 for PUT /{index}/_create/{document_id}: conflict"
            )
        self.indices.setdefault(index, {"mapping": {}, "documents": []})
        documents = self.indices[index]["documents"]
        assert isinstance(documents, list)
        documents.append((document_id, document))

    def delete_document(self, *, index: str, document_id: str) -> None:
        documents = self.indices.get(index, {}).get("documents", [])
        if not isinstance(documents, list):
            return
        self.indices[index]["documents"] = [
            (current_id, source)
            for current_id, source in documents
            if current_id != document_id
        ]


class FailingRemoteElasticsearchClient(FakeElasticsearchClient):
    def count_documents(self, *, index: str, query: dict[str, object]) -> int:
        if index.startswith("remote-articles-run-"):
            return 0
        return super().count_documents(index=index, query=query)


def _service(local_client: FakeElasticsearchClient, remote_client: FakeElasticsearchClient) -> RemoteAnalysisSyncService:
    service = RemoteAnalysisSyncService(local_client=local_client, remote_client=remote_client)
    service.specs = [
        service.specs[0].__class__(
            key="articles",
            local_index="local-articles",
            remote_alias="remote-articles",
            mapping={"mappings": {"properties": {"title": {"type": "keyword"}}}},
            source_fields=["title"],
        ),
        service.specs[0].__class__(
            key="chunks",
            local_index="local-chunks",
            remote_alias="remote-chunks",
            mapping={"mappings": {"properties": {"text": {"type": "keyword"}}}},
            source_fields=["text"],
        ),
    ]
    service.metadata_index = "remote-metadata"
    service.local_metadata_index = "local-metadata"
    return service


def test_publish_local_to_remote_cleans_up_staged_indices_on_validation_failure(monkeypatch) -> None:
    monkeypatch.setattr("app.sync.analysis.is_remote_analysis_enabled", lambda: True)
    monkeypatch.setattr("app.sync.analysis.get_source_es_index", lambda: "source-index")
    monkeypatch.setattr("app.sync.analysis.get_duplicate_embedding_provider", lambda: "local")

    local_client = FakeElasticsearchClient()
    local_client.indices["local-articles"] = {"mapping": {}, "documents": [("a1", {"title": "A"})]}
    local_client.indices["local-chunks"] = {"mapping": {}, "documents": [("c1", {"text": "C"})]}

    remote_client = FailingRemoteElasticsearchClient()
    service = _service(local_client, remote_client)

    logs: list[str] = []
    try:
        service.publish_local_to_remote(progress_callback=logs.append)
    except ElasticsearchClientError as exc:
        assert "Remote publish validation failed" in str(exc)
    else:
        raise AssertionError("Expected publish to fail validation")

    assert any(index.startswith("remote-articles-run-") for index in remote_client.deleted_indices)
    assert not any(index.startswith("remote-chunks-run-") for index in remote_client.deleted_indices)
    assert any("Deleted staged remote analysis index after failed publish" in message for message in logs)
    assert "remote-metadata" in remote_client.indices
    assert remote_client.get_document(index="remote-metadata", document_id="publish-lock") is None
    assert remote_client.aliases == {}


def test_publish_local_to_remote_promotes_aliases_and_records_metadata(monkeypatch) -> None:
    monkeypatch.setattr("app.sync.analysis.is_remote_analysis_enabled", lambda: True)
    monkeypatch.setattr("app.sync.analysis.get_source_es_index", lambda: "source-index")
    monkeypatch.setattr("app.sync.analysis.get_duplicate_embedding_provider", lambda: "jina")

    local_client = FakeElasticsearchClient()
    local_client.indices["local-articles"] = {"mapping": {}, "documents": [("a1", {"title": "A"})]}
    local_client.indices["local-chunks"] = {"mapping": {}, "documents": [("c1", {"text": "C"})]}

    remote_client = FakeElasticsearchClient()
    service = _service(local_client, remote_client)

    summary = service.publish_local_to_remote()

    assert summary.article_documents == 1
    assert summary.chunk_documents == 1
    assert summary.remote_run_id is not None
    assert remote_client.aliases["remote-articles"]
    assert remote_client.aliases["remote-chunks"]
    assert "remote-metadata" in remote_client.indices
    assert "local-metadata" in local_client.indices
    assert remote_client.get_document(index="remote-metadata", document_id="publish-lock") is None


def test_publish_local_to_remote_blocks_when_local_snapshot_is_stale(monkeypatch) -> None:
    monkeypatch.setattr("app.sync.analysis.is_remote_analysis_enabled", lambda: True)
    monkeypatch.setattr("app.sync.analysis.get_source_es_index", lambda: "source-index")
    monkeypatch.setattr("app.sync.analysis.get_duplicate_embedding_provider", lambda: "local")

    local_client = FakeElasticsearchClient()
    local_client.indices["local-articles"] = {"mapping": {}, "documents": [("a1", {"title": "A"})]}
    local_client.indices["local-chunks"] = {"mapping": {}, "documents": [("c1", {"text": "C"})]}
    local_client.indices["local-metadata"] = {
        "mapping": {},
        "documents": [("latest", {"run_id": "run-older", "published_at": "2026-05-05T12:00:00Z", "synced_at": "2026-05-05T12:05:00Z", "embedding_provider": "local"})],
    }

    remote_client = FakeElasticsearchClient()
    remote_client.indices["remote-metadata"] = {
        "mapping": {},
        "documents": [("published", {"run_id": "run-newer", "mode": "publish_remote_analysis", "published_at": "2026-05-05T13:00:00Z", "embedding_provider": "local"})],
    }

    service = _service(local_client, remote_client)

    try:
        service.publish_local_to_remote()
    except ElasticsearchClientError as exc:
        assert "stale" in str(exc) or "Pull published remote analysis before publishing" in str(exc)
    else:
        raise AssertionError("Expected publish to be blocked for a stale local snapshot")


def test_publish_local_to_remote_blocks_when_lock_exists(monkeypatch) -> None:
    monkeypatch.setattr("app.sync.analysis.is_remote_analysis_enabled", lambda: True)
    monkeypatch.setattr("app.sync.analysis.get_source_es_index", lambda: "source-index")
    monkeypatch.setattr("app.sync.analysis.get_duplicate_embedding_provider", lambda: "local")

    local_client = FakeElasticsearchClient()
    local_client.indices["local-articles"] = {"mapping": {}, "documents": [("a1", {"title": "A"})]}
    local_client.indices["local-chunks"] = {"mapping": {}, "documents": [("c1", {"text": "C"})]}

    remote_client = FakeElasticsearchClient()
    remote_client.indices["remote-metadata"] = {
        "mapping": {},
        "documents": [("publish-lock", {"run_id": "run-other", "lock_holder": "run-other", "expires_at": "2099-05-05T13:00:00Z"})],
    }
    service = _service(local_client, remote_client)

    try:
        service.publish_local_to_remote()
    except ElasticsearchClientError as exc:
        assert "publish lock" in str(exc)
    else:
        raise AssertionError("Expected publish to be blocked by an active lock")
