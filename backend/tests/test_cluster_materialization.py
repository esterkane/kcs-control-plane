from __future__ import annotations

from copy import deepcopy

from app.clustering.service import DuplicateClusterService
from app.config import ClusterMaterializationRequest
from app.ingestion.kb import NormalizedKbDocument
from app.similarity.service import SimilarSearchResponse


class FakeEsClient:
    def __init__(
        self,
        *,
        edge_documents: list[dict] | None = None,
        cluster_documents: list[dict] | None = None,
    ) -> None:
        self.created_indices: list[str] = []
        self.deleted_indices: list[str] = []
        self.bulk_calls: list[tuple[str, list[tuple[str, dict]]]] = []
        self.search_calls: list[tuple[str, dict]] = []
        self.pit_source_includes: list[list[str] | None] = []
        self.edge_documents: dict[str, dict] = {
            document["edge_id"]: deepcopy(document)
            for document in (edge_documents or [])
        }
        self.cluster_documents: dict[str, dict] = {
            document["cluster_id"]: deepcopy(document)
            for document in (cluster_documents or [])
        }
        self._pit_indices: dict[str, str] = {}
        self._pit_counter = 0

    def index_exists(self, *, index: str) -> bool:
        if index in self.created_indices:
            return True
        if index == "edges":
            return bool(self.edge_documents)
        if index == "clusters":
            return bool(self.cluster_documents)
        return False

    def create_index(self, *, index: str, mapping: dict) -> None:
        self.created_indices.append(index)

    def delete_by_query(self, *, index: str, query: dict) -> None:
        self.deleted_indices.append(index)
        if index == "edges":
            self.edge_documents = {}
        if index == "clusters":
            self.cluster_documents = {}

    def bulk_index(self, *, index: str, documents: list[tuple[str, dict]]) -> None:
        self.bulk_calls.append((index, documents))
        if index == "edges":
            for document_id, document in documents:
                self.edge_documents[document_id] = deepcopy(document)
        if index == "clusters":
            for document_id, document in documents:
                self.cluster_documents[document_id] = deepcopy(document)

    def open_point_in_time(self, *, index: str, keep_alive: str) -> str:
        self._pit_counter += 1
        pit_id = f"pit-{self._pit_counter}"
        self._pit_indices[pit_id] = index
        return pit_id

    def search_with_pit(self, *, pit_id: str, keep_alive: str, size: int, query=None, source_includes=None, search_after=None):
        self.pit_source_includes.append(source_includes)
        index = self._pit_indices[pit_id]
        if index == "articles" and search_after is None:
            return type(
                "Page",
                (),
                {
                    "pit_id": pit_id,
                    "hits": [
                        {"_source": _article("a").model_dump(by_alias=False), "sort": [1]},
                        {"_source": _article("b").model_dump(by_alias=False), "sort": [2]},
                    ],
                },
            )()
        if index == "edges" and search_after is None:
            return type(
                "Page",
                (),
                {
                    "pit_id": pit_id,
                    "hits": [
                        {"_source": deepcopy(document), "sort": [position]}
                        for position, document in enumerate(self.edge_documents.values(), start=1)
                    ],
                },
            )()
        if index == "clusters" and search_after is None:
            return type(
                "Page",
                (),
                {
                    "pit_id": pit_id,
                    "hits": [
                        {"_source": deepcopy(document), "sort": [position]}
                        for position, document in enumerate(self.cluster_documents.values(), start=1)
                    ],
                },
            )()
        return type("Page", (), {"pit_id": pit_id, "hits": []})()

    def close_point_in_time(self, *, pit_id: str) -> None:
        return None

    def search(self, *, index: str, body: dict) -> list[dict]:
        self.search_calls.append((index, body))
        if index == "clusters":
            query = body.get("query", {})
            if "terms" in query:
                cluster_ids = set(query["terms"].get("cluster_id", []))
                return [
                    {"_source": deepcopy(document)}
                    for cluster_id, document in self.cluster_documents.items()
                    if cluster_id in cluster_ids
                ]
        return []

    def count_documents(self, *, index: str, query: dict) -> int:
        if index == "edges":
            return len(self.edge_documents)
        if index == "clusters":
            return len(self.cluster_documents)
        return 0


class FakeSimilarityService:
    def __init__(self) -> None:
        self.call_count = 0

    def search(self, request):
        self.call_count += 1
        if request.article_id == "a":
            return SimilarSearchResponse.model_validate(
                {
                    "queryArticleId": "a",
                    "candidateCount": 1,
                    "candidates": [
                        {
                            "articleId": "b",
                            "label": "exact_duplicate",
                            "title": "b",
                            "summary": None,
                            "pairScores": {
                                "rrfScore": 0.1,
                                "articleEmbeddingSimilarity": 0.9,
                                "bestChunkSimilarity": 0.8,
                                "titleSimilarity": 0.9,
                                "summarySimilarity": 0.0,
                                "metadataAgreement": 1.0,
                                "rerankScore": 0.9,
                                "totalScore": 0.94,
                            },
                            "evidence": {
                                "sharedMetadata": {"products": ["Cloud"]},
                                "mostSimilarChunks": [],
                                "reasons": ["shared_metadata"],
                            },
                        }
                    ],
                }
            )
        return SimilarSearchResponse.model_validate(
            {
                "queryArticleId": request.article_id,
                "candidateCount": 1,
                "candidates": [
                    {
                        "articleId": "a",
                        "label": "exact_duplicate",
                        "title": "a",
                        "summary": None,
                        "pairScores": {
                            "rrfScore": 0.1,
                            "articleEmbeddingSimilarity": 0.9,
                            "bestChunkSimilarity": 0.8,
                            "titleSimilarity": 0.9,
                            "summarySimilarity": 0.0,
                            "metadataAgreement": 1.0,
                            "rerankScore": 0.9,
                            "totalScore": 0.94,
                        },
                        "evidence": {
                            "sharedMetadata": {"products": ["Cloud"]},
                            "mostSimilarChunks": [],
                            "reasons": ["shared_metadata"],
                        },
                    }
                ],
            }
        )


def _article(article_id: str) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": article_id,
            "remote_document_id": f"{article_id}-remote",
            "title": article_id,
            "summary": None,
            "body_markdown": None,
            "symptoms": None,
            "category": "operations",
            "visibility_external": True,
            "visibility_was_published": True,
            "visibility_was_checked_in": True,
            "products": ["Cloud"],
            "components": ["Identity"],
            "product_versions": [],
            "deployments": [],
            "platforms": [],
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": "2026-04-28T12:00:00Z",
            "source_index": "source",
            "compare_text": "Compare text",
            "compare_text_hash": "hash",
            "duplicate_comparison_embedding": [1.0, 0.0],
        }
    )


def test_materialization_persists_edges_and_clusters() -> None:
    es_client = FakeEsClient()
    service = DuplicateClusterService(
        es_client=es_client,  # type: ignore[arg-type]
        similarity_service=FakeSimilarityService(),  # type: ignore[arg-type]
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )

    summary = service.materialize(ClusterMaterializationRequest())

    assert summary.accepted_edge_count == 1
    assert summary.cluster_count == 1
    assert es_client.created_indices == ["edges", "clusters"]
    assert es_client.deleted_indices == ["edges", "clusters"]
    assert [call[0] for call in es_client.bulk_calls] == ["edges", "clusters"]
    assert es_client.bulk_calls[0][1][0][0].startswith("edge-")
    assert es_client.bulk_calls[1][1][0][0].startswith("family-")
    assert es_client.pit_source_includes[0] is not None
    assert "article_id" in es_client.pit_source_includes[0]
    assert "title" in es_client.pit_source_includes[0]


def test_materialization_reports_progress_messages() -> None:
    es_client = FakeEsClient()
    service = DuplicateClusterService(
        es_client=es_client,  # type: ignore[arg-type]
        similarity_service=FakeSimilarityService(),  # type: ignore[arg-type]
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )
    messages: list[str] = []

    service.materialize(
        ClusterMaterializationRequest(),
        progress_callback=messages.append,
    )

    assert any("candidate scan started" in message for message in messages)
    assert any("accepted_edges=" in message for message in messages)
    assert any("graph build complete" in message for message in messages)
    assert any("persistence complete" in message for message in messages)


def test_materialization_can_resume_from_persisted_edges() -> None:
    similarity = FakeSimilarityService()
    seed_service = DuplicateClusterService(
        es_client=FakeEsClient(),  # type: ignore[arg-type]
        similarity_service=similarity,  # type: ignore[arg-type]
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )
    _, seed_edges = seed_service.materialize_edges(ClusterMaterializationRequest())
    persisted_edges = [edge.model_dump(by_alias=False) for edge in seed_edges]

    es_client = FakeEsClient(edge_documents=persisted_edges)
    similarity = FakeSimilarityService()
    service = DuplicateClusterService(
        es_client=es_client,  # type: ignore[arg-type]
        similarity_service=similarity,  # type: ignore[arg-type]
        article_index="articles",
        edge_index="edges",
        cluster_index="clusters",
    )
    messages: list[str] = []

    summary = service.materialize(
        ClusterMaterializationRequest(),
        progress_callback=messages.append,
        resume_from_persisted_edges=True,
    )

    assert summary.accepted_edge_count == 1
    assert summary.cluster_count == 1
    assert similarity.call_count == 0
    assert [call[0] for call in es_client.bulk_calls] == ["clusters"]
    assert any("persisted edge checkpoint" in message for message in messages)
