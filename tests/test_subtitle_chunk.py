from __future__ import annotations

import unittest

from media_memory.core.models import SubtitleChunk
from media_memory.ingest.chunking import chunk_subtitles as legacy_chunk_subtitles
from media_memory.subtitles.chunk import chunk_subtitles


class SubtitleChunkTests(unittest.TestCase):
    def test_time_window_chunking_preserves_overlapping_timestamps(self) -> None:
        chunks = [
            self._chunk("First line " * 4, 0, 10_000),
            self._chunk("Second line " * 4, 50_000, 55_000),
            self._chunk("Third line " * 4, 65_000, 70_000),
        ]

        windows = chunk_subtitles(chunks)

        self.assertEqual(2, len(windows))
        self.assertEqual(0, windows[0].start_ms)
        self.assertEqual(55_000, windows[0].end_ms)
        self.assertIn("First line", windows[0].text)
        self.assertIn("Second line", windows[0].text)
        self.assertEqual(50_000, windows[1].start_ms)
        self.assertEqual(70_000, windows[1].end_ms)
        self.assertIn("Second line", windows[1].text)
        self.assertIn("Third line", windows[1].text)

    def test_time_window_chunking_respects_max_chars(self) -> None:
        chunks = [
            self._chunk("alpha " * 10, 0, 1000),
            self._chunk("beta " * 10, 2000, 3000),
        ]

        windows = chunk_subtitles(chunks, max_chars=80, min_chars=1)

        self.assertEqual(1, len(windows))
        self.assertIn("alpha", windows[0].text)
        self.assertNotIn("beta", windows[0].text)

    def test_legacy_wrapper_preserves_nearby_merge_behavior(self) -> None:
        chunks = [
            self._chunk("Hello", 0, 1000),
            self._chunk("world", 1200, 1800),
            self._chunk("later", 7000, 7500),
        ]

        merged = legacy_chunk_subtitles(chunks, max_chars=20, join_within_ms=3000)

        self.assertEqual(2, len(merged))
        self.assertEqual("Hello world", merged[0].text)
        self.assertEqual(1800, merged[0].end_ms)

    def test_time_window_chunking_rejects_invalid_options(self) -> None:
        chunks = [self._chunk("Hello", 0, 1000)]

        with self.assertRaises(ValueError):
            chunk_subtitles(chunks, window_seconds=0)
        with self.assertRaises(ValueError):
            chunk_subtitles(chunks, window_seconds=60, overlap_seconds=60)
        with self.assertRaises(ValueError):
            chunk_subtitles(chunks, overlap_seconds=-1)
        with self.assertRaises(ValueError):
            chunk_subtitles(chunks, min_chars=-1)
        with self.assertRaises(ValueError):
            chunk_subtitles(chunks, max_chars=0)

    def test_legacy_chunking_rejects_invalid_options(self) -> None:
        chunks = [self._chunk("Hello", 0, 1000)]

        with self.assertRaises(ValueError):
            legacy_chunk_subtitles(chunks, max_chars=0)
        with self.assertRaises(ValueError):
            legacy_chunk_subtitles(chunks, join_within_ms=-1)

    def _chunk(self, text: str, start_ms: int, end_ms: int) -> SubtitleChunk:
        return SubtitleChunk(media_path="m", subtitle_path="s", text=text, start_ms=start_ms, end_ms=end_ms)


if __name__ == "__main__":
    unittest.main()
