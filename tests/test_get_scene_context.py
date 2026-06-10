from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.models import SubtitleChunk
from media_memory.core.search import SearchService


class SceneContextTests(unittest.TestCase):
    def test_get_scene_context_returns_before_current_and_after_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MediaMemoryDB(Path(tmp) / "test.db")
            db.init_schema()
            media_id = db.upsert_media_item(path="/media/Movie.mkv", title="Movie", kind="movie")
            chunk_ids: list[int] = []
            for index, text in enumerate(["before one", "before two", "target line", "after one", "after two"]):
                chunk_id = db.insert_chunk(
                    media_id,
                    SubtitleChunk(
                        media_path="/media/Movie.mkv",
                        subtitle_path="/media/Movie.srt",
                        text=text,
                        start_ms=index * 1000,
                        end_ms=index * 1000 + 900,
                    ),
                    text_hash=f"hash-{index}",
                )
                self.assertIsNotNone(chunk_id)
                chunk_ids.append(int(chunk_id))
            search = SearchService(db)

            context = search.get_scene_context(chunk_ids[2], window=2)

            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(["before one", "before two"], [item["text"] for item in context["before"]])
            self.assertEqual("target line", context["current"]["text"])
            self.assertEqual(["after one", "after two"], [item["text"] for item in context["after"]])
            self.assertEqual(5, len(context["evidence"]))
            self.assertIn("target line", context["context"])
            db.close()


if __name__ == "__main__":
    unittest.main()
