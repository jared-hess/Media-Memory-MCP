from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from media_memory.core.errors import ProviderError
from media_memory.core.models import MediaItem
from media_memory.subtitle_sources.opensubtitles import OpenSubtitlesSource


class FakeOpenSubtitlesClient:
    def __init__(
        self, search_results: list[dict[str, Any]] | None = None, content: bytes | None = None
    ) -> None:
        self.search_results = search_results or []
        self.content = content or b"1\n00:00:01,000 --> 00:00:02,000\nHello from cache.\n"
        self.auth_calls: list[dict[str, str]] = []
        self.search_calls: list[dict[str, object]] = []
        self.download_calls: list[str] = []

    def authenticate(self, *, api_key: str, username: str, password: str) -> str:
        self.auth_calls.append({"api_key": api_key, "username": username, "password": password})
        return "token"

    def search(self, *, token: str, params: dict[str, object]) -> list[dict[str, Any]]:
        assert token == "token"
        self.search_calls.append(dict(params))
        return self.search_results

    def download(self, *, token: str, file_id: str) -> bytes:
        assert token == "token"
        self.download_calls.append(file_id)
        return self.content


class FailingOpenSubtitlesClient:
    def __init__(self) -> None:
        self.calls = 0

    def authenticate(self, *, api_key: str, username: str, password: str) -> str:
        del api_key, username, password
        self.calls += 1
        raise AssertionError("Disabled OpenSubtitles should not authenticate")

    def search(self, *, token: str, params: dict[str, object]) -> list[dict[str, Any]]:
        del token, params
        self.calls += 1
        raise AssertionError("Disabled OpenSubtitles should not search")

    def download(self, *, token: str, file_id: str) -> bytes:
        del token, file_id
        self.calls += 1
        raise AssertionError("Disabled OpenSubtitles should not download")


def test_disabled_opensubtitles_performs_zero_auth_search_or_download_calls(tmp_path: Path) -> None:
    client = FailingOpenSubtitlesClient()
    source = OpenSubtitlesSource(
        enabled=False,
        api_key="key",
        username="user",
        password="pass",
        cache_dir=tmp_path,
        client=client,
    )
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    assert source.find(item) == []
    with pytest.raises(ProviderError, match="disabled"):
        source.fetch(_candidate("sub-1", "file-1"))
    assert client.calls == 0


def test_enabled_opensubtitles_requires_complete_credentials_before_network(tmp_path: Path) -> None:
    client = FakeOpenSubtitlesClient()
    source = OpenSubtitlesSource(
        enabled=True,
        api_key="key",
        username="user",
        password=None,
        cache_dir=tmp_path,
        client=client,
    )
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    with pytest.raises(ProviderError, match="missing credentials: password"):
        source.find(item)

    assert client.auth_calls == []
    assert client.search_calls == []
    assert client.download_calls == []


def test_search_uses_imdb_id_when_available(tmp_path: Path) -> None:
    client = FakeOpenSubtitlesClient([_raw_result("sub-1", "file-1", score=0.95)])
    source = _enabled_source(tmp_path, client)
    item = MediaItem(
        title="The Matrix",
        path=tmp_path / "The.Matrix.1999.mkv",
        kind="movie",
        provider_ids={"imdb": "tt0133093"},
    )

    candidates = source.find(item)

    assert len(candidates) == 1
    assert client.search_calls == [
        {"languages": "eng,en", "hearing_impaired": "exclude", "imdb_id": "0133093"}
    ]


def test_search_falls_back_to_title_year_and_episode_metadata(tmp_path: Path) -> None:
    movie_client = FakeOpenSubtitlesClient([_raw_result("movie-sub", "movie-file", score=0.95)])
    movie_source = _enabled_source(tmp_path / "movie", movie_client)
    movie = MediaItem(
        title="Example Movie", path=tmp_path / "Example.Movie.1984.mkv", kind="movie", year=1984
    )

    movie_source.find(movie)

    assert movie_client.search_calls == [
        {
            "languages": "eng,en",
            "hearing_impaired": "exclude",
            "query": "Example Movie",
            "year": 1984,
        }
    ]

    episode_client = FakeOpenSubtitlesClient(
        [_raw_result("episode-sub", "episode-file", score=0.95)]
    )
    episode_source = _enabled_source(tmp_path / "episode", episode_client)
    episode = MediaItem(
        title="Pilot",
        show_title="Example Show",
        path=tmp_path / "Example.Show.S01E01.mkv",
        kind="episode",
        season=1,
        episode=1,
    )

    episode_source.find(episode)

    assert episode_client.search_calls == [
        {
            "languages": "eng,en",
            "hearing_impaired": "exclude",
            "parent_feature": "Example Show",
            "episode_number": 1,
            "season_number": 1,
        }
    ]


def test_candidate_below_min_confidence_is_rejected_and_not_downloaded(tmp_path: Path) -> None:
    client = FakeOpenSubtitlesClient([_raw_result("sub-1", "file-1", score=0.4)])
    source = _enabled_source(tmp_path, client, min_match_confidence=0.85)
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    assert source.find(item) == []
    with pytest.raises(ProviderError, match="below the configured threshold"):
        source.fetch(_candidate("sub-1", "file-1", confidence=0.4))

    assert client.download_calls == []


def test_daily_download_budget_is_enforced_before_download(tmp_path: Path) -> None:
    client = FakeOpenSubtitlesClient([_raw_result("sub-1", "file-1", score=0.95)])
    source = _enabled_source(tmp_path, client, daily_download_budget=0)
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")
    candidate = source.find(item)[0]

    with pytest.raises(ProviderError, match="budget is exhausted"):
        source.fetch(candidate)

    assert client.download_calls == []


def test_cached_subtitle_is_reused_on_rerun_and_metadata_is_recorded(tmp_path: Path) -> None:
    subtitle_content = b"1\n00:00:01,000 --> 00:00:02,000\nCached subtitle.\n"
    client = FakeOpenSubtitlesClient(
        [_raw_result("sub-1", "file-1", score=0.96, license_status="trusted")], subtitle_content
    )
    source = _enabled_source(tmp_path, client)
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")

    candidate = source.find(item)[0]
    first_path = source.fetch(candidate)
    second_candidate = source.find(item)[0]
    second_path = source.fetch(second_candidate)

    assert first_path == second_path
    assert first_path.read_bytes() == subtitle_content
    assert client.download_calls == ["file-1"]
    metadata = source.metadata_for(first_path)
    assert metadata is not None
    assert metadata.provider == "opensubtitles"
    assert metadata.language == "en"
    assert metadata.confidence == 0.96
    assert metadata.checksum == hashlib.sha256(subtitle_content).hexdigest()
    assert metadata.license_status == "trusted"


def test_force_redownloads_cached_subtitle_without_skipping_budget(tmp_path: Path) -> None:
    client = FakeOpenSubtitlesClient([_raw_result("sub-1", "file-1", score=0.95)])
    source = _enabled_source(tmp_path, client, daily_download_budget=2)
    item = MediaItem(title="Movie", path=tmp_path / "Movie.mkv", kind="movie")
    candidate = source.find(item)[0]

    first_path = source.fetch(candidate)
    second_path = source.fetch(candidate, force=True)

    assert first_path == second_path
    assert client.download_calls == ["file-1", "file-1"]


def _enabled_source(
    cache_dir: Path,
    client: FakeOpenSubtitlesClient,
    *,
    daily_download_budget: int = 900,
    min_match_confidence: float = 0.85,
) -> OpenSubtitlesSource:
    return OpenSubtitlesSource(
        enabled=True,
        api_key="key",
        username="user",
        password="pass",
        cache_dir=cache_dir,
        client=client,
        daily_download_budget=daily_download_budget,
        min_match_confidence=min_match_confidence,
    )


def _raw_result(
    subtitle_id: str, file_id: str, *, score: float, license_status: str = "trusted"
) -> dict[str, Any]:
    return {
        "id": subtitle_id,
        "attributes": {
            "language": "en",
            "files": [{"file_id": file_id}],
            "score": score,
            "license_status": license_status,
        },
    }


def _candidate(subtitle_id: str, file_id: str, *, confidence: float = 0.95):
    return OpenSubtitlesSource(
        enabled=True, api_key="key", username="user", password="pass"
    )._candidate_from_result(
        MediaItem(title="Movie", path=Path("/media/Movie.mkv"), kind="movie"),
        _raw_result(subtitle_id, file_id, score=confidence),
    )
