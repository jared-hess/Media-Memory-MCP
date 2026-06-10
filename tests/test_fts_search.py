from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from media_memory.core.db import MediaMemoryDB, SCHEMA_VERSION
from media_memory.core.models import SearchFilters, SubtitleChunk
from media_memory.core.search import SearchService


class ExplodingEmbeddings:
    def embed(self, text: str) -> list[float]:
        _ = text
        raise AssertionError("search path must not embed queries")


class ExplodingVectors:
    def search(self, vector: list[float], limit: int = 10) -> list[tuple[int, float]]:
        _ = (vector, limit)
        raise AssertionError("search path must not query vector store")


class FTSSearchTests(unittest.TestCase):
    def test_schema_has_canonical_tables_version_foreign_keys_and_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()

            tables = {
                row["name"]
                for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
                )
            }
            for table in {"media_items", "documents", "chunks", "ingest_jobs", "search_cache", "chunks_fts"}:
                self.assertIn(table, tables)

            self.assertEqual(1, db.conn.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual(SCHEMA_VERSION, db.conn.execute("PRAGMA user_version").fetchone()[0])

            media_columns = self._column_types(db.conn, "media_items")
            self.assertEqual("TEXT", media_columns["id"])
            self.assertIn("corpus_id", media_columns)
            chunk_columns = self._column_types(db.conn, "chunks")
            self.assertEqual("TEXT", chunk_columns["id"])
            self.assertIn("corpus_id", chunk_columns)
            self.assertIn("document_id", chunk_columns)
            self.assertIn("media_item_id", chunk_columns)

            fts_sql = db.conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'"
            ).fetchone()["sql"]
            self.assertIn("tokenize='porter unicode61'", fts_sql)
            db.close()

    def test_legacy_compatibility_methods_use_canonical_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/Show.S01E01.mkv", title="Show S01E01", kind="episode")
            chunk = SubtitleChunk(
                media_path="/media/Show.S01E01.mkv",
                subtitle_path="/media/Show.S01E01.srt",
                text="We need to go now",
                start_ms=1000,
                end_ms=3000,
            )

            chunk_id = db.insert_chunk(media_id, chunk, text_hash="hash-1")

            self.assertIsInstance(media_id, int)
            self.assertIsInstance(chunk_id, int)
            stored = db.conn.execute("SELECT * FROM chunks").fetchone()
            self.assertTrue(stored["id"].startswith("v1:chunk:local:"))
            self.assertEqual("local", stored["corpus_id"])
            self.assertTrue(stored["document_id"].startswith("v1:doc:local:"))

            rows = db.lexical_search("go now")
            self.assertEqual(1, len(rows))
            self.assertEqual(chunk_id, rows[0]["chunk_id"])
            self.assertEqual("/media/Show.S01E01.mkv", rows[0]["media_path"])
            self.assertEqual("Show S01E01", rows[0]["title"])
            self.assertEqual("We need to go now", rows[0]["text"])
            self.assertEqual(1000, rows[0]["start_ms"])
            self.assertEqual(3000, rows[0]["end_ms"])
            self.assertGreater(rows[0]["lexical_score"], 0.0)

            self.assertEqual(chunk_id, db.get_chunk_by_id(int(chunk_id))["chunk_id"])
            self.assertEqual(chunk_id, db.list_chunks_for_media("/media/Show.S01E01.mkv")[0]["chunk_id"])
            self.assertEqual(chunk_id, db.list_all_chunks()[0]["chunk_id"])
            db.close()

    def test_chunks_fts_is_rebuildable_from_canonical_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/Movie.mkv", title="Movie", kind="movie")
            first_id = db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/Movie.mkv",
                    subtitle_path="/media/Movie.srt",
                    text="Running quickly through memories",
                    start_ms=500,
                    end_ms=1500,
                ),
                text_hash="hash-1",
            )
            second_id = db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/Movie.mkv",
                    subtitle_path="/media/Movie.srt",
                    text="A quiet unrelated line",
                    start_ms=2000,
                    end_ms=3000,
                ),
                text_hash="hash-2",
            )

            db.conn.execute("DELETE FROM chunks_fts")
            db.conn.commit()
            self.assertEqual([], db.lexical_search("running"))

            db.rebuild_fts_index()

            rows = db.lexical_search("run")
            self.assertEqual(1, len(rows))
            self.assertEqual(first_id, rows[0]["chunk_id"])
            self.assertEqual([first_id, second_id], [row["chunk_id"] for row in db.list_all_chunks()])
            db.close()

    def test_search_service_uses_fts_only_with_quote_filters_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            local_media = db.upsert_media_item(path="/media/Show.S01E01.mkv", title="Pilot", kind="episode")
            other_media = db.upsert_media_item(
                path="/archive/Show.S01E02.mkv",
                title="Second Episode",
                kind="episode",
                corpus_id="archive",
            )
            db.insert_chunk(
                local_media,
                SubtitleChunk(
                    media_path="/media/Show.S01E01.mkv",
                    subtitle_path="/media/Show.S01E01.srt",
                    text="The blue door opens for the pilot",
                    start_ms=1000,
                    end_ms=2000,
                ),
                text_hash="hash-quote-1",
            )
            db.insert_chunk(
                local_media,
                SubtitleChunk(
                    media_path="/media/Show.S01E01.mkv",
                    subtitle_path="/media/Show.S01E01.srt",
                    text="The blue metal door stays closed",
                    start_ms=3000,
                    end_ms=4000,
                ),
                text_hash="hash-quote-2",
            )
            db.insert_chunk(
                other_media,
                SubtitleChunk(
                    media_path="/archive/Show.S01E02.mkv",
                    subtitle_path="/archive/Show.S01E02.srt",
                    text="The blue door opens in the archive",
                    start_ms=1000,
                    end_ms=2000,
                ),
                text_hash="hash-archive",
            )
            db.conn.execute(
                "UPDATE media_items SET show_title = ?, provider_ids_json = ? WHERE path = ?",
                ('Example Show', '{"imdb":"tt-local"}', "/media/Show.S01E01.mkv"),
            )
            db.conn.commit()
            search = SearchService(db, ExplodingEmbeddings(), ExplodingVectors())  # type: ignore[arg-type]

            results = search.search_media(
                '  "Blue Door"  ',
                filters=SearchFilters(show="Example", provider_ids={"imdb": "tt-local"}, limit=5),
            )

            self.assertEqual(1, len(results))
            self.assertEqual("/media/Show.S01E01.mkv", results[0].media_path)
            self.assertEqual(0.0, results[0].vector_score)
            self.assertIn("blue door", results[0].evidences[0].text.casefold())
            self.assertNotIn("metal", results[0].evidences[0].text.casefold())
            self.assertEqual(1, db.conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0])
            cached = search.search_media('"blue door"', filters=SearchFilters(show="Example", provider_ids={"imdb": "tt-local"}, limit=5))
            self.assertEqual(results[0].media_path, cached[0].media_path)
            db.close()

    def test_find_episode_prefers_summary_and_dialogue_prefers_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/Show.S01E03.mkv", title="Mystery", kind="episode")
            db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/Show.S01E03.mkv",
                    subtitle_path="/media/Show.S01E03.summary.txt",
                    text="Project Blue is revealed in the episode summary",
                    source_kind="summary",
                ),
                text_hash="summary",
            )
            db.insert_chunk(
                media_id,
                SubtitleChunk(
                    media_path="/media/Show.S01E03.mkv",
                    subtitle_path="/media/Show.S01E03.srt",
                    text="Project Blue is mentioned in dialogue",
                    start_ms=5000,
                    end_ms=6500,
                    source_kind="subtitle",
                ),
                text_hash="subtitle",
            )
            search = SearchService(db)

            episodes = search.find_episode("project blue")
            scenes = search.search_dialogue("project blue")

            self.assertEqual("summary", episodes[0].evidences[0].subtitle_path.split(".")[-2])
            self.assertEqual(5000, scenes[0]["evidence"]["start_ms"])
            self.assertIn("query", scenes[0])
            self.assertIn("results", scenes[0])
            self.assertIn("confidence", scenes[0])
            self.assertIn("why", scenes[0])
            self.assertIn("evidence", scenes[0])
            db.close()

    @staticmethod
    def _column_types(conn: sqlite3.Connection, table: str) -> dict[str, str]:
        return {row["name"]: row["type"] for row in conn.execute(f"PRAGMA table_info({table})")}


if __name__ == "__main__":
    unittest.main()
