from __future__ import annotations

from dataclasses import dataclass, field


LEXICAL_WEIGHT = 0.45
VECTOR_WEIGHT = 0.45
METADATA_WEIGHT = 0.10


@dataclass(frozen=True)
class RankingSignals:
    """Evidence-backed score components for one search row."""

    combined_score: float
    lexical_score: float
    vector_score: float
    metadata_score: float
    confidence: float
    why: list[str] = field(default_factory=list)


def combine_scores(
    lexical_score: float, vector_score: float, lexical_weight: float = 0.65
) -> float:
    lexical_weight = max(0.0, min(1.0, lexical_weight))
    vector_weight = 1.0 - lexical_weight
    return lexical_weight * lexical_score + vector_weight * vector_score


def combine_structured_scores(
    *,
    lexical_score: float,
    metadata_score: float,
    vector_score: float | None = None,
) -> float:
    """Combine ranking channels, renormalizing when vectors are unavailable."""

    lexical_score = _bounded(lexical_score)
    metadata_score = _bounded(metadata_score)
    if vector_score is None:
        active_weight = LEXICAL_WEIGHT + METADATA_WEIGHT
        lexical_weight = LEXICAL_WEIGHT / active_weight
        metadata_weight = METADATA_WEIGHT / active_weight
        return lexical_weight * lexical_score + metadata_weight * metadata_score

    vector_score = _bounded(vector_score)
    return (
        LEXICAL_WEIGHT * lexical_score
        + VECTOR_WEIGHT * vector_score
        + METADATA_WEIGHT * metadata_score
    )


def normalize_fts_score(score: float) -> float:
    """Map SQLite FTS bm25-derived scores into a bounded confidence value."""

    if score <= 0:
        return 0.0
    return min(1.0, score / (score + 1.0))


def metadata_confidence(signals: list[float]) -> float:
    """Collapse bounded metadata/provenance boosts into a single channel."""

    if not signals:
        return 0.0
    return _bounded(sum(_bounded(signal) for signal in signals))


def apply_source_bias(score: float, *, source_kind: str | None, preferred: set[str]) -> float:
    """Boost rows from source types that are preferred for a search mode."""

    if source_kind is None:
        return score
    if source_kind.casefold() in preferred:
        return score + 0.25
    return score


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))
