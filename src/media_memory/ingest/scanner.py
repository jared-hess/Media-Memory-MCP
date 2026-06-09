from __future__ import annotations

from pathlib import Path

from media_memory.core.models import MediaItem
from media_memory.media_sources.filesystem import FilesystemMediaSource


def scan_media(root: Path) -> list[MediaItem]:
    return FilesystemMediaSource(root).scan()
