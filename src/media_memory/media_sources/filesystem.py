from __future__ import annotations

import re
from pathlib import Path

from media_memory.core.models import MediaItem

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}
EPISODE_PATTERN = re.compile(r"[sS](\d{2})[eE](\d{2})")


class FilesystemMediaSource:
    def __init__(self, root: Path):
        self.root = root

    def scan(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            season = episode = None
            kind = "movie"
            match = EPISODE_PATTERN.search(path.name)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2))
                kind = "episode"
            items.append(
                MediaItem(
                    title=path.stem,
                    path=path,
                    kind=kind,
                    season=season,
                    episode=episode,
                )
            )
        return items
