from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_target_chunk_index, get_target_es_index, get_target_es_url
from app.dedup.chunking import chunk_article_document
from app.dedup.compare_text import build_compare_text
from app.embeddings.providers import EmbeddingProvider, create_duplicate_embedding_provider
from app.elasticsearch.client import ElasticsearchClient, ElasticsearchClientError
from app.ingestion.kb import NormalizedKbDocument
from app.reranking.providers import RerankItem, RerankerProvider, StubRerankerProvider, create_reranker_provider

RRF_K = 60
CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d+\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
MAX_LEXICAL_TITLE_WORDS = 24
MAX_LEXICAL_SUMMARY_WORDS = 48
MAX_LEXICAL_COMPARE_WORDS = 180
ARTICLE_SOURCE_INCLUDES = [
    "*",
    "duplicate_comparison_embedding",
    "duplicate_title_embedding",
    "duplicate_summary_embedding",
    "duplicate_body_embedding",
]
CHUNK_SOURCE_INCLUDES = [
    "article_id",
    "chunk_id",
    "chunk_text",
    "chunk_heading",
    "chunk_ordinal",
    "duplicate_comparison_embedding",
]


class SimilarSearchRequest(BaseModel):
    article_id: str | None = Field(default=None, alias="articleId")
    title: str | None = None
    summary: str | None = None
    compare_text: str | None = Field(default=None, alias="compareText")
    products: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    product_versions: list[str] = Field(default_factory=list, alias="productVersions")
    deployments: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    include_cve: bool = Field(default=False, alias="includeCve")
    include_chunk_seed: bool = Field(default=True, alias="includeChunkSeed")
    limit: int = 10

    model_config = {"populate_by_name": True}


class SimilarChunkEvidence(BaseModel):
    query_chunk_id: str = Field(alias="queryChunkId")
    candidate_chunk_id: str = Field(alias="candidateChunkId")
    similarity: float
    query_heading: str | None = Field(alias="queryHeading")
    candidate_heading: str | None = Field(alias="candidateHeading")
    query_text: str = Field(alias="queryText")
    candidate_text: str = Field(alias="candidateText")

    model_config = {"populate_by_name": True}


class SimilarEvidence(BaseModel):
    shared_metadata: dict[str, list[str]] = Field(alias="sharedMetadata")
    most_similar_chunks: list[SimilarChunkEvidence] = Field(alias="mostSimilarChunks")
    reasons: list[str]

    model_config = {"populate_by_name": True}


class PairScores(BaseModel):
    rrf_score: float = Field(alias="rrfScore")
    article_embedding_similarity: float = Field(alias="articleEmbeddingSimilarity")
    best_chunk_similarity: float = Field(alias="bestChunkSimilarity")
    title_similarity: float = Field(alias="titleSimilarity")
    summary_similarity: float = Field(alias="summarySimilarity")
    metadata_agreement: float = Field(alias="metadataAgreement")
    rerank_score: float = Field(alias="rerankScore")
    total_score: float = Field(alias="totalScore")

    model_config = {"populate_by_name": True}


class SimilarArticleCandidate(BaseModel):
    article_id: str = Field(alias="articleId")
    label: str
    title: str | None
    summary: str | None
    pair_scores: PairScores = Field(alias="pairScores")
    evidence: SimilarEvidence

    model_config = {"populate_by_name": True}


class SimilarSearchResponse(BaseModel):
    query_article_id: str | None = Field(alias="queryArticleId")
    candidate_count: int = Field(alias="candidateCount")
    candidates: list[SimilarArticleCandidate]

    model_config = {"populate_by_name": True}


@dataclass
class QueryChunk:
    chunk_id: str
    heading: str | None
    text: str
    embedding: list[float] | None


@dataclass
class CandidateState:
    article: NormalizedKbDocument
    article_rrf_score: float = 0.0
    lexical_rank: int | None = None
    vector_rank: int | None = None
    chunk_rank: int | None = None
    chunk_evidence: list[SimilarChunkEvidence] = field(default_factory=list)


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token for token in re.findall(r"[a-z0-9]+", text.casefold()) if token}


def _jaccard_similarity(left: str | None, right: str | None) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(l * r for l, r in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _article_embedding_similarity(
    query: NormalizedKbDocument,
    candidate: NormalizedKbDocument,
) -> float:
    weighted_scores: list[tuple[float, float]] = []

    compare_similarity = _cosine_similarity(
        query.duplicate_comparison_embedding,
        candidate.duplicate_comparison_embedding,
    )
    if compare_similarity > 0:
        weighted_scores.append((compare_similarity, 0.5))

    title_similarity = _cosine_similarity(
        query.duplicate_title_embedding,
        candidate.duplicate_title_embedding,
    )
    if title_similarity > 0:
        weighted_scores.append((title_similarity, 0.2))

    summary_similarity = _cosine_similarity(
        query.duplicate_summary_embedding,
        candidate.duplicate_summary_embedding,
    )
    if summary_similarity > 0:
        weighted_scores.append((summary_similarity, 0.15))

    body_similarity = _cosine_similarity(
        query.duplicate_body_embedding,
        candidate.duplicate_body_embedding,
    )
    if body_similarity > 0:
        weighted_scores.append((body_similarity, 0.15))

    if not weighted_scores:
        return 0.0

    numerator = sum(score * weight for score, weight in weighted_scores)
    denominator = sum(weight for _, weight in weighted_scores)
    return numerator / denominator


def _shared_metadata(query: NormalizedKbDocument, candidate: NormalizedKbDocument) -> dict[str, list[str]]:
    shared: dict[str, list[str]] = {}
    for field_name in ("products", "components", "product_versions", "deployments", "platforms"):
        overlap = sorted(set(getattr(query, field_name)) & set(getattr(candidate, field_name)))
        if overlap:
            shared[field_name] = overlap
    if query.category and candidate.category and query.category == candidate.category:
        shared["category"] = [query.category]
    return shared


def _metadata_agreement(query: NormalizedKbDocument, candidate: NormalizedKbDocument) -> float:
    compared = 0
    matched = 0
    for field_name in ("products", "components", "product_versions", "deployments", "platforms"):
        query_values = set(getattr(query, field_name))
        candidate_values = set(getattr(candidate, field_name))
        if not query_values and not candidate_values:
            continue
        compared += 1
        if query_values & candidate_values:
            matched += 1
    if query.category or candidate.category:
        compared += 1
        if query.category and candidate.category and query.category == candidate.category:
            matched += 1
    return matched / compared if compared else 0.0


def classify_pair(scores: PairScores) -> str:
    if (
        scores.total_score >= 0.86
        and scores.title_similarity >= 0.7
        and max(scores.article_embedding_similarity, scores.rerank_score) >= 0.82
    ):
        return "exact_duplicate"
    if scores.total_score >= 0.68 and (
        scores.best_chunk_similarity >= 0.58 or scores.article_embedding_similarity >= 0.72
    ):
        return "near_duplicate"
    if scores.total_score >= 0.42:
        return "same_topic_related"
    return "keep_separate"


def _reason_codes(
    scores: PairScores,
    shared_metadata: dict[str, list[str]],
    chunk_evidence: list[SimilarChunkEvidence],
) -> list[str]:
    reasons: list[str] = []
    if scores.article_embedding_similarity >= 0.75:
        reasons.append("high_article_embedding_similarity")
    if scores.best_chunk_similarity >= 0.6:
        reasons.append("high_chunk_similarity")
    if scores.title_similarity >= 0.6:
        reasons.append("high_title_similarity")
    if scores.summary_similarity >= 0.5:
        reasons.append("high_summary_similarity")
    if shared_metadata:
        reasons.append("shared_metadata")
    if scores.rerank_score >= 0.6:
        reasons.append("reranker_support")
    if chunk_evidence:
        reasons.append("chunk_seeded_match")
    return reasons


def _rrf_score(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (RRF_K + rank)


def _is_cve_candidate(article: NormalizedKbDocument) -> bool:
    haystacks = [article.title or "", article.summary or "", article.category or ""]
    haystacks.extend(article.ai_tags)
    return any(CVE_PATTERN.search(text) for text in haystacks)


def _is_draft_variant(article: NormalizedKbDocument) -> bool:
    return article.remote_document_id.casefold().endswith("-draft")


def _limit_words(text: str | None, *, max_words: int) -> str:
    if not text:
        return ""
    normalized = WHITESPACE_PATTERN.sub(" ", text).strip()
    if not normalized:
        return ""
    words = normalized.split(" ")
    return " ".join(words[:max_words])


def _query_document_from_request(request: SimilarSearchRequest) -> NormalizedKbDocument:
    return NormalizedKbDocument.model_validate(
        {
            "article_id": request.article_id or "adhoc-query",
            "remote_document_id": request.article_id or "adhoc-query",
            "title": request.title,
            "summary": request.summary,
            "body_markdown": request.compare_text,
            "symptoms": None,
            "category": None,
            "visibility_external": None,
            "visibility_was_published": None,
            "visibility_was_checked_in": None,
            "products": request.products,
            "components": request.components,
            "product_versions": request.product_versions,
            "deployments": request.deployments,
            "platforms": request.platforms,
            "ai_summary": None,
            "ai_subtitle": None,
            "ai_questions": [],
            "ai_tags": [],
            "source_updated_at": None,
            "source_index": "adhoc",
            "compare_text": request.compare_text,
            "compare_text_hash": None,
            "duplicate_comparison_embedding": None,
        }
    )


class SimilarArticleService:
    def __init__(
        self,
        *,
        es_client: ElasticsearchClient,
        reranker: RerankerProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_task: str | None = None,
        article_index: str = "kcs-kb-articles-v1",
        chunk_index: str = "kcs-kb-article-chunks-v1",
        enable_lexical_search: bool = True,
    ) -> None:
        self.es_client = es_client
        self.reranker = reranker or StubRerankerProvider()
        self.embedding_provider = embedding_provider
        self.embedding_task = embedding_task or "retrieval.query"
        self.article_index = article_index
        self.chunk_index = chunk_index
        self.enable_lexical_search = enable_lexical_search

    def _article_from_hit(self, hit: dict[str, Any]) -> NormalizedKbDocument | None:
        source = hit.get("_source")
        if not isinstance(source, dict):
            return None
        return NormalizedKbDocument.model_validate(source)

    def get_article_by_id(self, article_id: str) -> NormalizedKbDocument | None:
        hits = self.es_client.search(
            index=self.article_index,
            body={
                "size": 1,
                "_source": {"includes": ARTICLE_SOURCE_INCLUDES},
                "query": {"term": {"article_id": article_id}},
            },
        )
        if not hits:
            return None
        return self._article_from_hit(hits[0])

    def _query_compare_text(self, article: NormalizedKbDocument) -> str:
        return article.compare_text or build_compare_text(article)

    def _hydrate_query_article(self, article: NormalizedKbDocument) -> NormalizedKbDocument:
        compare_text = self._query_compare_text(article)
        title_text = article.title or ""
        summary_text = article.summary or ""
        body_text = article.body_markdown or compare_text

        update_payload: dict[str, Any] = {"compare_text": compare_text}
        if self.embedding_provider is not None:
            vectors = self.embedding_provider.embed_batch(
                [title_text, summary_text, body_text, compare_text],
                self.embedding_task,
            )
            if len(vectors) == 4:
                update_payload["duplicate_title_embedding"] = vectors[0] if title_text else None
                update_payload["duplicate_summary_embedding"] = vectors[1] if summary_text else None
                update_payload["duplicate_body_embedding"] = vectors[2] if body_text else None
                update_payload["duplicate_comparison_embedding"] = vectors[3] if compare_text else None

        return article.model_copy(update=update_payload)

    def _bounded_lexical_query_text(
        self,
        article: NormalizedKbDocument,
        *,
        include_compare_text: bool,
    ) -> str:
        parts = [
            _limit_words(article.title, max_words=MAX_LEXICAL_TITLE_WORDS),
            _limit_words(article.summary, max_words=MAX_LEXICAL_SUMMARY_WORDS),
        ]
        if include_compare_text:
            parts.append(
                _limit_words(
                    self._query_compare_text(article),
                    max_words=MAX_LEXICAL_COMPARE_WORDS,
                )
            )
        return " ".join(part for part in parts if part).strip()

    def _lexical_candidates(self, *, article: NormalizedKbDocument, limit: int) -> list[NormalizedKbDocument]:
        if not self.enable_lexical_search:
            return []
        query_text = self._bounded_lexical_query_text(article, include_compare_text=True)
        if not query_text:
            return []
        search_body = {
            "size": max(limit * 3, 20),
            "_source": {"includes": ARTICLE_SOURCE_INCLUDES},
            "query": {
                "multi_match": {
                    "query": query_text,
                    "fields": ["title^4", "summary^2.5", "compare_text^1.5"],
                    "type": "best_fields",
                }
            },
        }
        try:
            hits = self.es_client.search(index=self.article_index, body=search_body)
        except ElasticsearchClientError as exc:
            # Fall back to title/summary lexical search if a long compare-text query still exceeds
            # Elasticsearch's max clause count.
            narrower_query_text = self._bounded_lexical_query_text(article, include_compare_text=False)
            if not narrower_query_text or "too many clauses" not in str(exc).casefold():
                raise
            hits = self.es_client.search(
                index=self.article_index,
                body={
                    "size": max(limit * 3, 20),
                    "_source": {"includes": ARTICLE_SOURCE_INCLUDES},
                    "query": {
                        "multi_match": {
                            "query": narrower_query_text,
                            "fields": ["title^4", "summary^2.5"],
                            "type": "best_fields",
                        }
                    },
                },
            )
        return [candidate for hit in hits if (candidate := self._article_from_hit(hit)) is not None]

    def _embedding_candidates(self, *, article: NormalizedKbDocument, limit: int) -> list[NormalizedKbDocument]:
        if not article.duplicate_comparison_embedding:
            return []
        hits = self.es_client.search(
            index=self.article_index,
            body={
                "size": max(limit * 3, 20),
                "_source": {"includes": ARTICLE_SOURCE_INCLUDES},
                "knn": {
                    "field": "duplicate_comparison_embedding",
                    "query_vector": article.duplicate_comparison_embedding,
                    "k": max(limit * 3, 20),
                    "num_candidates": max(limit * 6, 50),
                },
            },
        )
        return [candidate for hit in hits if (candidate := self._article_from_hit(hit)) is not None]

    def _query_chunks(self, article_id: str) -> list[QueryChunk]:
        hits = self.es_client.search(
            index=self.chunk_index,
            body={
                "size": 100,
                "_source": {"includes": CHUNK_SOURCE_INCLUDES},
                "query": {"term": {"article_id": article_id}},
                "sort": [{"chunk_ordinal": "asc"}],
            },
        )
        chunks: list[QueryChunk] = []
        for hit in hits:
            source = hit.get("_source")
            if not isinstance(source, dict):
                continue
            chunk_id = source.get("chunk_id")
            chunk_text = source.get("chunk_text")
            if not isinstance(chunk_id, str) or not isinstance(chunk_text, str):
                continue
            chunks.append(
                QueryChunk(
                    chunk_id=chunk_id,
                    heading=source.get("chunk_heading") if isinstance(source.get("chunk_heading"), str) else None,
                    text=chunk_text,
                    embedding=source.get("duplicate_comparison_embedding")
                    if isinstance(source.get("duplicate_comparison_embedding"), list)
                    else None,
                )
            )
        return chunks

    def _adhoc_query_chunks(self, article: NormalizedKbDocument) -> list[QueryChunk]:
        if self.embedding_provider is None:
            return []
        article_chunks = chunk_article_document(article)
        if not article_chunks:
            return []
        texts = [chunk.text for chunk in article_chunks]
        vectors = self.embedding_provider.embed_batch(texts, self.embedding_task)
        chunks: list[QueryChunk] = []
        for article_chunk, vector in zip(article_chunks, vectors, strict=True):
            chunks.append(
                QueryChunk(
                    chunk_id=article_chunk.chunk_id,
                    heading=article_chunk.heading,
                    text=article_chunk.text,
                    embedding=vector,
                )
            )
        return chunks

    def _chunk_seed_candidates(
        self,
        *,
        article: NormalizedKbDocument,
        limit: int,
    ) -> dict[str, list[SimilarChunkEvidence]]:
        query_chunks = (
            self._query_chunks(article.article_id)
            if article.article_id != "adhoc-query"
            else self._adhoc_query_chunks(article)
        )
        if not query_chunks:
            return {}

        evidence_by_article: dict[str, list[SimilarChunkEvidence]] = {}
        for query_chunk in query_chunks[:3]:
            if not query_chunk.embedding:
                continue
            hits = self.es_client.search(
                index=self.chunk_index,
                body={
                    "size": max(limit * 2, 10),
                    "_source": {"includes": CHUNK_SOURCE_INCLUDES},
                    "knn": {
                        "field": "duplicate_comparison_embedding",
                        "query_vector": query_chunk.embedding,
                        "k": max(limit * 2, 10),
                        "num_candidates": max(limit * 4, 30),
                    },
                },
            )
            for hit in hits:
                source = hit.get("_source")
                if not isinstance(source, dict):
                    continue
                candidate_article_id = source.get("article_id")
                candidate_chunk_id = source.get("chunk_id")
                candidate_text = source.get("chunk_text")
                candidate_embedding = source.get("duplicate_comparison_embedding")
                if not isinstance(candidate_article_id, str) or candidate_article_id == article.article_id:
                    continue
                if not isinstance(candidate_chunk_id, str) or not isinstance(candidate_text, str):
                    continue
                evidence = SimilarChunkEvidence(
                    queryChunkId=query_chunk.chunk_id,
                    candidateChunkId=candidate_chunk_id,
                    similarity=round(
                        _cosine_similarity(
                            query_chunk.embedding,
                            candidate_embedding if isinstance(candidate_embedding, list) else None,
                        ),
                        4,
                    ),
                    queryHeading=query_chunk.heading,
                    candidateHeading=source.get("chunk_heading") if isinstance(source.get("chunk_heading"), str) else None,
                    queryText=query_chunk.text,
                    candidateText=candidate_text,
                )
                evidence_by_article.setdefault(candidate_article_id, []).append(evidence)
        for evidences in evidence_by_article.values():
            evidences.sort(key=lambda item: item.similarity, reverse=True)
        return evidence_by_article

    def _eligible_candidate(
        self,
        *,
        query_article: NormalizedKbDocument,
        candidate: NormalizedKbDocument,
        include_cve: bool,
    ) -> bool:
        if candidate.article_id == query_article.article_id:
            return False
        if _is_draft_variant(candidate):
            return False
        if not include_cve and _is_cve_candidate(candidate):
            return False
        return True

    def _rerank_scores(
        self,
        *,
        query_text: str,
        candidates: list[CandidateState],
    ) -> dict[str, float]:
        documents = [candidate.article.compare_text or build_compare_text(candidate.article) for candidate in candidates]
        reranked = self.reranker.rerank(query_text, documents)
        scores: dict[str, float] = {}
        for item in reranked:
            if 0 <= item.index < len(candidates):
                scores[candidates[item.index].article.article_id] = item.relevance_score
        return scores

    def search(self, request: SimilarSearchRequest) -> SimilarSearchResponse:
        if request.article_id:
            query_article = self.get_article_by_id(request.article_id)
            if query_article is None:
                raise ValueError(f"Article not found: {request.article_id}")
        else:
            query_article = self._hydrate_query_article(_query_document_from_request(request))

        lexical = self._lexical_candidates(article=query_article, limit=request.limit)
        vector = self._embedding_candidates(article=query_article, limit=request.limit)
        chunk_evidence = self._chunk_seed_candidates(article=query_article, limit=request.limit) if request.include_chunk_seed else {}

        candidates: dict[str, CandidateState] = {}

        def register(candidate: NormalizedKbDocument) -> CandidateState:
            state = candidates.get(candidate.article_id)
            if state is None:
                state = CandidateState(article=candidate)
                candidates[candidate.article_id] = state
            return state

        for rank, candidate in enumerate(lexical, start=1):
            if not self._eligible_candidate(query_article=query_article, candidate=candidate, include_cve=request.include_cve):
                continue
            register(candidate).lexical_rank = rank

        for rank, candidate in enumerate(vector, start=1):
            if not self._eligible_candidate(query_article=query_article, candidate=candidate, include_cve=request.include_cve):
                continue
            register(candidate).vector_rank = rank

        for article_id, evidence in chunk_evidence.items():
            candidate = self.get_article_by_id(article_id)
            if candidate is None:
                continue
            if not self._eligible_candidate(query_article=query_article, candidate=candidate, include_cve=request.include_cve):
                continue
            state = register(candidate)
            state.chunk_rank = 1
            state.chunk_evidence = evidence[:3]

        ranked_states = list(candidates.values())
        for state in ranked_states:
            state.article_rrf_score = (
                _rrf_score(state.lexical_rank)
                + _rrf_score(state.vector_rank)
                + _rrf_score(state.chunk_rank)
            )
        ranked_states.sort(key=lambda state: state.article_rrf_score, reverse=True)
        ranked_states = ranked_states[: max(request.limit * 2, request.limit)]

        rerank_scores = self._rerank_scores(
            query_text=self._query_compare_text(query_article),
            candidates=ranked_states,
        )

        candidates_out: list[SimilarArticleCandidate] = []
        for state in ranked_states:
            candidate = state.article
            article_similarity = _article_embedding_similarity(query_article, candidate)
            best_chunk_similarity = max((item.similarity for item in state.chunk_evidence), default=0.0)
            title_similarity = _jaccard_similarity(query_article.title, candidate.title)
            summary_similarity = _jaccard_similarity(query_article.summary, candidate.summary)
            metadata_agreement = _metadata_agreement(query_article, candidate)
            rerank_score = rerank_scores.get(candidate.article_id, 0.0)
            total_score = min(
                1.0,
                (state.article_rrf_score * 8.0)
                + (article_similarity * 0.28)
                + (best_chunk_similarity * 0.18)
                + (title_similarity * 0.18)
                + (summary_similarity * 0.12)
                + (metadata_agreement * 0.1)
                + (rerank_score * 0.14),
            )
            scores = PairScores(
                rrfScore=round(state.article_rrf_score, 4),
                articleEmbeddingSimilarity=round(article_similarity, 4),
                bestChunkSimilarity=round(best_chunk_similarity, 4),
                titleSimilarity=round(title_similarity, 4),
                summarySimilarity=round(summary_similarity, 4),
                metadataAgreement=round(metadata_agreement, 4),
                rerankScore=round(rerank_score, 4),
                totalScore=round(total_score, 4),
            )
            shared_metadata = _shared_metadata(query_article, candidate)
            evidence = SimilarEvidence(
                sharedMetadata=shared_metadata,
                mostSimilarChunks=state.chunk_evidence[:3],
                reasons=_reason_codes(scores, shared_metadata, state.chunk_evidence),
            )
            candidates_out.append(
                SimilarArticleCandidate(
                    articleId=candidate.article_id,
                    label=classify_pair(scores),
                    title=candidate.title,
                    summary=candidate.summary,
                    pairScores=scores,
                    evidence=evidence,
                )
            )

        candidates_out.sort(key=lambda candidate: candidate.pair_scores.total_score, reverse=True)
        candidates_out = candidates_out[: request.limit]
        return SimilarSearchResponse(
            queryArticleId=query_article.article_id if request.article_id else None,
            candidateCount=len(candidates_out),
            candidates=candidates_out,
        )


def build_similarity_service() -> SimilarArticleService:
    embedding_provider, embedding_task = create_duplicate_embedding_provider()
    return SimilarArticleService(
        es_client=ElasticsearchClient(base_url=get_target_es_url()),
        reranker=create_reranker_provider(),
        embedding_provider=embedding_provider,
        embedding_task=embedding_task,
        article_index=get_target_es_index(),
        chunk_index=get_target_chunk_index(),
    )
