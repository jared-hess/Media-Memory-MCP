from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProviderConfigError(ValueError):
    """Raised when an explicitly configured embedding provider is unusable."""


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed(self, text: str) -> list[float]:
        """Backward-compatible single-text embedding helper."""

        return self.embed_texts([text])[0]


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic low-cost embedding for local development and tests."""

    def __init__(self, dims: int = 8):
        self.dims = dims

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        buckets = [0.0 for _ in range(self.dims)]
        if not text:
            return buckets
        for idx, ch in enumerate(text.lower()):
            buckets[idx % self.dims] += (ord(ch) % 31) / 31.0
        scale = max(len(text), 1)
        return [v / scale for v in buckets]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Opt-in OpenAI embedding provider for configured deployments."""

    MODEL = "text-embedding-3-small"

    def __init__(self, api_key: str | None, *, dimensions: int | None = None) -> None:
        if not api_key:
            raise EmbeddingProviderConfigError(
                "OpenAI embeddings require embeddings.api_key when provider is 'openai'."
            )
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.dimensions:
            response = self.client.embeddings.create(
                input=texts,
                model=self.MODEL,
                encoding_format="float",
                dimensions=self.dimensions,
            )
        else:
            response = self.client.embeddings.create(
                input=texts,
                model=self.MODEL,
                encoding_format="float",
            )
        return [list(item.embedding) for item in response.data]
