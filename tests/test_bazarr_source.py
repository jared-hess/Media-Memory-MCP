from __future__ import annotations

from pathlib import Path

import pytest

from media_memory.core.errors import ProviderError
from media_memory.core.models import MediaItem
from media_memory.subtitle_sources.bazarr import BazarrSubtitleSource


class FailingBazarrClient:
    def __init__(self) -> None:
        self.calls = 0

    def find(self, item: MediaItem):
        del item
        self.calls += 1
        raise AssertionError("Bazarr API should not be called unless api_enabled is true")


def test_disabled_bazarr_performs_zero_api_calls(tmp_path: Path) -> None:
    client = FailingBazarrClient()
    source = BazarrSubtitleSource(
        enabled=False,
        url="https://bazarr.example",
        api_key="secret",
        api_enabled=True,
        roots=[tmp_path],
        client=client,
    )
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    assert source.find(item) == []
    with pytest.raises(ProviderError, match="disabled"):
        source.fetch(_pathless_candidate())
    assert client.calls == 0


def test_bazarr_filesystem_mode_discovers_sidecar_without_api_calls(tmp_path: Path) -> None:
    client = FailingBazarrClient()
    media_path = tmp_path / "media" / "Movie.mkv"
    subtitle_path = tmp_path / "media" / "Movie.en.srt"
    media_path.parent.mkdir()
    media_path.write_bytes(b"fake video")
    subtitle_path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nBazarr sidecar.\n", encoding="utf-8"
    )
    source = BazarrSubtitleSource(enabled=True, api_enabled=False, client=client)

    candidates = source.find(MediaItem(title="Movie", path=media_path, kind="movie"))
    fetched_path = source.fetch(candidates[0])

    assert fetched_path == subtitle_path
    assert candidates[0].provider == "bazarr"
    assert candidates[0].language == "en"
    assert candidates[0].raw["bazarr"]["mode"] == "sidecar"
    assert candidates[0].raw["bazarr"]["provenance"] == "bazarr-filesystem-subtitle"
    assert client.calls == 0


def test_bazarr_filesystem_mode_discovers_configured_export_root(tmp_path: Path) -> None:
    media_path = tmp_path / "media" / "Movie.mkv"
    bazarr_root = tmp_path / "bazarr"
    subtitle_path = bazarr_root / "nested" / "Movie.eng.srt"
    media_path.parent.mkdir()
    bazarr_root.mkdir()
    subtitle_path.parent.mkdir()
    media_path.write_bytes(b"fake video")
    subtitle_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nBazarr export.\n", encoding="utf-8")
    source = BazarrSubtitleSource(enabled=True, roots=[bazarr_root])

    candidates = source.find(MediaItem(title="Movie", path=media_path, kind="movie"))

    assert [candidate.path for candidate in candidates] == [subtitle_path]
    assert candidates[0].raw["bazarr"]["mode"] == "root"


def test_bazarr_api_mode_requires_explicit_client_after_filesystem_lookup(tmp_path: Path) -> None:
    source = BazarrSubtitleSource(enabled=True, api_enabled=True, roots=[tmp_path / "missing"])
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    with pytest.raises(ProviderError, match="API mode"):
        source.find(item)


def _pathless_candidate():
    from media_memory.subtitle_sources.base import SubtitleCandidate

    return SubtitleCandidate(provider="bazarr", raw={"bazarr": {"mode": "api"}})
