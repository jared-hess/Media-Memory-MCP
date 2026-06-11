from __future__ import annotations

import re
from pathlib import Path

from media_memory.core.models import MediaItem

EPISODE_RE = re.compile(
    r"(?P<show>.*?)\s*(?:[. _-]+)?[Ss](?P<season>\d{1,2})[ ._-]*[Ee](?P<episode>\d{1,3})(?:[. _-]+(?P<title>.*?))?$"
)
SEASON_FOLDER_RE = re.compile(r"season[ ._-]*(?P<season>\d{1,2})", re.IGNORECASE)
LEADING_EPISODE_RE = re.compile(r"^(?P<episode>\d{1,3})(?:[. _-]+(?P<title>.*?))?$")
MOVIE_PARENS_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\).*$")
MOVIE_DOTTED_YEAR_RE = re.compile(r"^(?P<title>.*?)[. _-]+(?P<year>\d{4})(?:[. _-]+.*)?$")
QUALITY_TOKENS = {
    "480p",
    "576p",
    "720p",
    "1080p",
    "2160p",
    "4k",
    "bluray",
    "brrip",
    "web",
    "webrip",
    "web-dl",
    "hdtv",
    "dl",
    "x264",
    "x265",
    "h264",
    "h265",
}


def identify_media_path(path: str | Path, *, corpus_id: str = "local") -> MediaItem:
    """Identify basic movie or episode metadata from a filename/path."""

    media_path = Path(path)
    stem = media_path.stem.strip()
    episode = _identify_episode(media_path, stem)
    if episode is not None:
        show_title, season_number, episode_number, episode_title = episode
        return MediaItem(
            title=episode_title or show_title,
            path=media_path,
            kind="episode",
            season=season_number,
            episode=episode_number,
            season_number=season_number,
            episode_number=episode_number,
            show_title=show_title,
            episode_title=episode_title,
            corpus_id=corpus_id,
        )

    movie_title, year = _identify_movie(stem)
    return MediaItem(
        title=movie_title, path=media_path, kind="movie", year=year, corpus_id=corpus_id
    )


def identify_filename(path: str | Path, *, corpus_id: str = "local") -> MediaItem:
    """Backward-friendly alias for filename identification."""

    return identify_media_path(path, corpus_id=corpus_id)


def identify_media(path: str | Path, *, corpus_id: str = "local") -> MediaItem:
    """Alias matching provider-style naming."""

    return identify_media_path(path, corpus_id=corpus_id)


def _identify_episode(path: Path, stem: str) -> tuple[str, int, int, str | None] | None:
    match = EPISODE_RE.match(stem)
    if match:
        show_title = _clean_title(match.group("show"))
        episode_title = _clean_title(match.group("title") or "") or None
        if not show_title:
            show_title = _show_from_parents(path) or stem
        return show_title, int(match.group("season")), int(match.group("episode")), episode_title

    season = _season_from_parents(path)
    leading_episode = LEADING_EPISODE_RE.match(stem)
    if season is not None and leading_episode:
        show_title = _show_from_parents(path) or _clean_title(path.parent.parent.name)
        episode_title = _clean_title(leading_episode.group("title") or "") or None
        return show_title, season, int(leading_episode.group("episode")), episode_title
    return None


def _identify_movie(stem: str) -> tuple[str, int | None]:
    parens = MOVIE_PARENS_RE.match(stem)
    if parens:
        return _clean_title(parens.group("title")), int(parens.group("year"))
    dotted = MOVIE_DOTTED_YEAR_RE.match(stem)
    if dotted and 1888 <= int(dotted.group("year")) <= 2100:
        return _clean_title(dotted.group("title")), int(dotted.group("year"))
    return _clean_title(stem), None


def _season_from_parents(path: Path) -> int | None:
    for parent in path.parents:
        match = SEASON_FOLDER_RE.search(parent.name)
        if match:
            return int(match.group("season"))
    return None


def _show_from_parents(path: Path) -> str | None:
    for parent in path.parents:
        if SEASON_FOLDER_RE.search(parent.name):
            return _clean_title(parent.parent.name)
    return _clean_title(path.parent.name) if path.parent.name else None


def _clean_title(value: str) -> str:
    words = [part for part in re.split(r"[. _-]+", value.strip(" ._-")) if part]
    while words and words[-1].lower() in QUALITY_TOKENS:
        words.pop()
    return " ".join(words).strip()
