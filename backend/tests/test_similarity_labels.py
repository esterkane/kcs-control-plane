from app.similarity.service import PairScores, classify_pair


def _scores(**overrides: float) -> PairScores:
    base = {
        "rrfScore": 0.04,
        "articleEmbeddingSimilarity": 0.8,
        "bestChunkSimilarity": 0.7,
        "titleSimilarity": 0.8,
        "summarySimilarity": 0.7,
        "metadataAgreement": 0.8,
        "rerankScore": 0.85,
        "totalScore": 0.9,
    }
    base.update(overrides)
    return PairScores(**base)


def test_classifies_exact_duplicate() -> None:
    assert classify_pair(_scores()) == "exact_duplicate"


def test_classifies_near_duplicate() -> None:
    assert classify_pair(
        _scores(totalScore=0.74, articleEmbeddingSimilarity=0.73, titleSimilarity=0.58),
    ) == "near_duplicate"


def test_classifies_same_topic_related_and_keep_separate() -> None:
    assert classify_pair(
        _scores(
            totalScore=0.5,
            articleEmbeddingSimilarity=0.3,
            bestChunkSimilarity=0.2,
            titleSimilarity=0.3,
            rerankScore=0.2,
        ),
    ) == "same_topic_related"
    assert classify_pair(
        _scores(
            totalScore=0.2,
            articleEmbeddingSimilarity=0.1,
            bestChunkSimilarity=0.1,
            titleSimilarity=0.1,
            summarySimilarity=0.1,
            metadataAgreement=0.0,
            rerankScore=0.1,
        ),
    ) == "keep_separate"

