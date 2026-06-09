from __future__ import annotations

import math
from abc import ABC, abstractmethod


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, chunk_id: int, vector: list[float]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, vector: list[float], limit: int = 20) -> list[tuple[int, float]]:
        raise NotImplementedError


class LanceDBVectorStore(VectorStore):
    """LanceDB abstraction with a local in-memory fallback.

    This keeps the interface stable while avoiding mandatory external dependencies.
    """

    def __init__(self) -> None:
        self._vectors: dict[int, list[float]] = {}

    def upsert(self, chunk_id: int, vector: list[float]) -> None:
        self._vectors[chunk_id] = vector

    def search(self, vector: list[float], limit: int = 20) -> list[tuple[int, float]]:
        scored = []
        for chunk_id, candidate in self._vectors.items():
            score = _cosine_similarity(vector, candidate)
            scored.append((chunk_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    dot = sum(left[i] * right[i] for i in range(length))
    left_norm = math.sqrt(sum(left[i] * left[i] for i in range(length)))
    right_norm = math.sqrt(sum(right[i] * right[i] for i in range(length)))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
