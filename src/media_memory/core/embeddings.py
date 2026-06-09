from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic low-cost embedding for local development and tests."""

    def __init__(self, dims: int = 8):
        self.dims = dims

    def embed(self, text: str) -> list[float]:
        buckets = [0.0 for _ in range(self.dims)]
        if not text:
            return buckets
        for idx, ch in enumerate(text.lower()):
            buckets[idx % self.dims] += (ord(ch) % 31) / 31.0
        scale = max(len(text), 1)
        return [v / scale for v in buckets]
