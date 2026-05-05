from __future__ import annotations

from app.ingestion.kb import normalize_document, should_index_document


def test_filters_draft_documents_by_remote_document_id_suffix() -> None:
    hit = {
        "_id": "article-1-draft",
        "_source": {
            "id": "article-1",
            "workflow_state": "published",
        },
    }

    assert should_index_document(hit) is False


def test_filters_non_published_and_archived_documents() -> None:
    pending_hit = {
        "_id": "remote-1",
        "_source": {
            "id": "article-1",
            "workflow_state": "review",
        },
    }
    archived_hit = {
        "_id": "remote-2",
        "_source": {
            "id": "article-2",
            "workflow_state": "published",
            "archived": True,
        },
    }

    assert should_index_document(pending_hit) is False
    assert should_index_document(archived_hit) is False


def test_normalizes_ai_fields_without_using_ai_source_id() -> None:
    hit = {
        "_id": "remote-100",
        "_source": {
            "id": "article-100",
            "workflow_state": "published",
            "title": "Login issue",
            "body": "Markdown body",
            "products": "Cloud, Enterprise",
            "components": "Auth;API",
            "ai_fields": {
                "source_id": "wrong-primary-id",
                "summary": "AI generated summary",
                "subtitle": "AI subtitle",
                "questions": '["How to login?", "Why is SSO failing?"]',
                "tags": "identity|sso",
            },
        },
    }

    normalized = normalize_document(hit, source_index="source-index")

    assert normalized is not None
    assert normalized.article_id == "article-100"
    assert normalized.remote_document_id == "remote-100"
    assert normalized.products == ["Cloud, Enterprise"]
    assert normalized.components == ["Auth", "API"]
    assert normalized.ai_summary == "AI generated summary"
    assert normalized.ai_subtitle == "AI subtitle"
    assert normalized.ai_questions == ["How to login?", "Why is SSO failing?"]
    assert normalized.ai_tags == ["identity", "sso"]


def test_normalizes_remote_kb_content_schema() -> None:
    hit = {
        "_id": "remote-200",
        "_source": {
            "id": "article-200",
            "state": "published",
            "content_title": "Logstash persisted queue monitoring",
            "content_summary": "How to inspect persisted queue size over time.",
            "content_body": "## Resolution\nUse Metricbeat monitoring data.",
            "category": "knowledge_article",
            "visibility_external": "false",
            "visibility_was_published": "true",
            "visibility_was_checked_in": "false",
            "metadata_products": ["Logstash"],
            "metadata_components": ["Stack monitoring"],
            "metadata_product_versions": ["7.x"],
            "metadata_deployments": ["Elastic self-managed"],
            "metadata_platforms": ["Self-managed / On-premise / ECE / ECK"],
            "modified_date": "2023-01-26T12:02:57.607Z",
            "ai_fields": {
                "source_id": "remote-200",
                "ai_summary": "Monitoring queue growth over time.",
                "ai_subtitle": "Persisted queue analysis",
                "ai_questions_answered": [
                    "How can I monitor the persisted queue?",
                ],
                "ai_tags": ["Logstash", "Monitoring"],
            },
        },
    }

    normalized = normalize_document(hit, source_index="source-index")

    assert normalized is not None
    assert normalized.title == "Logstash persisted queue monitoring"
    assert normalized.summary == "How to inspect persisted queue size over time."
    assert normalized.body_markdown == "## Resolution\nUse Metricbeat monitoring data."
    assert normalized.products == ["Logstash"]
    assert normalized.components == ["Stack monitoring"]
    assert normalized.product_versions == ["7.x"]
    assert normalized.deployments == ["Elastic self-managed"]
    assert normalized.platforms == ["Self-managed / On-premise / ECE / ECK"]
    assert normalized.ai_summary == "Monitoring queue growth over time."
    assert normalized.ai_subtitle == "Persisted queue analysis"
    assert normalized.ai_questions == ["How can I monitor the persisted queue?"]
    assert normalized.ai_tags == ["Logstash", "Monitoring"]
    assert normalized.source_updated_at == "2023-01-26T12:02:57.607Z"


def test_normalizes_invalid_surrogate_text_values() -> None:
    hit = {
        "_id": "remote-bad-unicode",
        "_source": {
            "id": "article-bad-unicode",
            "workflow_state": "published",
            "title": "Bad\ud800title",
            "summary": "Sum\ud800mary",
            "body": "## Resolution\nFix\ud800it",
            "products": ["Cloud\ud800"],
            "ai_fields": {
                "summary": "AI\ud800summary",
                "questions": ["How\ud800?"],
            },
        },
    }

    normalized = normalize_document(hit, source_index="source-index")

    assert normalized is not None
    assert normalized.title == "Badtitle"
    assert normalized.summary == "Summary"
    assert normalized.body_markdown == "## Resolution\nFixit"
    assert normalized.products == ["Cloud"]
    assert normalized.ai_summary == "AIsummary"
    assert normalized.ai_questions == ["How?"]
