from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_pair_explain_endpoint(monkeypatch) -> None:
    class FakeService:
        def explain_pair(self, pair_id: str, request):
            assert request.include_research is True
            return {
                "pairId": pair_id,
                "summary": "These articles describe the same login loop.",
                "whyTheseAreSimilar": ["Shared environment", "Aligned resolution"],
                "whatDiffers": ["One article is more prescriptive"],
                "mergeRecommendationConfidence": 0.86,
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "promptVersion": "pair-cluster-explainer-v1",
                "generatedAt": "2026-04-28T12:00:00Z",
                "researchUsed": False,
            }

    monkeypatch.setattr("app.api.routes.kb.build_explanation_service", lambda: FakeService())

    response = client.post("/kb/pairs/edge-1/explain", json={"includeResearch": True})

    assert response.status_code == 200
    assert response.json()["pairId"] == "edge-1"
    assert response.json()["provider"] == "gemini"


def test_cluster_summarize_endpoint(monkeypatch) -> None:
    class FakeService:
        def summarize_cluster(self, cluster_id: str, request):
            assert request.include_research is False
            return {
                "clusterId": cluster_id,
                "summary": "This family revolves around queued macOS provisioning syncs.",
                "whyTheseAreSimilar": ["Same component", "Overlapping failure mode"],
                "whatDiffers": ["Patch-level remediation steps diverge"],
                "mergeRecommendationConfidence": 0.74,
                "provider": "stub",
                "model": "stub",
                "promptVersion": "pair-cluster-explainer-v1",
                "generatedAt": "2026-04-28T12:00:00Z",
                "researchUsed": False,
            }

    monkeypatch.setattr("app.api.routes.clusters.build_explanation_service", lambda: FakeService())

    response = client.post("/kb/clusters/family-1/summarize")

    assert response.status_code == 200
    assert response.json()["clusterId"] == "family-1"
    assert response.json()["summary"].startswith("This family")
