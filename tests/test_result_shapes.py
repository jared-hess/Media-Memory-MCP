from __future__ import annotations

import unittest
from pathlib import Path

from media_memory.core.models import (
    Chunk,
    Document,
    IngestJob,
    MediaItem,
    SearchEvidence,
    SearchFilters,
    SearchResult,
    SubtitleChunk,
)


class ResultShapeTests(unittest.TestCase):
    def test_legacy_search_result_to_dict_shape_is_preserved(self) -> None:
        result = SearchResult(
            media_path="/media/movie.mkv",
            title="Movie",
            combined_score=0.9,
            lexical_score=0.8,
            vector_score=0.7,
            evidences=[
                SearchEvidence(
                    chunk_id=1,
                    text="hello there",
                    score=0.9,
                    start_ms=1000,
                    end_ms=2500,
                )
            ],
        )

        payload = result.to_dict()

        self.assertEqual("/media/movie.mkv", payload["media_path"])
        self.assertEqual("local", payload["corpus_id"])
        self.assertIn("evidences", payload)
        self.assertNotIn("evidence", payload)
        self.assertEqual(1, payload["evidences"][0]["chunk_id"])
        self.assertEqual("hello there", payload["evidences"][0]["text"])
        self.assertEqual(0.9, payload["evidences"][0]["score"])
        self.assertEqual(1000, payload["evidences"][0]["start_ms"])
        self.assertEqual(2500, payload["evidences"][0]["end_ms"])
        self.assertIn("confidence", payload)
        self.assertIn("why", payload)

    def test_legacy_search_result_positional_constructor_still_works(self) -> None:
        result = SearchResult(
            "/media/movie.mkv",
            "Movie",
            0.9,
            0.8,
            0.0,
            [SearchEvidence(chunk_id=1, text="hello", score=0.9, start_ms=None, end_ms=None)],
        )

        self.assertEqual("/media/movie.mkv", result.media_path)
        self.assertEqual(0.0, result.vector_score)
        self.assertEqual("hello", result.evidences[0].text)

    def test_legacy_constructors_and_path_behavior_still_work(self) -> None:
        item = MediaItem(
            title="Show S01E01",
            path=Path("/media/Show.S01E01.mkv"),
            kind="episode",
            season=1,
            episode=1,
        )
        chunk = SubtitleChunk(
            media_path=str(item.path),
            subtitle_path="/media/Show.S01E01.srt",
            text="we need to go",
            start_ms=1000,
            end_ms=3000,
            season=item.season,
            episode=item.episode,
        )

        self.assertEqual(Path("/media"), item.path.parent)
        self.assertEqual("Show.S01E01", item.path.stem)
        self.assertIsInstance(chunk, Chunk)
        self.assertEqual("local", item.corpus_id)
        self.assertEqual("local", chunk.corpus_id)

    def test_new_domain_models_carry_corpus_ids(self) -> None:
        document = Document(media_id="media-1", source_path="/media/movie.srt")
        filters = SearchFilters(kind="episode", season=1)
        job = IngestJob(media_id="media-1", source_path="/media/movie.srt")

        self.assertEqual("local", document.corpus_id)
        self.assertEqual("local", filters.corpus_id)
        self.assertEqual("local", job.corpus_id)
        self.assertEqual("pending", job.status)


if __name__ == "__main__":
    unittest.main()
