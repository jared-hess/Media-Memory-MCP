from __future__ import annotations

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider
from media_memory.core.models import MediaItem
from media_memory.core.vector_store import VectorStore
from media_memory.ingest.pipeline import IngestPipeline
from media_memory.subtitle_sources.local_sidecar import LocalSidecarSubtitleSource


class IngestService:
    def __init__(self, db: MediaMemoryDB, embeddings: EmbeddingProvider, vectors: VectorStore):
        self.db = db
        self.embeddings = embeddings
        self.vectors = vectors
        self.subtitle_source = LocalSidecarSubtitleSource()
        self.pipeline = IngestPipeline(
            db, embeddings, vectors, subtitle_source=self.subtitle_source
        )

    def ingest_media_items(self, items: list[MediaItem]) -> dict[str, int]:
        return self.pipeline.ingest_media_items(items)
