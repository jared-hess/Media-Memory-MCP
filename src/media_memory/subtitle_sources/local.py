from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from media_memory.core.models import MediaItem, ProviderCandidate
from media_memory.subtitle_sources.base import SubtitleCandidate

SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}


class LocalSubtitleSource:
    """Read-only local sidecar subtitle source."""

    def __init__(self, *, extensions: Iterable[str] | None = None, roots: Iterable[Path | str] | None = None):
        self.extensions = {extension.lower() for extension in (extensions or SUBTITLE_EXTENSIONS)}
        self.roots = [Path(root) for root in (roots or [])]

    def find(self, item: MediaItem) -> list[Path]:
        return self.find_for_media(item)

    def find_for_media(self, media_item: MediaItem) -> list[Path]:
        media_dir = media_item.path.parent
        if self.roots and not _is_under_any_root(media_dir, self.roots):
            return []
        stem = media_item.path.stem
        candidates: list[Path] = []
        for path in sorted(media_dir.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in self.extensions:
                continue
            if path.stem == stem or path.name.startswith(f"{stem}."):
                candidates.append(path)
        return candidates

    def fetch(self, candidate: Path | SubtitleCandidate | ProviderCandidate) -> Path:
        if isinstance(candidate, Path):
            return candidate
        if isinstance(candidate, SubtitleCandidate) and candidate.path is not None:
            return candidate.path
        raise ValueError("Local subtitle candidates must include a filesystem path.")


LocalSidecarSubtitleSource = LocalSubtitleSource


def _is_under_any_root(path: Path, roots: list[Path]) -> bool:
    resolved_path = path.resolve()
    for root in roots:
        try:
            resolved_path.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False
