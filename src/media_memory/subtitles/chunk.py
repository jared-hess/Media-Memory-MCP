from __future__ import annotations

from media_memory.core.models import SubtitleChunk


def chunk_subtitles(
    chunks: list[SubtitleChunk],
    *,
    window_seconds: int = 60,
    overlap_seconds: int = 15,
    min_chars: int = 80,
    max_chars: int = 1200,
) -> list[SubtitleChunk]:
    """Group subtitle cues into timestamp-preserving time windows."""

    _validate_window_options(
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    if not chunks:
        return []
    sorted_chunks = sorted(chunks, key=lambda chunk: chunk.start_ms or 0)
    windows: list[SubtitleChunk] = []
    window_ms = window_seconds * 1000
    step_ms = max(1, (window_seconds - overlap_seconds) * 1000)
    first_start = sorted_chunks[0].start_ms or 0
    last_end = max((chunk.end_ms or chunk.start_ms or first_start) for chunk in sorted_chunks)
    window_start = first_start

    while window_start <= last_end:
        window_end = window_start + window_ms
        selected = [
            chunk
            for chunk in sorted_chunks
            if _overlaps(chunk.start_ms, chunk.end_ms, window_start, window_end)
        ]
        if selected:
            candidate = _build_window(selected, max_chars=max_chars)
            if len(candidate.text) >= min_chars or not windows:
                windows.append(candidate)
            else:
                windows[-1] = _combine(windows[-1], candidate, max_chars=max_chars)
        window_start += step_ms

    return _dedupe_windows(windows)


def legacy_chunk_subtitles(
    chunks: list[SubtitleChunk],
    *,
    max_chars: int = 240,
    join_within_ms: int = 3000,
) -> list[SubtitleChunk]:
    """Merge nearby subtitle cues using the scaffold-era behavior."""

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")
    if join_within_ms < 0:
        raise ValueError("join_within_ms must be non-negative")
    if not chunks:
        return []
    merged: list[SubtitleChunk] = []
    current = chunks[0]
    for nxt in chunks[1:]:
        gap_ok = (
            current.end_ms is not None
            and nxt.start_ms is not None
            and nxt.start_ms - current.end_ms <= join_within_ms
        )
        if (
            nxt.media_path == current.media_path
            and nxt.subtitle_path == current.subtitle_path
            and gap_ok
            and len(current.text) + 1 + len(nxt.text) <= max_chars
        ):
            current = _copy_chunk(current, text=f"{current.text} {nxt.text}", end_ms=nxt.end_ms)
            continue
        merged.append(current)
        current = nxt
    merged.append(current)
    return merged


def _validate_window_options(
    *,
    window_seconds: int,
    overlap_seconds: int,
    min_chars: int,
    max_chars: int,
) -> None:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be greater than 0")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds must be non-negative")
    if overlap_seconds >= window_seconds:
        raise ValueError("overlap_seconds must be less than window_seconds")
    if min_chars < 0:
        raise ValueError("min_chars must be non-negative")
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")


def _overlaps(
    start_ms: int | None,
    end_ms: int | None,
    window_start_ms: int,
    window_end_ms: int,
) -> bool:
    start = start_ms or 0
    end = end_ms if end_ms is not None else start
    return start < window_end_ms and end >= window_start_ms


def _build_window(chunks: list[SubtitleChunk], *, max_chars: int) -> SubtitleChunk:
    text_parts: list[str] = []
    for chunk in chunks:
        next_text = " ".join([*text_parts, chunk.text]).strip()
        if text_parts and len(next_text) > max_chars:
            break
        text_parts.append(chunk.text)
    return _copy_chunk(
        chunks[0],
        text=" ".join(text_parts),
        start_ms=chunks[0].start_ms,
        end_ms=chunks[min(len(text_parts), len(chunks)) - 1].end_ms,
    )


def _combine(left: SubtitleChunk, right: SubtitleChunk, *, max_chars: int) -> SubtitleChunk:
    text = f"{left.text} {right.text}".strip()
    if len(text) > max_chars:
        return left
    return _copy_chunk(left, text=text, end_ms=right.end_ms)


def _dedupe_windows(chunks: list[SubtitleChunk]) -> list[SubtitleChunk]:
    deduped: list[SubtitleChunk] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    for chunk in chunks:
        key = (chunk.text, chunk.start_ms, chunk.end_ms)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped


def _copy_chunk(
    chunk: SubtitleChunk,
    *,
    text: str,
    start_ms: int | None | object = ...,
    end_ms: int | None | object = ...,
) -> SubtitleChunk:
    return chunk.model_copy(
        update={
            "text": text,
            "start_ms": chunk.start_ms if start_ms is ... else start_ms,
            "end_ms": chunk.end_ms if end_ms is ... else end_ms,
        }
    )
