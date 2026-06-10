from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from media_memory.core.models import MediaItem
from media_memory.media_sources.base import MediaRef

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}
EPISODE_PATTERN = re.compile(r"[sS](\d{2})[eE](\d{2})")


class FilesystemMediaSource:
    def __init__(
        self,
        root: Path | str | None = None,
        *,
        roots: Iterable[Path | str] | None = None,
        extensions: Iterable[str] | None = None,
    ):
        configured_roots = list(roots or [])
        if root is not None:
            configured_roots.insert(0, root)
        self.roots = [Path(value) for value in configured_roots]
        self.root = self.roots[0] if self.roots else Path(".")
        self.extensions = {extension.lower() for extension in (extensions or MEDIA_EXTENSIONS)}

    def scan(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for root in self.roots or [self.root]:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in self.extensions:
                    continue
                items.append(self._item_from_path(path))
        return items

    def refs(self) -> list[MediaRef]:
        """Return lightweight typed references for callers that do not need full items."""

        return [MediaRef(path=item.path, title=item.title, kind=item.kind) for item in self.scan()]

    @staticmethod
    def _item_from_path(path: Path) -> MediaItem:
        season = episode = None
        kind = "movie"
        match = EPISODE_PATTERN.search(path.name)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            kind = "episode"
        return MediaItem(
            title=path.stem,
            path=path,
            kind=kind,
            season=season,
            episode=episode,
        )
