from __future__ import annotations

from media_memory.core.models import SubtitleChunk
from media_memory.subtitles.chunk import legacy_chunk_subtitles


def chunk_subtitles(
    chunks: list[SubtitleChunk],
    *,
    max_chars: int = 240,
    join_within_ms: int = 3000,
) -> list[SubtitleChunk]:
    return legacy_chunk_subtitles(chunks, max_chars=max_chars, join_within_ms=join_within_ms)
