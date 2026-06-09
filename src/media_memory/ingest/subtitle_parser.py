from __future__ import annotations

import re
from pathlib import Path

from media_memory.core.models import SubtitleChunk

SRT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
ASS_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[.](\d{2})")
TIMECODE_CLEAN_RE = re.compile(r"<[^>]+>|\{\\[^}]+\}")


def parse_subtitle_file(path: Path, media_path: str, season: int | None = None, episode: int | None = None) -> list[SubtitleChunk]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".srt":
        return _parse_srt(text, media_path, str(path), season, episode)
    if suffix == ".vtt":
        return _parse_vtt(text, media_path, str(path), season, episode)
    if suffix in {".ass", ".ssa"}:
        return _parse_ass(text, media_path, str(path), season, episode)
    return []


def normalize_text(value: str) -> str:
    cleaned = TIMECODE_CLEAN_RE.sub("", value)
    cleaned = cleaned.replace("\\N", " ").replace("\\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _to_ms(hours: int, minutes: int, seconds: int, millis: int) -> int:
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _parse_srt(text: str, media_path: str, subtitle_path: str, season: int | None, episode: int | None) -> list[SubtitleChunk]:
    blocks = re.split(r"\n\s*\n", text.strip())
    chunks: list[SubtitleChunk] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        ts_line = lines[1] if lines[0].isdigit() else lines[0]
        if "-->" not in ts_line:
            continue
        left, right = [part.strip() for part in ts_line.split("-->", maxsplit=1)]
        start = _parse_srt_time(left)
        end = _parse_srt_time(right)
        if start is None or end is None:
            continue
        content_lines = lines[2:] if lines[0].isdigit() else lines[1:]
        content = normalize_text(" ".join(content_lines))
        if not content:
            continue
        chunks.append(
            SubtitleChunk(
                media_path=media_path,
                subtitle_path=subtitle_path,
                text=content,
                start_ms=start,
                end_ms=end,
                season=season,
                episode=episode,
            )
        )
    return chunks


def _parse_vtt(text: str, media_path: str, subtitle_path: str, season: int | None, episode: int | None) -> list[SubtitleChunk]:
    lines = [line.rstrip("\n") for line in text.splitlines()]
    chunks: list[SubtitleChunk] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if "-->" not in line:
            idx += 1
            continue
        left, right = [part.strip() for part in line.split("-->", maxsplit=1)]
        start = _parse_srt_time(left)
        end = _parse_srt_time(right)
        if start is None or end is None:
            idx += 1
            continue
        idx += 1
        content_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip():
            content_lines.append(lines[idx].strip())
            idx += 1
        content = normalize_text(" ".join(content_lines))
        if content:
            chunks.append(
                SubtitleChunk(
                    media_path=media_path,
                    subtitle_path=subtitle_path,
                    text=content,
                    start_ms=start,
                    end_ms=end,
                    season=season,
                    episode=episode,
                )
            )
        idx += 1
    return chunks


def _parse_ass(text: str, media_path: str, subtitle_path: str, season: int | None, episode: int | None) -> list[SubtitleChunk]:
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
        if not content:
            continue
        chunks.append(
            SubtitleChunk(
                media_path=media_path,
                subtitle_path=subtitle_path,
                text=content,
                start_ms=start,
                end_ms=end,
                season=season,
                episode=episode,
            )
        )
    return chunks


def _parse_srt_time(value: str) -> int | None:
    match = SRT_TIME_RE.search(value)
    if not match:
        return None
    return _to_ms(*(int(part) for part in match.groups()))


def _parse_ass_time(value: str) -> int | None:
    match = ASS_TIME_RE.search(value)
    if not match:
        return None
    hours, minutes, seconds, centiseconds = (int(part) for part in match.groups())
    return _to_ms(hours, minutes, seconds, centiseconds * 10)
