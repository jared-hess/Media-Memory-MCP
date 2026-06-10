from __future__ import annotations

import unittest

from media_memory.core.models import SubtitleChunk
from media_memory.ingest.chunking import chunk_subtitles


class ChunkingTests(unittest.TestCase):
    def test_chunk_subtitles_merges_nearby_lines(self) -> None:
        chunks = [
            SubtitleChunk(media_path="m", subtitle_path="s", text="Hello", start_ms=0, end_ms=1000),
            SubtitleChunk(media_path="m", subtitle_path="s", text="world", start_ms=1200, end_ms=1800),
            SubtitleChunk(media_path="m", subtitle_path="s", text="later", start_ms=7000, end_ms=7500),
        ]
        merged = chunk_subtitles(chunks, max_chars=20, join_within_ms=3000)
        self.assertEqual(2, len(merged))
        self.assertEqual("Hello world", merged[0].text)
        self.assertEqual(1800, merged[0].end_ms)


if __name__ == "__main__":
    unittest.main()
