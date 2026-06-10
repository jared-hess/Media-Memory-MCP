from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.models import SubtitleChunk
from media_memory.core.search import SearchService


class ResultRankingTests(unittest.TestCase):
    def test_exact_phrase_subtitle_match_outranks_fuzzy_order_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            exact_media_id = db.upsert_media_item(path="/media/exact.mkv", title="Exact", kind="movie")
            fuzzy_media_id = db.upsert_media_item(path="/media/fuzzy.mkv", title="Fuzzy", kind="movie")
            db.insert_chunk(
                exact_media_id,
                SubtitleChunk(
                    media_path="/media/exact.mkv",
                    subtitle_path="/media/exact.srt",
                    text="May the force be with you",
                    start_ms=1000,
                    end_ms=3000,
                    source_kind="subtitle",
                ),
                text_hash="exact",
            )
            db.insert_chunk(
                fuzzy_media_id,
                SubtitleChunk(
                    media_path="/media/fuzzy.mkv",
                    subtitle_path="/media/fuzzy.srt",
                    text="May the force with you be",
                    start_ms=1000,
                    end_ms=3000,
                    source_kind="subtitle",
                ),
                text_hash="fuzzy",
            )

            results = SearchService(db).search_media("may the force be with you", limit=2)

            self.assertEqual(["/media/exact.mkv", "/media/fuzzy.mkv"], [result.media_path for result in results])
            self.assertTrue(any("exact phrase" in reason for reason in results[0].why))
            db.close()

    def test_plot_queries_favor_summary_metadata_chunks_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            summary_media_id = db.upsert_media_item(path="/media/summary.mkv", title="Summary Episode", kind="episode")
            subtitle_media_id = db.upsert_media_item(path="/media/subtitle.mkv", title="Subtitle Episode", kind="episode")
            db.insert_chunk(
                summary_media_id,
                SubtitleChunk(
                    media_path="/media/summary.mkv",
                    subtitle_path="/media/summary.json",
                    text="A revenge betrayal plot sends the crew into hiding",
                    source_kind="summary",
                ),
                text_hash="summary",
            )
            db.insert_chunk(
                subtitle_media_id,
                SubtitleChunk(
                    media_path="/media/subtitle.mkv",
                    subtitle_path="/media/subtitle.srt",
                    text="A revenge betrayal plot sends the crew into hiding",
                    start_ms=5000,
                    end_ms=7000,
                    source_kind="subtitle",
                ),
                text_hash="subtitle",
            )

            results = SearchService(db).find_episode("revenge betrayal plot", limit=2)

            self.assertEqual("/media/summary.mkv", results[0].media_path)
            self.assertTrue(any("summary source" in reason for reason in results[0].why))
            self.assertIsNone(results[0].evidences[0].start_ms)
            self.assertEqual("summary", results[0].evidences[0].source_kind)
            db.close()

    def test_dialogue_queries_favor_timestamped_subtitle_chunks_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            subtitle_media_id = db.upsert_media_item(path="/media/dialogue.mkv", title="Dialogue", kind="movie")
            summary_media_id = db.upsert_media_item(path="/media/timestamped-summary.mkv", title="Summary", kind="movie")
            db.insert_chunk(
                summary_media_id,
                SubtitleChunk(
                    media_path="/media/timestamped-summary.mkv",
                    subtitle_path="/media/timestamped-summary.json",
                    text="Open the pod bay doors please",
                    start_ms=1000,
                    end_ms=2000,
                    source_kind="summary",
                ),
                text_hash="summary",
            )
            db.insert_chunk(
                subtitle_media_id,
                SubtitleChunk(
                    media_path="/media/dialogue.mkv",
                    subtitle_path="/media/dialogue.srt",
                    text="Open the pod bay doors please",
                    start_ms=3000,
                    end_ms=4500,
                    source_kind="subtitle",
                ),
                text_hash="subtitle",
            )

            results = SearchService(db).search_dialogue("open the pod bay doors", limit=2)

            self.assertEqual("/media/dialogue.mkv", results[0]["media"]["path"])
            self.assertIn("subtitle source", str(results[0]["why"]))
            self.assertIn("timestamp metadata", str(results[0]["why"]))
            db.close()

    def test_malformed_wildcard_query_does_not_raise_fts_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/alpha.mkv", title="Alpha", kind="movie")
            db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/alpha.mkv",
                    subtitle_path="/media/alpha.srt",
                    text="alpha beta",
                    source_kind="subtitle",
                ),
                text_hash="alpha",
            )

            results = SearchService(db).search_media("alpha**", limit=2)

            self.assertEqual(1, len(results))
            self.assertEqual("/media/alpha.mkv", results[0].media_path)
            db.close()

    def test_provider_ids_do_not_create_unmatched_why_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/provider.mkv", title="Provider", kind="movie")
            db.conn.execute(
                "UPDATE media_items SET provider_ids_json = ? WHERE legacy_id = ?",
                ('{"imdb": "tt123"}', media_id),
            )
            db.conn.commit()
            db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/provider.mkv",
                    subtitle_path="/media/provider.srt",
                    text="quiet moon landing",
                    source_kind="subtitle",
                ),
                text_hash="provider",
            )

            results = SearchService(db).search_media("quiet moon", limit=1)

            self.assertFalse(any("provider" in reason for reason in results[0].why))
            db.close()


if __name__ == "__main__":
    unittest.main()
