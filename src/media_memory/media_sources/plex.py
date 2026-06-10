from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib import parse, request
from xml.etree import ElementTree

from media_memory.core.models import MediaItem
from media_memory.media_sources.base import MediaRef, ProviderError


class PlexClient(Protocol):
    """Minimal HTTP client interface used by tests to avoid real network calls."""

    def get(self, path: str) -> bytes:
        """Return raw Plex XML for an API path."""


class UrllibPlexClient:
    """Small stdlib Plex HTTP client used only after Plex is explicitly enabled."""

    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def get(self, path: str) -> bytes:
        separator = "&" if "?" in path else "?"
        url = f"{self.base_url}{path}{separator}X-Plex-Token={parse.quote(self.token)}"
        with request.urlopen(url, timeout=self.timeout_seconds) as response:  # noqa: S310 - explicit opt-in local Plex URL.
            return response.read()


@dataclass(frozen=True)
class PlexLibrary:
    """A Plex library section."""

    key: str
    title: str
    type: str


class PlexMediaSource:
    """Plex media discovery that stays inert unless explicitly enabled."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        url: str | None = None,
        token: str | None = None,
        libraries: Iterable[str] | None = None,
        client: PlexClient | None = None,
    ) -> None:
        self.enabled = enabled
        self.url = url
        self.token = token
        self.libraries = list(libraries or [])
        self._client = client

    def scan(self) -> list[MediaItem | MediaRef]:
        if not self.enabled:
            return []
        items: list[MediaItem | MediaRef] = []
        for library in self.list_libraries():
            if not self._library_selected(library):
                continue
            items.extend(self.list_items(library.key))
        return items

    def list_libraries(self) -> list[PlexLibrary]:
        if not self.enabled:
            return []
        root = self._xml("/library/sections")
        libraries: list[PlexLibrary] = []
        for directory in root.findall("Directory"):
            key = directory.get("key")
            title = directory.get("title")
            library_type = directory.get("type") or "unknown"
            if key and title:
                libraries.append(PlexLibrary(key=key, title=title, type=library_type))
        return libraries

    def list_items(self, library_key: str) -> list[MediaItem]:
        if not self.enabled:
            return []
        root = self._xml(f"/library/sections/{parse.quote(library_key)}/all")
        return [
            item for video in root.iter("Video") if (item := _item_from_video(video)) is not None
        ]

    def _library_selected(self, library: PlexLibrary) -> bool:
        if not self.libraries:
            return True
        selected = {value.casefold() for value in self.libraries}
        return library.key.casefold() in selected or library.title.casefold() in selected

    def _xml(self, path: str) -> ElementTree.Element:
        try:
            return ElementTree.fromstring(self._client_or_default().get(path))
        except ElementTree.ParseError as exc:
            raise ProviderError(f"Plex returned invalid XML for {path}.") from exc

    def _client_or_default(self) -> PlexClient:
        if self._client is not None:
            return self._client
        if not self.url or not self.token:
            raise ProviderError("Plex media source requires url and token when enabled.")
        self._client = UrllibPlexClient(self.url, self.token)
        return self._client


def _item_from_video(video: ElementTree.Element) -> MediaItem | None:
    part = next(video.iter("Part"), None)
    file_path = part.get("file") if part is not None else None
    if not file_path:
        return None

    raw = {key: value for key, value in video.attrib.items() if value}
    rating_key = video.get("ratingKey") or video.get("key")
    kind = "episode" if video.get("type") == "episode" or video.get("grandparentTitle") else "movie"
    season = _int_or_none(video.get("parentIndex"))
    episode = _int_or_none(video.get("index"))
    runtime_seconds = _duration_seconds(video.get("duration"))
    title = video.get("title") or Path(file_path).stem
    provider_ids = {"plex_rating_key": rating_key} if rating_key else {}
    provider_refs = []
    if rating_key:
        provider_refs.append(
            {"provider": "plex", "id": rating_key, "namespace": "rating-key", "raw": raw}
        )

    return MediaItem(
        title=title,
        path=Path(file_path),
        kind=kind,
        season=season,
        episode=episode,
        show_title=video.get("grandparentTitle"),
        season_number=season,
        episode_number=episode,
        episode_title=title if kind == "episode" else None,
        year=_int_or_none(video.get("year")),
        runtime_seconds=runtime_seconds,
        provider_ids=provider_ids,
        provider_refs=provider_refs,
    )


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _duration_seconds(value: str | None) -> int | None:
    milliseconds = _int_or_none(value)
    if milliseconds is None:
        return None
    return round(milliseconds / 1000)
