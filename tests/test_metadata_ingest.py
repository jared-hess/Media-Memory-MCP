from __future__ import annotations

import json
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.models import MediaItem, SearchFilters
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceDBVectorStore
from media_memory.ingest.indexer import IngestService


def test_summary_sidecar_ingests_as_separate_untimestamped_document(tmp_path: Path) -> None:
    media_path = tmp_path / "Seinfeld.S07E01.The.Engagement.mkv"
    subtitle_path = tmp_path / "Seinfeld.S07E01.The.Engagement.srt"
    summary_path = tmp_path / "Seinfeld.S07E01.The.Engagement.summary.json"
    media_path.write_text("placeholder", encoding="utf-8")
    subtitle_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nJerry talks about coffee.\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "provider": "manual",
                "source_type": "summary",
                "summary": "George gets engaged to Susan while Jerry starts a new chapter.",
            }
        ),
        encoding="utf-8",
    )
    db = MediaMemoryDB(tmp_path / "media-memory.sqlite")
    db.init_schema()

    stats = IngestService(db, MockEmbeddingProvider(), LanceDBVectorStore()).ingest_media_items(
        [MediaItem(title="The Engagement", path=media_path, kind="unknown")]
    )

    assert stats["failed_jobs"] == 0
    assert db.count_documents() == 2
    summary = db.conn.execute(
        """
        SELECT c.start_ms, c.end_ms, c.source_kind, d.source_kind AS document_source_kind,
               d.provider_ids_json, d.checksum, d.media_item_id
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.text LIKE '%George gets engaged%'
        """
    ).fetchone()
    assert summary is not None
    assert summary["start_ms"] is None
    assert summary["end_ms"] is None
    assert summary["source_kind"] == "summary"
    assert summary["document_source_kind"] == "summary"
    assert json.loads(summary["provider_ids_json"]) == {"source_provider": "manual"}
    assert summary["checksum"] is not None
    assert summary["media_item_id"] is not None

    results = SearchService(db).search_media("George gets engaged", limit=1)
    assert results
    assert results[0].media_path == str(media_path)
    assert results[0].show_title == "Seinfeld"
    assert results[0].season == 7
    assert results[0].episode == 1
    evidence = results[0].evidences[0]
    assert evidence.start_ms is None
    assert evidence.end_ms is None
    assert evidence.source_kind == "summary"
    assert evidence.source_provider == "manual"
    assert evidence.source_path == str(summary_path)
    assert evidence.provider_ids == {"source_provider": "manual"}

    filtered = SearchService(db).search_media(
        "George gets engaged",
        filters=SearchFilters(show="Seinfeld", season=7, episode=1, source_provider="manual"),
    )
    assert [result.media_path for result in filtered] == [str(media_path)]
    db.close()


def test_metadata_query_does_not_match_subtitle_only_text(tmp_path: Path) -> None:
    media_path = tmp_path / "Seinfeld.S07E01.The.Engagement.mkv"
    subtitle_path = tmp_path / "Seinfeld.S07E01.The.Engagement.srt"
    media_path.write_text("placeholder", encoding="utf-8")
    subtitle_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nJerry talks about coffee.\n",
        encoding="utf-8",
    )
    db = MediaMemoryDB(tmp_path / "media-memory.sqlite")
    db.init_schema()

    IngestService(db, MockEmbeddingProvider(), LanceDBVectorStore()).ingest_media_items(
        [MediaItem(title="The Engagement", path=media_path, kind="unknown")]
    )

    assert SearchService(db).search_media("George gets engaged") == []
    db.close()
