from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.ingest.subtitle_parser import normalize_text as legacy_normalize_text
from media_memory.ingest.subtitle_parser import parse_subtitle_file as legacy_parse_subtitle_file
from media_memory.subtitles.normalize import normalize_text
from media_memory.subtitles.parse import parse_subtitle_file


class SubtitleParseTests(unittest.TestCase):
    def test_parse_srt(self) -> None:
        chunks = self._parse(
            "sample.srt",
            """1
00:00:01,000 --> 00:00:02,500
<i>Hello</i> there.

2
00:00:03,000 --> 00:00:04,000
General Kenobi!
""",
        )

        self.assertEqual(2, len(chunks))
        self.assertEqual("Hello there.", chunks[0].text)
        self.assertEqual(1000, chunks[0].start_ms)
        self.assertEqual(2500, chunks[0].end_ms)
        self.assertEqual("General Kenobi!", chunks[1].text)

    def test_parse_vtt_with_cue_identifier(self) -> None:
        chunks = self._parse(
            "sample.vtt",
            """WEBVTT

cue-1
00:00:05.000 --> 00:00:06.250 align:start
Hello <b>VTT</b>.

00:00:07.000 --> 00:00:08.000
Second cue.
""",
        )

        self.assertEqual(2, len(chunks))
        self.assertEqual("Hello VTT.", chunks[0].text)
        self.assertEqual(5000, chunks[0].start_ms)
        self.assertEqual(6250, chunks[0].end_ms)

    def test_parse_ass_and_ssa_dialogue(self) -> None:
        ass_body = """[Script Info]
Title: sample

[Events]
Dialogue: 0,0:00:01.20,0:00:03.45,Default,,0,0,0,,{\\i1}Hello\\NASS{\\i0}
"""
        for name in ("sample.ass", "sample.ssa"):
            with self.subTest(name=name):
                chunks = self._parse(name, ass_body)
                self.assertEqual(1, len(chunks))
                self.assertEqual("Hello ASS", chunks[0].text)
                self.assertEqual(1200, chunks[0].start_ms)
                self.assertEqual(3450, chunks[0].end_ms)

    def test_parse_ass_skips_unreasonably_large_timestamps(self) -> None:
        chunks = self._parse(
            "sample.ass",
            "Dialogue: 0,999999:00:00.00,999999:00:01.00,Default,,0,0,0,,Too long\n",
        )

        self.assertEqual([], chunks)

    def test_normalize_text_strips_markup_noise_and_repeated_lines(self) -> None:
        value = """<i>{\\i1}Hello&nbsp; world{\\i0}</i>
[music]
♪  theme song  ♪
theme song
theme song
"""

        self.assertEqual("Hello world theme song", normalize_text(value))

    def test_legacy_imports_delegate_to_new_parser(self) -> None:
        self.assertIs(legacy_parse_subtitle_file, parse_subtitle_file)
        self.assertIs(legacy_normalize_text, normalize_text)

    def _parse(self, filename: str, body: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / filename
            path.write_text(body, encoding="utf-8")
            return parse_subtitle_file(path, media_path="/media/sample.mkv", season=7, episode=1)


if __name__ == "__main__":
    unittest.main()
