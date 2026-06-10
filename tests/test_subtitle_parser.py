from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.ingest.subtitle_parser import normalize_text, parse_subtitle_file


class SubtitleParserTests(unittest.TestCase):
    def test_parse_srt(self) -> None:
        body = """1
00:00:01,000 --> 00:00:02,500
Hello there.

2
00:00:03,000 --> 00:00:04,000
General Kenobi!
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.srt"
            path.write_text(body, encoding="utf-8")
            chunks = parse_subtitle_file(path, media_path="/media/movie.mkv")
        self.assertEqual(2, len(chunks))
        self.assertEqual("Hello there.", chunks[0].text)
        self.assertEqual(1000, chunks[0].start_ms)
        self.assertEqual(2500, chunks[0].end_ms)

    def test_normalize_text_removes_ass_markup(self) -> None:
        self.assertEqual("hello world", normalize_text("{\\i1}hello{\\i0}\\Nworld"))


if __name__ == "__main__":
    unittest.main()
