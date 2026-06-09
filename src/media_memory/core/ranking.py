from __future__ import annotations


def combine_scores(lexical_score: float, vector_score: float, lexical_weight: float = 0.65) -> float:
    lexical_weight = max(0.0, min(1.0, lexical_weight))
    vector_weight = 1.0 - lexical_weight
    return lexical_weight * lexical_score + vector_weight * vector_score
