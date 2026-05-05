from fastapi.testclient import TestClient

from app.main import app
from app.similarity.service import SimilarSearchResponse


client = TestClient(app)


def test_get_similar_endpoint(monkeypatch) -> None:
    expected = SimilarSearchResponse.model_validate(
        {
            "queryArticleId": "article-1",
            "candidateCount": 1,
            "candidates": [
                {
                    "articleId": "article-2",
                    "label": "near_duplicate",
                    "title": "Article 2",
                    "summary": "Candidate summary",
                    "pairScores": {
                        "rrfScore": 0.1,
                        "articleEmbeddingSimilarity": 0.8,
                        "bestChunkSimilarity": 0.6,
                        "titleSimilarity": 0.7,
                        "summarySimilarity": 0.6,
                        "metadataAgreement": 0.5,
                        "rerankScore": 0.7,
                        "totalScore": 0.8,
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

    class FakeService:
        def search(self, request):
            return expected

    monkeypatch.setattr("app.api.routes.kb.build_similarity_service", lambda: FakeService())

    response = client.get("/kb/articles/article-1/similar")

    assert response.status_code == 200
    assert response.json()["queryArticleId"] == "article-1"
    assert response.json()["candidates"][0]["articleId"] == "article-2"


def test_post_similar_search_endpoint(monkeypatch) -> None:
    expected = SimilarSearchResponse.model_validate(
        {
            "queryArticleId": None,
            "candidateCount": 0,
            "candidates": [],
        }
    )

    class FakeService:
        def search(self, request):
            return expected

    monkeypatch.setattr("app.api.routes.kb.build_similarity_service", lambda: FakeService())

    response = client.post(
        "/kb/similar/search",
        json={"title": "VPN issue", "summary": "Login loop", "limit": 5},
    )

    assert response.status_code == 200
    assert response.json() == {"queryArticleId": None, "candidateCount": 0, "candidates": []}
