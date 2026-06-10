from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from media_memory.core.errors import ProviderError
from media_memory.core.models import MediaItem
from media_memory.subtitle_sources.embedded import EmbeddedSubtitleSource


class FakeCommandRunner:
    def __init__(self, *, extract_content: str = "1\n00:00:01,000 --> 00:00:02,000\nEmbedded line.\n") -> None:
        self.extract_content = extract_content
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"streams": [{"index": 2, "tags": {"language": "eng", "title": "English"}}]}), stderr="")
        if command[0] == "ffmpeg":
            Path(command[-1]).write_text(self.extract_content, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")


class FailingCommandRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        del command
        self.calls += 1
        raise AssertionError("Disabled embedded subtitles should not invoke ffprobe or ffmpeg")


def test_disabled_embedded_subtitles_perform_zero_ffprobe_or_ffmpeg_calls(tmp_path: Path) -> None:
    runner = FailingCommandRunner()
    source = EmbeddedSubtitleSource(enabled=False, extract_with_ffmpeg=True, extract_to=tmp_path / "cache", runner=runner)
    item = MediaItem(title="Movie", path=tmp_path / "media" / "Movie.mkv", kind="movie")

    assert source.find(item) == []
    with pytest.raises(ProviderError, match="disabled"):
        source.fetch(_embedded_candidate(tmp_path / "media" / "Movie.mkv", tmp_path / "cache" / "Movie.srt"))
    assert runner.calls == 0


def test_embedded_extraction_writes_only_under_configured_cache_dir(tmp_path: Path) -> None:
    media_dir = tmp_path / "readonly-media"
    cache_dir = tmp_path / "data" / "subtitles" / "embedded"
    media_dir.mkdir()
    media_path = media_dir / "Movie.mkv"
    media_path.write_bytes(b"fake video")
    runner = FakeCommandRunner()
    source = EmbeddedSubtitleSource(enabled=True, extract_with_ffmpeg=True, extract_to=cache_dir, runner=runner)
    item = MediaItem(title="Movie", path=media_path, kind="movie")

    candidates = source.find(item)
    extracted_path = source.fetch(candidates[0])

    assert extracted_path.read_text(encoding="utf-8").startswith("1\n")
    assert extracted_path.resolve().is_relative_to(cache_dir.resolve())
    assert list(media_dir.iterdir()) == [media_path]
    assert runner.commands[0][0] == "ffprobe"
    assert runner.commands[1][0] == "ffmpeg"
    assert runner.commands[1][-1] == str(extracted_path)
    metadata = source.metadata_for(extracted_path)
    assert metadata is not None
    assert metadata.provider == "embedded"
    assert metadata.media_path == str(media_path)
    assert metadata.stream_index == 2
    assert metadata.language == "eng"


def test_embedded_fetch_rejects_candidate_paths_outside_cache(tmp_path: Path) -> None:
    media_path = tmp_path / "media" / "Movie.mkv"
    outside_path = tmp_path / "media" / "Movie.srt"
    source = EmbeddedSubtitleSource(enabled=True, extract_with_ffmpeg=True, extract_to=tmp_path / "cache", runner=FakeCommandRunner())

    with pytest.raises(ProviderError, match="cache directory"):
        source.fetch(_embedded_candidate(media_path, outside_path))


def _embedded_candidate(media_path: Path, target_path: Path):
    from media_memory.subtitle_sources.base import SubtitleCandidate

    return SubtitleCandidate(
        provider="embedded",
        language="eng",
        raw={
            "embedded": {
                "media_path": str(media_path),
                "stream_index": 0,
                "language": "eng",
                "title": "English",
                "path": str(target_path),
            }
        },
    )
