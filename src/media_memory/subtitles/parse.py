from __future__ import annotations

import re
from pathlib import Path

from media_memory.core.models import SubtitleChunk
from media_memory.subtitles.normalize import normalize_text

SRT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})")
ASS_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[.](\d{2})")
MAX_TIMESTAMP_MS = 24 * 60 * 60 * 1000


def parse_subtitle_file(
    path: Path,
    media_path: str,
    season: int | None = None,
    episode: int | None = None,
) -> list[SubtitleChunk]:
    """Parse a supported subtitle file into timestamped chunks."""

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    if suffix == ".srt":
        return _parse_srt(text, media_path, str(path), season, episode)
    if suffix == ".vtt":
        return _parse_vtt(text, media_path, str(path), season, episode)
    if suffix in {".ass", ".ssa"}:
        return _parse_ass(text, media_path, str(path), season, episode)
    return []


def _parse_srt(
    text: str,
    media_path: str,
    subtitle_path: str,
    season: int | None,
    episode: int | None,
) -> list[SubtitleChunk]:
    blocks = re.split(r"\n\s*\n", text.strip())
    chunks: list[SubtitleChunk] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        ts_index = 1 if lines[0].isdigit() and len(lines) > 1 else 0
        ts_line = lines[ts_index]
        if "-->" not in ts_line:
            continue
        start, end = _parse_time_range(ts_line)
        if start is None or end is None:
            continue
        content = normalize_text("\n".join(lines[ts_index + 1 :]))
        if content:
            chunks.append(_chunk(media_path, subtitle_path, content, start, end, season, episode))
    return chunks


def _parse_vtt(
    text: str,
    media_path: str,
    subtitle_path: str,
    season: int | None,
    episode: int | None,
) -> list[SubtitleChunk]:
    lines = [line.rstrip("\n") for line in text.splitlines()]
    chunks: list[SubtitleChunk] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line.upper() == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION")):
            idx += 1
            continue
        if "-->" not in line and idx + 1 < len(lines) and "-->" in lines[idx + 1]:
            idx += 1
            line = lines[idx].strip()
        if "-->" not in line:
            idx += 1
            continue
        start, end = _parse_time_range(line)
        if start is None or end is None:
            idx += 1
            continue
        idx += 1
        content_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip():
            content_lines.append(lines[idx].strip())
            idx += 1
        content = normalize_text("\n".join(content_lines))
        if content:
            chunks.append(_chunk(media_path, subtitle_path, content, start, end, season, episode))
        idx += 1
    return chunks


def _parse_ass(
    text: str,
    media_path: str,
    subtitle_path: str,
    season: int | None,
    episode: int | None,
) -> list[SubtitleChunk]:
    chunks: list[SubtitleChunk] = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start = _parse_ass_time(parts[1].strip())
        end = _parse_ass_time(parts[2].strip())
        if start is None or end is None:
            continue
        content = normalize_text(parts[9])
        if content:
            chunks.append(_chunk(media_path, subtitle_path, content, start, end, season, episode))
    return chunks


def _chunk(
    media_path: str,
    subtitle_path: str,
    text: str,
    start_ms: int,
    end_ms: int,
    season: int | None,
    episode: int | None,
) -> SubtitleChunk:
    return SubtitleChunk(
        media_path=media_path,
        subtitle_path=subtitle_path,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        season=season,
        episode=episode,
    )


def _parse_time_range(value: str) -> tuple[int | None, int | None]:
    left, right = [part.strip() for part in value.split("-->", maxsplit=1)]
    return _parse_srt_time(left), _parse_srt_time(right)


def _parse_srt_time(value: str) -> int | None:
    match = SRT_TIME_RE.search(value)
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return _valid_timestamp(_to_ms(hours, minutes, seconds, millis))


def _parse_ass_time(value: str) -> int | None:
    match = ASS_TIME_RE.search(value)
    if not match:
        return None
    hours, minutes, seconds, centis = (int(part) for part in match.groups())
    return _valid_timestamp(_to_ms(hours, minutes, seconds, centis * 10))


def _to_ms(hours: int, minutes: int, seconds: int, millis: int) -> int:
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _valid_timestamp(value: int) -> int | None:
    if value < 0 or value > MAX_TIMESTAMP_MS:
        return None
    return value
