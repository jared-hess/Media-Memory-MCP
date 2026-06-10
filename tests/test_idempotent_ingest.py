from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.models import MediaItem
from media_memory.core.vector_store import LanceDBVectorStore
from media_memory.ingest.indexer import IngestService
from media_memory.ingest.jobs import INGEST_JOB_STATES, IngestJobState
from media_memory.ingest.pipeline import IngestPipeline


class IdempotentIngestTests(unittest.TestCase):
    def test_ingest_rerun_keeps_counts_and_returns_zero_new_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_path = root / "Example.Show.S01E01.Pilot.mkv"
            subtitle_path = root / "Example.Show.S01E01.Pilot.en.srt"
            media_path.write_text("", encoding="utf-8")
            subtitle_path.write_text(
                _srt_text("We need a deterministic subtitle fixture for idempotent ingest."),
                encoding="utf-8",
            )
            db = _db(root)
            service = IngestService(db, MockEmbeddingProvider(), LanceDBVectorStore())
            item = MediaItem(title="Explicit Pilot", path=media_path, kind="unknown")

            first = service.ingest_media_items([item])
            first_counts = (db.count_media_items(), db.count_documents(), db.count_chunks())
            second = service.ingest_media_items([item])
            second_counts = (db.count_media_items(), db.count_documents(), db.count_chunks())

            self.assertEqual(1, first["media_items"])
            self.assertGreater(first["new_chunks"], 0)
            self.assertEqual(0, second["new_chunks"])
            self.assertEqual(first_counts, second_counts)
            self.assertEqual((1, 1, first["new_chunks"]), first_counts)
            self.assertEqual(0, second["failed_jobs"])
            self.assertGreaterEqual(second["jobs"], 3)
            stored_media = db.conn.execute(
                "SELECT title, kind, season, episode FROM media_items"
            ).fetchone()
            self.assertEqual("Explicit Pilot", stored_media["title"])
            self.assertEqual("episode", stored_media["kind"])
            self.assertEqual(1, stored_media["season"])
            self.assertEqual(1, stored_media["episode"])
            stored_chunk = db.conn.execute("SELECT season, episode FROM chunks").fetchone()
            self.assertEqual(1, stored_chunk["season"])
            self.assertEqual(1, stored_chunk["episode"])
            document = db.conn.execute("SELECT checksum FROM documents").fetchone()
            self.assertIsNotNone(document["checksum"])
            self.assertEqual(64, len(document["checksum"]))
            self.assertIn(
                "deterministic", [row["text"] for row in db.lexical_search("deterministic")][0]
            )
            self.assertEqual(INGEST_JOB_STATES, tuple(state.value for state in IngestJobState))
            self.assertTrue(_history_contains(db, IngestJobState.INDEXED))
            db.close()

    def test_bad_subtitle_records_failed_job_without_aborting_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_path = root / "Movie.Name.1999.mkv"
            bad_subtitle = root / "Movie.Name.1999.bad.srt"
            good_subtitle = root / "Movie.Name.1999.en.srt"
            media_path.write_text("", encoding="utf-8")
            bad_subtitle.write_text("this is not parseable subtitle content", encoding="utf-8")
            good_subtitle.write_text(
                _srt_text("The good subtitle should still be indexed after a bad sidecar."),
                encoding="utf-8",
            )
            db = _db(root)
            pipeline = IngestPipeline(db, MockEmbeddingProvider(), LanceDBVectorStore())

            stats = pipeline.ingest_media_items(
                [MediaItem(title="Movie Name", path=media_path, kind="movie")]
            )

            self.assertEqual(1, stats["media_items"])
            self.assertEqual(1, stats["failed_jobs"])
            self.assertGreater(stats["new_chunks"], 0)
            self.assertEqual(1, db.count_ingest_jobs(status=IngestJobState.FAILED.value))
            self.assertEqual(1, db.count_documents())
            self.assertEqual(stats["new_chunks"], db.count_chunks())
            failed_job = db.conn.execute(
                "SELECT source_path, error FROM ingest_jobs WHERE status = ?",
                (IngestJobState.FAILED.value,),
            ).fetchone()
            self.assertEqual(str(bad_subtitle), failed_job["source_path"])
            self.assertIn("No parseable subtitle cues", failed_job["error"])
            self.assertTrue(_history_contains(db, IngestJobState.FAILED))
            self.assertTrue(_history_contains(db, IngestJobState.INDEXED))
            db.close()

    def test_missing_media_records_failed_job_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good_media = root / "Good.Movie.2001.mkv"
            good_subtitle = root / "Good.Movie.2001.srt"
            missing_media = root / "Missing.Movie.2002.mkv"
            good_media.write_text("", encoding="utf-8")
            good_subtitle.write_text(
                _srt_text("The present media item should still be searchable."), encoding="utf-8"
            )
            db = _db(root)
            service = IngestService(db, MockEmbeddingProvider(), LanceDBVectorStore())

            stats = service.ingest_media_items(
                [
                    MediaItem(title="Missing Movie", path=missing_media, kind="movie"),
                    MediaItem(title="Good Movie", path=good_media, kind="movie"),
                ]
            )

            self.assertEqual(2, stats["media_items"])
            self.assertEqual(1, stats["failed_jobs"])
            self.assertGreater(stats["new_chunks"], 0)
            self.assertEqual(1, db.count_media_items())
            failed_job = db.conn.execute(
                "SELECT media_path, error FROM ingest_jobs WHERE status = 'failed'"
            ).fetchone()
            self.assertEqual(str(missing_media), failed_job["media_path"])
            self.assertIn("does not exist", failed_job["error"])
            db.close()


def _db(root: Path) -> MediaMemoryDB:
    db = MediaMemoryDB(root / "media-memory.db")
    db.init_schema()
    return db


def _srt_text(sentence: str) -> str:
    return f"""1
00:00:01,000 --> 00:00:03,000
{sentence}

2
00:00:04,000 --> 00:00:06,000
Another line gives the chunker enough nearby subtitle content to merge.
"""


def _history_contains(db: MediaMemoryDB, state: IngestJobState) -> bool:
    for row in db.list_ingest_jobs():
        history = json.loads(row["state_history_json"])
        if any(entry["status"] == state.value for entry in history):
            return True
    return False
