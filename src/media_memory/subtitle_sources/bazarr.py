from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from media_memory.core.models import MediaItem, ProviderCandidate
from media_memory.media_sources.base import ProviderError
from media_memory.subtitle_sources.base import SubtitleCandidate
from media_memory.subtitle_sources.local import SUBTITLE_EXTENSIONS, LocalSubtitleSource

PROVIDER_NAME = "bazarr"


class BazarrClient(Protocol):
    """Boundary for future Bazarr API lookups, used only when explicitly enabled."""

    def find(self, item: MediaItem) -> list[SubtitleCandidate]:
        """Return API-backed subtitle candidates for a media item."""


class BazarrSubtitleSource:
    """Opt-in Bazarr subtitle source with read-only filesystem support."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        url: str | None = None,
        api_key: str | None = None,
        api_enabled: bool = False,
        roots: Iterable[Path | str] | None = None,
        extensions: Iterable[str] | None = None,
        client: BazarrClient | None = None,
    ) -> None:
        self.enabled = enabled
        self.url = url
        self.api_key = api_key
        self.api_enabled = api_enabled
        self.roots = [Path(root) for root in (roots or [])]
        self.extensions = {extension.lower() for extension in (extensions or SUBTITLE_EXTENSIONS)}
        self.client = client
        self._local_source = LocalSubtitleSource(extensions=self.extensions)

    def find(self, item: MediaItem) -> list[SubtitleCandidate]:
        return self.find_for_media(item)

    def find_for_media(self, item: MediaItem) -> list[SubtitleCandidate]:
        if not self.enabled:
            return []
        candidates = [self._candidate_from_path(path, mode="sidecar") for path in self._local_source.find(item)]
        candidates.extend(self._candidate_from_path(path, mode="root") for path in self._find_in_roots(item))
        if not self.api_enabled:
            return _dedupe_candidates(candidates)
        if self.client is None:
            raise ProviderError("Bazarr API mode is enabled but no Bazarr API client is configured.")
        return _dedupe_candidates([*candidates, *self.client.find(item)])

    def fetch(self, candidate: Path | SubtitleCandidate | ProviderCandidate) -> Path:
        if isinstance(candidate, Path):
            return candidate
        if isinstance(candidate, SubtitleCandidate) and candidate.path is not None:
            return candidate.path
        if isinstance(candidate, ProviderCandidate):
            path = candidate.raw.get("path")
            if isinstance(path, str):
                return Path(path)
        if not self.enabled:
            raise ProviderError("Bazarr subtitle fetch requested while provider is disabled.")
        raise ProviderError("Bazarr subtitle candidate does not include a local filesystem path.")

    def _find_in_roots(self, item: MediaItem) -> list[Path]:
        if not self.roots:
            return []
        media_stem = item.path.stem
        matches: list[Path] = []
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in self.extensions:
                    continue
                if path.stem == media_stem or path.name.startswith(f"{media_stem}."):
                    matches.append(path)
        return matches

    def _candidate_from_path(self, path: Path, *, mode: str) -> SubtitleCandidate:
        return SubtitleCandidate(
            path=path,
            uri=path.as_uri() if path.is_absolute() else None,
            language=_language_hint(path),
            provider=PROVIDER_NAME,
            score=1.0,
            raw={PROVIDER_NAME: {"mode": mode, "path": str(path), "provenance": "bazarr-filesystem-subtitle"}},
        )


def _dedupe_candidates(candidates: list[SubtitleCandidate]) -> list[SubtitleCandidate]:
    seen: set[Path] = set()
    deduped: list[SubtitleCandidate] = []
    for candidate in candidates:
        if candidate.path is None:
            deduped.append(candidate)
            continue
        resolved = candidate.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate)
    return deduped


def _language_hint(path: Path) -> str | None:
    parts = path.stem.split(".")
    if len(parts) < 2:
        return None
    suffix = parts[-1].lower()
    return suffix if 2 <= len(suffix) <= 3 and suffix.isalpha() else None
