from __future__ import annotations

from media_memory.core.models import SubtitleChunk


def chunk_subtitles(
    chunks: list[SubtitleChunk],
    *,
    max_chars: int = 240,
    join_within_ms: int = 3000,
) -> list[SubtitleChunk]:
    if not chunks:
        return []
    merged: list[SubtitleChunk] = []
    current = chunks[0]
    for nxt in chunks[1:]:
        current_len = len(current.text)
        next_len = len(nxt.text)
        gap_ok = (
            current.end_ms is not None
            and nxt.start_ms is not None
            and nxt.start_ms - current.end_ms <= join_within_ms
        )
        if (
            nxt.media_path == current.media_path
            and nxt.subtitle_path == current.subtitle_path
            and gap_ok
            and current_len + 1 + next_len <= max_chars
        ):
            current = SubtitleChunk(
                media_path=current.media_path,
                subtitle_path=current.subtitle_path,
                text=f"{current.text} {nxt.text}",
                start_ms=current.start_ms,
                end_ms=nxt.end_ms,
                season=current.season,
                episode=current.episode,
            )
            continue
        merged.append(current)
        current = nxt
    merged.append(current)
    return merged
