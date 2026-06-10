from __future__ import annotations

import hashlib
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider
from media_memory.core.models import MediaItem, SubtitleChunk
from media_memory.core.vector_store import VectorStore
from media_memory.ingest.identify import identify_media_path
from media_memory.ingest.jobs import IngestJobState
from media_memory.metadata_sources.filename import FilenameMetadataSource, MetadataDocument
from media_memory.subtitle_sources.local import LocalSubtitleSource
from media_memory.subtitles.chunk import chunk_subtitles
from media_memory.subtitles.normalize import normalize_text
from media_memory.subtitles.parse import parse_subtitle_file


class IngestPipeline:
    """Resumable local ingest pipeline with per-target failure isolation."""

    def __init__(
        self,
        db: MediaMemoryDB,
        embeddings: EmbeddingProvider,
        vectors: VectorStore,
        *,
        subtitle_source: LocalSubtitleSource | None = None,
        metadata_sources: list[FilenameMetadataSource] | None = None,
    ) -> None:
        self.db = db
        self.embeddings = embeddings
        self.vectors = vectors
        self.subtitle_source = subtitle_source or LocalSubtitleSource()
        self.metadata_sources = metadata_sources or [FilenameMetadataSource()]

    def ingest_media_items(self, items: list[MediaItem]) -> dict[str, int]:
        stats = {
            "media_items": 0,
            "documents": 0,
            "new_chunks": 0,
            "jobs": 0,
            "failed_jobs": 0,
        }
        seen_jobs: set[str] = set()
        for item in items:
            stats["media_items"] += 1
            try:
                refined_item, media_id = self._prepare_media(item, seen_jobs)
                metadata_documents = self._find_metadata_documents(refined_item)
                for document in metadata_documents:
                    before_documents = self.db.count_documents()
                    new_chunks, failed = self._ingest_metadata_document(
                        refined_item, media_id, document, seen_jobs
                    )
                    stats["new_chunks"] += new_chunks
                    stats["failed_jobs"] += failed
                    if self.db.count_documents() > before_documents:
                        stats["documents"] += 1
                subtitle_paths = self.subtitle_source.find_for_media(refined_item)
                if not subtitle_paths and not metadata_documents:
                    job_id = self._record(
                        IngestJobState.INDEXED,
                        media_item_id=media_id,
                        media_path=str(refined_item.path),
                        completed=True,
                    )
                    seen_jobs.add(job_id)
                    continue
                for subtitle_path in subtitle_paths:
                    before_documents = self.db.count_documents()
                    new_chunks, failed = self._ingest_subtitle(
                        refined_item, media_id, Path(subtitle_path), seen_jobs
                    )
                    stats["new_chunks"] += new_chunks
                    stats["failed_jobs"] += failed
                    if self.db.count_documents() > before_documents:
                        stats["documents"] += 1
            except Exception as exc:  # noqa: BLE001 - failures are isolated and recorded per item.
                job_id = self._record(
                    IngestJobState.FAILED,
                    media_path=str(item.path),
                    error=str(exc),
                    completed=True,
                )
                seen_jobs.add(job_id)
                stats["failed_jobs"] += 1
                continue
        stats["jobs"] = len(seen_jobs)
        return stats

    def _prepare_media(self, item: MediaItem, seen_jobs: set[str]) -> tuple[MediaItem, int]:
        if not item.path.exists():
            raise FileNotFoundError(f"Media file does not exist: {item.path}")
        discovered_job = self._record(IngestJobState.DISCOVERED, media_path=str(item.path))
        seen_jobs.add(discovered_job)
        refined = _refine_media_item(item)
        identified_job = self._record(IngestJobState.IDENTIFIED, media_path=str(refined.path))
        seen_jobs.add(identified_job)
        media_id = self.db.upsert_media_item(
            path=str(refined.path),
            title=refined.title,
            kind=refined.kind,
            season=refined.season,
            episode=refined.episode,
            show_title=refined.show_title,
            season_number=refined.season_number,
            episode_number=refined.episode_number,
            episode_title=refined.episode_title,
            year=refined.year,
            runtime_seconds=refined.runtime_seconds,
            provider_ids=refined.provider_ids,
            provider_refs=[ref.model_dump(mode="json") for ref in refined.provider_refs],
            corpus_id=refined.corpus_id,
        )
        metadata_job = self._record(
            IngestJobState.METADATA_ENRICHED,
            media_item_id=media_id,
            media_path=str(refined.path),
        )
        seen_jobs.add(metadata_job)
        return refined, media_id

    def _ingest_subtitle(
        self,
        item: MediaItem,
        media_id: int,
        subtitle_path: Path,
        seen_jobs: set[str],
    ) -> tuple[int, int]:
        try:
            found_job = self._record(
                IngestJobState.SUBTITLE_FOUND,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(subtitle_path),
            )
            seen_jobs.add(found_job)
            fetched_path = self.subtitle_source.fetch(subtitle_path)
            downloaded_job = self._record(
                IngestJobState.SUBTITLE_DOWNLOADED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(fetched_path),
            )
            seen_jobs.add(downloaded_job)
            subtitle_checksum = _file_sha256(fetched_path)
            parsed = parse_subtitle_file(
                fetched_path,
                media_path=str(item.path),
                season=item.season,
                episode=item.episode,
            )
            if not parsed:
                raise ValueError(f"No parseable subtitle cues found in {fetched_path}")
            parsed_job = self._record(
                IngestJobState.SUBTITLE_PARSED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(fetched_path),
            )
            seen_jobs.add(parsed_job)
            chunks = chunk_subtitles(parsed)
            if not chunks:
                raise ValueError(f"No searchable subtitle chunks produced for {fetched_path}")
            chunked_job = self._record(
                IngestJobState.CHUNKED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(fetched_path),
            )
            seen_jobs.add(chunked_job)
            new_chunks = self._index_chunks(media_id, chunks, subtitle_checksum)
            embedded_job = self._record(
                IngestJobState.EMBEDDED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(fetched_path),
            )
            seen_jobs.add(embedded_job)
            indexed_job = self._record(
                IngestJobState.INDEXED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(fetched_path),
                completed=True,
            )
            seen_jobs.add(indexed_job)
            return new_chunks, 0
        except Exception as exc:  # noqa: BLE001 - one bad subtitle must not abort a batch.
            failed_job = self._record(
                IngestJobState.FAILED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=str(subtitle_path),
                error=str(exc),
                completed=True,
            )
            seen_jobs.add(failed_job)
            return 0, 1

    def _find_metadata_documents(self, item: MediaItem) -> list[MetadataDocument]:
        documents: list[MetadataDocument] = []
        for source in self.metadata_sources:
            documents.extend(source.find_documents(item))
        return documents

    def _ingest_metadata_document(
        self,
        item: MediaItem,
        media_id: int,
        document: MetadataDocument,
        seen_jobs: set[str],
    ) -> tuple[int, int]:
        try:
            source_path = Path(document.source_path)
            checksum = document.checksum or (
                _file_sha256(source_path) if source_path.exists() else _text_sha256(document.text)
            )
            chunk = SubtitleChunk(
                media_path=str(item.path),
                subtitle_path=document.source_path,
                text=document.text,
                season=item.season,
                episode=item.episode,
                source_kind=document.source_kind,
            )
            text_hash = _text_sha256(document.text)
            chunk_id = self.db.insert_chunk(
                media_id,
                chunk,
                text_hash,
                document_checksum=checksum,
                provider_ids=document.provider_ids,
                provider_refs=document.provider_refs,
            )
            if chunk_id is not None:
                metadata_row = self.db.get_chunk_vector_metadata(chunk_id)
                metadata = dict(metadata_row) if metadata_row is not None else {}
                self.vectors.upsert(chunk_id, self.embeddings.embed(document.text), metadata)
            indexed_job = self._record(
                IngestJobState.INDEXED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=document.source_path,
                completed=True,
            )
            seen_jobs.add(indexed_job)
            return (1 if chunk_id is not None else 0), 0
        except Exception as exc:  # noqa: BLE001 - metadata sidecars must be isolated like subtitles.
            failed_job = self._record(
                IngestJobState.FAILED,
                media_item_id=media_id,
                media_path=str(item.path),
                source_path=document.source_path,
                error=str(exc),
                completed=True,
            )
            seen_jobs.add(failed_job)
            return 0, 1

    def _index_chunks(
        self, media_id: int, chunks: list[SubtitleChunk], subtitle_checksum: str
    ) -> int:
        new_chunks = 0
        for chunk in chunks:
            text_hash = _text_sha256(chunk.text)
            chunk_id = self.db.insert_chunk(
                media_id, chunk, text_hash, document_checksum=subtitle_checksum
            )
            if chunk_id is None:
                continue
            metadata_row = self.db.get_chunk_vector_metadata(chunk_id)
            metadata = dict(metadata_row) if metadata_row is not None else {}
            self.vectors.upsert(chunk_id, self.embeddings.embed(chunk.text), metadata)
            new_chunks += 1
        return new_chunks

    def _record(
        self,
        state: IngestJobState,
        *,
        media_item_id: int | str | None = None,
        media_path: str | None = None,
        source_path: str | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> str:
        return self.db.upsert_ingest_job(
            status=state.value,
            media_item_id=media_item_id,
            media_path=media_path,
            source_path=source_path,
            error=error,
            completed=completed,
        )


def _refine_media_item(item: MediaItem) -> MediaItem:
    identified = identify_media_path(item.path, corpus_id=item.corpus_id)
    return item.model_copy(
        update={
            "kind": item.kind if item.kind != "unknown" else identified.kind,
            "season": item.season if item.season is not None else identified.season,
            "episode": item.episode if item.episode is not None else identified.episode,
            "show_title": item.show_title or identified.show_title,
            "season_number": item.season_number
            if item.season_number is not None
            else identified.season_number,
            "episode_number": item.episode_number
            if item.episode_number is not None
            else identified.episode_number,
            "episode_title": item.episode_title or identified.episode_title,
            "year": item.year if item.year is not None else identified.year,
        }
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
