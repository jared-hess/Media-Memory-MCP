from __future__ import annotations

from pathlib import Path

from media_memory.core.models import MediaItem

SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}


class LocalSidecarSubtitleSource:
    def find_for_media(self, media_item: MediaItem) -> list[Path]:
        media_dir = media_item.path.parent
        stem = media_item.path.stem
        candidates: list[Path] = []
        for path in sorted(media_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUBTITLE_EXTENSIONS:
                continue
            if path.stem == stem or path.name.startswith(f"{stem}."):
                candidates.append(path)
        return candidates
