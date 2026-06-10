from __future__ import annotations

import hashlib
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider
from media_memory.core.models import MediaItem
from media_memory.core.vector_store import VectorStore
from media_memory.ingest.chunking import chunk_subtitles
from media_memory.ingest.subtitle_parser import parse_subtitle_file
from media_memory.subtitle_sources.local_sidecar import LocalSidecarSubtitleSource


class IngestService:
    def __init__(self, db: MediaMemoryDB, embeddings: EmbeddingProvider, vectors: VectorStore):
        self.db = db
        self.embeddings = embeddings
        self.vectors = vectors
        self.subtitle_source = LocalSidecarSubtitleSource()

    def ingest_media_items(self, items: list[MediaItem]) -> dict[str, int]:
        media_count = 0
        chunk_count = 0
        for item in items:
            media_count += 1
            media_id = self.db.upsert_media_item(
                path=str(item.path),
                title=item.title,
                kind=item.kind,
                season=item.season,
                episode=item.episode,
            )
            subtitle_paths = self.subtitle_source.find_for_media(item)
            for subtitle_path in subtitle_paths:
                parsed = parse_subtitle_file(
                    Path(subtitle_path),
                    media_path=str(item.path),
                    season=item.season,
                    episode=item.episode,
                )
                merged_chunks = chunk_subtitles(parsed)
                for chunk in merged_chunks:
                    text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
                    chunk_id = self.db.insert_chunk(media_id, chunk, text_hash)
                    if chunk_id is None:
                        continue
                    self.vectors.upsert(chunk_id, self.embeddings.embed(chunk.text))
                    chunk_count += 1
        return {"media_items": media_count, "new_chunks": chunk_count}
