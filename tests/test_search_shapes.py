from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.models import SubtitleChunk
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceDBVectorStore


class SearchShapeTests(unittest.TestCase):
    def test_search_returns_structured_evidence(self) -> None:
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
            self.assertIsNotNone(chunk_id)

            embeddings = MockEmbeddingProvider()
            vectors = LanceDBVectorStore()
            vectors.upsert(int(chunk_id), embeddings.embed(chunk.text))
            search = SearchService(db, embeddings, vectors)

            results = search.search_media("go now", limit=5)
            self.assertTrue(results)
            payload = results[0].to_dict()
            self.assertIn("media_path", payload)
            self.assertIn("evidences", payload)
            self.assertIsInstance(payload["evidences"], list)
            self.assertIn("start_ms", payload["evidences"][0])
            self.assertIn("end_ms", payload["evidences"][0])
            db.close()


if __name__ == "__main__":
    unittest.main()
