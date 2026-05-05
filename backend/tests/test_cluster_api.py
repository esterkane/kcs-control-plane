from fastapi.testclient import TestClient

from app.clustering.service import ClusterDetailResponse, ClusterListResponse, ClusterMaterializationSummary
from app.main import app


client = TestClient(app)


def test_list_clusters_endpoint(monkeypatch) -> None:
    expected = ClusterListResponse.model_validate(
        {
            "count": 1,
            "items": [
                {
                    "clusterId": "family-1",
                    "articleIds": ["a", "b"],
                    "memberCount": 2,
                    "reviewState": "pending_review",
                    "representativeArticleId": "a",
                    "representativeTitle": "Article A",
                }
            ],
        }
    )

    class FakeService:
        def list_clusters(self, *, size: int = 20):
            return expected

    monkeypatch.setattr("app.api.routes.clusters.build_duplicate_cluster_service", lambda: FakeService())

    response = client.get("/kb/clusters")

    assert response.status_code == 200
    assert response.json()["items"][0]["clusterId"] == "family-1"


def test_get_cluster_endpoint(monkeypatch) -> None:
    expected = ClusterDetailResponse.model_validate(
        {
            "clusterId": "family-1",
            "articleIds": ["a", "b"],
            "edgeIds": ["edge-1"],
            "memberCount": 2,
            "reviewState": "pending_review",
            "representativeArticleId": "a",
            "representativeTitle": "Article A",
            "memberships": [
                {
                    "articleId": "a",
                    "title": "Article A",
                    "supportingEdgeIds": ["edge-1"],
                    "reasons": ["shared_metadata"],
                    "sharedMetadata": {"products": ["Cloud"]},
                }
            ],
            "thresholds": {
                "topN": 12,
                "includeCve": False,
                "includeChunkSeed": True,
                "maxComponentSize": 12,
                "weakEdgeThreshold": 0.78,
                "analysisMode": "graph",
            },
            "materializedAt": "2026-04-28T12:00:00Z",
            "edges": [
                {
                    "edgeId": "edge-1",
                    "leftArticleId": "a",
                    "rightArticleId": "b",
                    "label": "exact_duplicate",
                    "accepted": True,
                    "totalScore": 0.94,
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
                    "sourceQueryArticleId": "a",
                    "sourceCandidateArticleId": "b",
                    "materializedAt": "2026-04-28T12:00:00Z",
                }
            ],
        }
    )

    class FakeService:
        def get_cluster(self, cluster_id: str):
            return expected

    monkeypatch.setattr("app.api.routes.clusters.build_duplicate_cluster_service", lambda: FakeService())

    response = client.get("/kb/clusters/family-1")

    assert response.status_code == 200
    assert response.json()["clusterId"] == "family-1"


def test_get_cluster_for_article_endpoint(monkeypatch) -> None:
    expected = ClusterListResponse.model_validate(
        {
            "count": 1,
            "items": [
                {
                    "clusterId": "family-1",
                    "articleIds": ["a", "b"],
                    "memberCount": 2,
                    "reviewState": "pending_review",
                    "representativeArticleId": "a",
                    "representativeTitle": "Article A",
                }
            ],
        }
    ).items[0]

    class FakeService:
        def get_cluster_for_article(self, article_id: str):
            return expected if article_id == "a" else None

    monkeypatch.setattr("app.api.routes.clusters.build_duplicate_cluster_service", lambda: FakeService())

    response = client.get("/kb/articles/a/cluster")

    assert response.status_code == 200
    assert response.json()["clusterId"] == "family-1"


def test_update_cluster_endpoint(monkeypatch) -> None:
    expected = ClusterDetailResponse.model_validate(
        {
            "clusterId": "family-1",
            "articleIds": ["a", "b"],
            "edgeIds": ["edge-1"],
            "memberCount": 2,
            "reviewState": "approved_family",
            "representativeArticleId": "a",
            "representativeTitle": "Article A",
            "memberships": [
                {
                    "articleId": "a",
                    "title": "Article A",
                    "supportingEdgeIds": ["edge-1"],
                    "reasons": ["shared_metadata"],
                    "sharedMetadata": {"products": ["Cloud"]},
                }
            ],
            "thresholds": {
                "topN": 12,
                "includeCve": False,
                "includeChunkSeed": True,
                "maxComponentSize": 12,
                "weakEdgeThreshold": 0.78,
                "analysisMode": "graph",
            },
            "materializedAt": "2026-04-28T12:00:00Z",
            "edges": [],
        }
    )

    class FakeService:
        def update_cluster_review_state(self, *, cluster_id: str, request):
            return expected if cluster_id == "family-1" else None

    monkeypatch.setattr("app.api.routes.clusters.build_duplicate_cluster_service", lambda: FakeService())

    response = client.patch("/kb/clusters/family-1", json={"reviewState": "approved_family"})

    assert response.status_code == 200
    assert response.json()["reviewState"] == "approved_family"


def test_materialize_clusters_endpoint(monkeypatch) -> None:
    expected = ClusterMaterializationSummary.model_validate(
        {
            "analysisMode": "graph",
            "analysisOnly": False,
            "sourceArticleCount": 10,
            "acceptedEdgeCount": 7,
            "clusterCount": 3,
            "reviewStateCounts": {"pending_review": 2, "split_required": 1},
        }
    )

    class FakeService:
        def materialize(self, request):
            return expected

    monkeypatch.setattr("app.api.routes.clusters.build_duplicate_cluster_service", lambda: FakeService())

    response = client.post("/kb/clusters/materialize", json={"topN": 8})

    assert response.status_code == 200
    assert response.json()["acceptedEdgeCount"] == 7
